"""Gradle build-script parser (Groovy and Kotlin DSL) with source-line tracking.

Extracts the P0-relevant facts a Kubernetes migration needs from a Gradle build:
applied plugins (with versions), declared dependencies (with configuration and
coordinate), the Java toolchain / source compatibility, and the project group and
version. Companion ``settings.gradle`` (``rootProject.name``) and
``gradle-wrapper.properties`` (pinned Gradle version) facts are attached by the
caller.

This is a line- and block-oriented parser in the spirit of ``nginx.py``: Groovy
and Kotlin build scripts have no clean structural Python parser, so we locate the
``plugins { }`` and ``dependencies { }`` blocks by brace depth and read the
recognised declarations line by line, always reporting the real source range.
Constructs the parser does not understand are recorded as ``ParseIssue`` rather
than being silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .common import Located, ParseIssue
from .version_catalog import VersionCatalog

# Version-catalog accessor references: `alias(libs.plugins.spring.boot)` in a
# plugins block, and `implementation libs.spring.starter.webflux` in a
# dependencies block. Resolved to real coordinates via `apply_version_catalog`.
_CATALOG_PLUGIN_RE = re.compile(r"^\s*alias\(\s*(libs\.[\w.]+)\s*\)")
_CATALOG_DEP_RE = re.compile(r"^\s*(?P<cfg>[a-zA-Z][\w]*)\s*[(\s]\s*(?P<acc>libs\.[\w.]+)")

# Gradle dependency configurations we recognise on a declaration line.
_DEP_CONFIGURATIONS = (
    "implementation",
    "api",
    "compileOnly",
    "compileOnlyApi",
    "runtimeOnly",
    "developmentOnly",
    "testAndDevelopmentOnly",
    "annotationProcessor",
    "testImplementation",
    "testCompileOnly",
    "testRuntimeOnly",
    "testAnnotationProcessor",
    "integrationTestImplementation",
    "providedRuntime",
    "providedCompile",
    "checkstyle",
    "modules",
)

# id 'x' [version 'y']  /  id("x") [version "y"]  /  alias(...) is unsupported.
_PLUGIN_RE = re.compile(
    r"""^\s*id\s*[(\s]\s*['"]([\w.\-]+)['"]\s*\)?      # plugin id
        (?:\s*version\s*[(\s]?\s*['"]([^'"]+)['"])?    # optional version
    """,
    re.VERBOSE,
)
# Bare Kotlin/Groovy plugin accessors, e.g. `java`, `application`, `kotlin("jvm")`.
_PLUGIN_ACCESSOR_RE = re.compile(r"^\s*([a-zA-Z][\w.\-]*)\b(?!\s*[({'\"])\s*$")
_KOTLIN_PLUGIN_CALL_RE = re.compile(r"^\s*(kotlin|id)\s*\(\s*['\"]([\w.\-]+)['\"]")

# configuration 'group:artifact[:version]'  /  configuration("...")
_DEP_RE = re.compile(
    r"""^\s*(?P<cfg>[a-zA-Z][\w]*)\s*      # configuration name
        [(\s]\s*                            # '(' or whitespace
        ['"](?P<coord>[^'"]+)['"]           # first quoted coordinate/notation
    """,
    re.VERBOSE,
)
_PLATFORM_RE = re.compile(r"\b(?:enforced)?[Pp]latform\s*\(")
_PROJECT_DEP_RE = re.compile(r"\bproject\s*\(")

_TOOLCHAIN_RE = re.compile(r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)")
_SOURCECOMPAT_RE = re.compile(
    r"""sourceCompatibility\s*=\s*
        (?:['"](?P<str>[\d.]+)['"]|JavaVersion\.VERSION_(?P<enum>\d+))""",
    re.VERBOSE,
)
_GROUP_RE = re.compile(r"^\s*group\s*=\s*['\"]([^'\"]+)['\"]")
_VERSION_RE = re.compile(r"^\s*version\s*=\s*['\"]([^'\"]+)['\"]")


@dataclass
class GradlePlugin:
    id: str
    version: str | None
    location: Located


@dataclass
class GradleDependency:
    configuration: str
    coordinate: str
    group: str | None
    artifact: str | None
    version: str | None
    location: Located


@dataclass
class GradleBuild:
    path: str
    is_kotlin: bool = False
    plugins: list[GradlePlugin] = field(default_factory=list)
    dependencies: list[GradleDependency] = field(default_factory=list)
    # Version-catalog references captured verbatim; resolved by the caller once
    # the catalog is available (`apply_version_catalog`).
    plugin_alias_refs: list[tuple[str, Located]] = field(default_factory=list)
    dependency_alias_refs: list[tuple[str, str, Located]] = field(default_factory=list)
    group: str | None = None
    version: str | None = None
    java_version: str | None = None
    java_version_line: tuple[int, int] | None = None
    java_version_selector: str | None = None
    # Attached by the caller from companion files.
    root_project_name: str | None = None
    root_project_name_location: Located | None = None
    wrapper_gradle_version: str | None = None
    wrapper_location: Located | None = None
    issues: list[ParseIssue] = field(default_factory=list)

    def plugin(self, plugin_id: str) -> GradlePlugin | None:
        for plugin in self.plugins:
            if plugin.id == plugin_id:
                return plugin
        return None

    def plugin_prefixed(self, prefix: str) -> GradlePlugin | None:
        for plugin in self.plugins:
            if plugin.id.startswith(prefix):
                return plugin
        return None

    def has_dependency(self, group_prefix: str, artifact_sub: str = "") -> bool:
        return self.find_dependency(group_prefix, artifact_sub) is not None

    def find_dependency(
        self, group_prefix: str, artifact_sub: str = ""
    ) -> GradleDependency | None:
        for dep in self.dependencies:
            group = dep.group or ""
            artifact = dep.artifact or ""
            if group.startswith(group_prefix) and artifact_sub in artifact:
                return dep
        return None

    @property
    def artifact_base_name(self) -> str | None:
        """The bootJar base name derived from project metadata, e.g.
        ``spring-petclinic-4.0.0-SNAPSHOT`` (name + version)."""

        name = self.root_project_name
        if name is None:
            return None
        if self.version:
            return f"{name}-{self.version}"
        return name


def _split_coordinate(coord: str) -> tuple[str | None, str | None, str | None]:
    """Split ``group:artifact:version`` (version may itself be a ``${...}``)."""

    # Only split on the first two colons; a version placeholder may contain none.
    parts = coord.split(":")
    if len(parts) == 1:
        # Not a maven-style coordinate (e.g. a file path or bare name).
        return None, parts[0] or None, None
    group = parts[0] or None
    artifact = parts[1] or None
    version = ":".join(parts[2:]) if len(parts) > 2 else None
    return group, artifact, version


def _extract_block(
    lines: list[str], header_pattern: re.Pattern[str]
) -> tuple[int, int, list[tuple[int, str]]] | None:
    """Return ``(start_line, end_line, [(line_no, text), ...])`` for the first
    brace block whose opening line matches ``header_pattern`` (which must also
    include the ``{``). Line numbers are 1-based."""

    for index, line in enumerate(lines):
        if header_pattern.search(line) and "{" in line:
            depth = line.count("{") - line.count("}")
            inner: list[tuple[int, str]] = []
            end = index
            cursor = index + 1
            while cursor < len(lines) and depth > 0:
                current = lines[cursor]
                new_depth = depth + current.count("{") - current.count("}")
                # Exclude the line that closes the block back to depth 0.
                if new_depth > 0:
                    inner.append((cursor + 1, current))
                depth = new_depth
                end = cursor
                cursor += 1
            return index + 1, end + 1, inner
    return None


def _parse_plugins(lines: list[str], build: GradleBuild) -> None:
    block = _extract_block(lines, re.compile(r"^\s*plugins\b"))
    if block is None:
        return
    _, _, inner = block
    for line_no, text in inner:
        stripped = text.strip()
        if not stripped or stripped.startswith(("//", "/*", "*")):
            continue
        catalog_ref = _CATALOG_PLUGIN_RE.match(text)
        if catalog_ref is not None:
            accessor = catalog_ref.group(1)
            build.plugin_alias_refs.append(
                (accessor, Located(accessor, "plugin.alias", line_no, line_no))
            )
            continue
        match = _PLUGIN_RE.match(text)
        if match is None:
            match = _KOTLIN_PLUGIN_CALL_RE.match(text)
            if match is not None:
                plugin_id = match.group(2)
                build.plugins.append(
                    GradlePlugin(
                        id=plugin_id,
                        version=None,
                        location=Located(plugin_id, "plugin", line_no, line_no),
                    )
                )
                continue
            accessor = _PLUGIN_ACCESSOR_RE.match(text)
            if accessor is not None:
                plugin_id = accessor.group(1)
                build.plugins.append(
                    GradlePlugin(
                        id=plugin_id,
                        version=None,
                        location=Located(plugin_id, "plugin", line_no, line_no),
                    )
                )
                continue
            build.issues.append(
                ParseIssue("gradle_plugin", f"unrecognised plugin declaration: {stripped!r}")
            )
            continue
        plugin_id, version = match.group(1), match.group(2)
        build.plugins.append(
            GradlePlugin(
                id=plugin_id,
                version=version,
                location=Located(plugin_id, "plugin", line_no, line_no),
            )
        )


def _parse_dependencies(lines: list[str], build: GradleBuild) -> None:
    block = _extract_block(lines, re.compile(r"^\s*dependencies\b"))
    if block is None:
        return
    _, _, inner = block
    for line_no, text in inner:
        stripped = text.strip()
        if not stripped or stripped.startswith(("//", "/*", "*")):
            continue
        match = _DEP_RE.match(text)
        if match is None:
            catalog_ref = _CATALOG_DEP_RE.match(text)
            if catalog_ref is not None and catalog_ref.group("cfg") in _DEP_CONFIGURATIONS:
                cfg, accessor = catalog_ref.group("cfg"), catalog_ref.group("acc")
                build.dependency_alias_refs.append(
                    (cfg, accessor, Located(accessor, f"dependency[{accessor}]", line_no, line_no))
                )
            continue
        cfg = match.group("cfg")
        if cfg not in _DEP_CONFIGURATIONS:
            continue
        if _PLATFORM_RE.search(text) or _PROJECT_DEP_RE.search(text):
            build.issues.append(
                ParseIssue(
                    "gradle_dependency",
                    f"non-coordinate dependency not modelled: {stripped!r}",
                )
            )
            continue
        coord = match.group("coord")
        group, artifact, version = _split_coordinate(coord)
        build.dependencies.append(
            GradleDependency(
                configuration=cfg,
                coordinate=coord,
                group=group,
                artifact=artifact,
                version=version,
                location=Located(coord, f"dependency[{artifact or coord}]", line_no, line_no),
            )
        )


def _parse_java_version(lines: list[str], build: GradleBuild) -> None:
    for index, line in enumerate(lines):
        match = _TOOLCHAIN_RE.search(line)
        if match is not None:
            build.java_version = match.group(1)
            build.java_version_line = (index + 1, index + 1)
            build.java_version_selector = "java.toolchain.languageVersion"
            return
    for index, line in enumerate(lines):
        match = _SOURCECOMPAT_RE.search(line)
        if match is not None:
            build.java_version = match.group("str") or match.group("enum")
            build.java_version_line = (index + 1, index + 1)
            build.java_version_selector = "sourceCompatibility"
            return


def _parse_group_version(lines: list[str], build: GradleBuild) -> None:
    for line in lines:
        if build.group is None:
            gmatch = _GROUP_RE.match(line)
            if gmatch is not None:
                build.group = gmatch.group(1)
        if build.version is None:
            vmatch = _VERSION_RE.match(line)
            if vmatch is not None:
                build.version = vmatch.group(1)


def parse_gradle(text: str, path: str) -> GradleBuild:
    """Parse a ``build.gradle`` (Groovy) or ``build.gradle.kts`` (Kotlin) file."""

    build = GradleBuild(path=path, is_kotlin=path.endswith(".kts"))
    lines = text.splitlines()
    _parse_plugins(lines, build)
    _parse_dependencies(lines, build)
    _parse_java_version(lines, build)
    _parse_group_version(lines, build)
    return build


def apply_version_catalog(build: GradleBuild, catalog: VersionCatalog) -> None:
    """Resolve captured ``libs.…`` accessors to real plugins/dependencies.

    Runs after both the build script and the catalog are parsed. Unresolved
    accessors are recorded as ``ParseIssue`` (never silently dropped)."""

    for accessor, location in build.plugin_alias_refs:
        plugin_id = catalog.plugin(accessor)
        if plugin_id is not None:
            build.plugins.append(GradlePlugin(id=plugin_id, version=None, location=location))
        else:
            build.issues.append(
                ParseIssue("gradle_catalog_plugin", f"unresolved catalog plugin: {accessor}")
            )
    for cfg, accessor, location in build.dependency_alias_refs:
        module = catalog.library(accessor)
        if module is not None:
            group, artifact, _ = _split_coordinate(module)
            build.dependencies.append(
                GradleDependency(
                    configuration=cfg,
                    coordinate=module,
                    group=group,
                    artifact=artifact,
                    version=catalog.library_version(accessor),
                    location=location,
                )
            )
        else:
            build.issues.append(
                ParseIssue("gradle_catalog_dependency", f"unresolved catalog dependency: {accessor}")
            )


_ROOT_NAME_RE = re.compile(r"""rootProject\.name\s*=\s*['"]([^'"]+)['"]""")


def parse_settings(text: str, path: str) -> tuple[str, Located] | None:
    """Extract ``rootProject.name`` from ``settings.gradle`` (Groovy or Kotlin)."""

    for index, line in enumerate(text.splitlines()):
        match = _ROOT_NAME_RE.search(line)
        if match is not None:
            name = match.group(1)
            return name, Located(name, "rootProject.name", index + 1, index + 1)
    return None


_WRAPPER_DIST_RE = re.compile(r"gradle-([\d.]+)-(?:bin|all)\.zip")


def parse_gradle_wrapper(text: str, path: str) -> tuple[str, Located] | None:
    """Extract the pinned Gradle version from ``gradle-wrapper.properties``."""

    for index, line in enumerate(text.splitlines()):
        if line.strip().startswith("distributionUrl"):
            match = _WRAPPER_DIST_RE.search(line)
            if match is not None:
                version = match.group(1)
                return version, Located(version, "distributionUrl", index + 1, index + 1)
    return None
