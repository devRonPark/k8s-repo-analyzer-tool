"""Maven ``pom.xml`` parser with source-line tracking.

Extracts the P0-relevant facts a Kubernetes migration needs from a Maven build:
packaging, final artifact name, Java version, declared dependencies (with
scope), build plugins, and per-profile application-server bindings. Values that
reference Maven properties (``${...}``) are resolved against the ``<properties>``
block where the property is known; unresolved references are left verbatim.

Nothing here decides operational values; it only reports what the POM states,
each fact carrying the real line range of its structural node.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .common import Located, ParseIssue
from .xml_source import XmlNode, parse_xml

_PROP_REF = re.compile(r"\$\{([^}]+)\}")


@dataclass
class MavenDependency:
    group_id: str
    artifact_id: str
    version: str | None
    scope: str
    location: Located


@dataclass
class MavenProfile:
    id: str
    active_by_default: bool
    properties: dict[str, str]
    container_id: str | None  # cargo container id, resolved where possible
    location: Located


@dataclass
class MavenPlugin:
    group_id: str
    artifact_id: str
    location: Located


@dataclass
class MavenProject:
    path: str
    group_id: str | None = None
    artifact_id: str | None = None
    version: str | None = None
    packaging: str = "jar"
    name: str | None = None
    final_name: str | None = None
    java_version: str | None = None
    properties: dict[str, str] = field(default_factory=dict)
    property_lines: dict[str, tuple[int, int]] = field(default_factory=dict)
    dependencies: list[MavenDependency] = field(default_factory=list)
    profiles: list[MavenProfile] = field(default_factory=list)
    build_plugins: list[MavenPlugin] = field(default_factory=list)
    packaging_line: tuple[int, int] | None = None
    final_name_line: tuple[int, int] | None = None
    java_version_line: tuple[int, int] | None = None
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def artifact_file_name(self) -> str | None:
        """The build output file name, e.g. ``jpetstore.war`` or ``app-1.0.jar``."""

        base = self.final_name
        if base is None and self.artifact_id is not None:
            base = self.artifact_id
            if self.version is not None:
                base = f"{self.artifact_id}-{self.version}"
        if base is None:
            return None
        return f"{base}.{self.packaging}"

    def default_profile(self) -> MavenProfile | None:
        for profile in self.profiles:
            if profile.active_by_default:
                return profile
        return None

    def has_dependency(self, group_prefix: str, artifact_prefix: str = "") -> bool:
        for dep in self.dependencies:
            if dep.group_id.startswith(group_prefix) and dep.artifact_id.startswith(
                artifact_prefix
            ):
                return True
        return False


def _resolve(value: str | None, properties: dict[str, str]) -> str | None:
    """Resolve ``${prop}`` references using ``properties`` (bounded passes)."""

    if value is None:
        return None
    resolved = value
    for _ in range(5):
        match = _PROP_REF.search(resolved)
        if match is None:
            return resolved
        replaced = _PROP_REF.sub(
            lambda m: properties.get(m.group(1), m.group(0)), resolved
        )
        if replaced == resolved:
            return resolved
        resolved = replaced
    return resolved


def _collect_properties(
    root: XmlNode,
) -> tuple[dict[str, str], dict[str, tuple[int, int]]]:
    props: dict[str, str] = {}
    lines: dict[str, tuple[int, int]] = {}
    node = root.first("properties")
    if node is not None:
        for child in node.children:
            props[child.tag] = child.text.strip()
            lines[child.tag] = (child.start_line, child.end_line)
    return props, lines


_JAVA_VERSION_KEYS = (
    "java.version",
    "java.release.version",
    "maven.compiler.release",
    "maven.compiler.source",
    "maven.compiler.target",
)


def _java_version(properties: dict[str, str]) -> tuple[str | None, str | None]:
    for key in _JAVA_VERSION_KEYS:
        if key in properties and properties[key].strip():
            return _resolve(properties[key], properties), key
    return None, None


def _located(node: XmlNode, path: str, selector: str) -> Located:
    return Located(
        value=node.text.strip(),
        selector=selector,
        start_line=node.start_line,
        end_line=node.end_line,
    )


def parse_maven(text: str, path: str) -> MavenProject:
    project = MavenProject(path=path)
    doc = parse_xml(text, path)
    project.issues.extend(doc.issues)
    root = doc.root
    if root is None or root.tag != "project":
        if not project.issues:
            project.issues.append(ParseIssue("maven_root", "no <project> root element"))
        return project

    properties, property_lines = _collect_properties(root)
    project.properties = properties
    project.property_lines = property_lines

    project.group_id = root.text_of("groupId")
    project.artifact_id = root.text_of("artifactId")
    project.version = _resolve(root.text_of("version"), properties)
    project.name = root.text_of("name")

    packaging_node = root.first("packaging")
    if packaging_node is not None:
        project.packaging = (packaging_node.text.strip() or "jar").lower()
        project.packaging_line = (packaging_node.start_line, packaging_node.end_line)

    java_version, java_key = _java_version(properties)
    project.java_version = java_version
    if java_key is not None and java_key in property_lines:
        project.java_version_line = property_lines[java_key]

    build = root.first("build")
    if build is not None:
        final_name_node = build.first("finalName")
        if final_name_node is not None:
            project.final_name = _resolve(final_name_node.text.strip(), properties)
            project.final_name_line = (
                final_name_node.start_line,
                final_name_node.end_line,
            )
        project.build_plugins = _collect_plugins(build, path)

    for deps in root.find("dependencies"):
        project.dependencies.extend(_collect_dependencies(deps, path, properties))

    profiles_node = root.first("profiles")
    if profiles_node is not None:
        for profile_node in profiles_node.find("profile"):
            project.profiles.append(_parse_profile(profile_node, path, properties))

    return project


def _collect_dependencies(
    deps_node: XmlNode, path: str, properties: dict[str, str]
) -> list[MavenDependency]:
    collected: list[MavenDependency] = []
    for dep in deps_node.find("dependency"):
        group = dep.text_of("groupId") or ""
        artifact = dep.text_of("artifactId") or ""
        version = _resolve(dep.text_of("version"), properties)
        scope = dep.text_of("scope") or "compile"
        collected.append(
            MavenDependency(
                group_id=group,
                artifact_id=artifact,
                version=version,
                scope=scope,
                location=Located(
                    value=f"{group}:{artifact}",
                    selector=f"dependency[{artifact}]",
                    start_line=dep.start_line,
                    end_line=dep.end_line,
                ),
            )
        )
    return collected


def _collect_plugins(build_node: XmlNode, path: str) -> list[MavenPlugin]:
    plugins: list[MavenPlugin] = []
    for container in ("plugins", "pluginManagement"):
        holder = build_node.first(container)
        if holder is None:
            continue
        plugin_lists = holder.find("plugins") if container == "pluginManagement" else [holder]
        for plugin_list in plugin_lists:
            for plugin in plugin_list.find("plugin"):
                plugins.append(
                    MavenPlugin(
                        group_id=plugin.text_of("groupId") or "",
                        artifact_id=plugin.text_of("artifactId") or "",
                        location=Located(
                            value=(plugin.text_of("artifactId") or ""),
                            selector="plugin",
                            start_line=plugin.start_line,
                            end_line=plugin.end_line,
                        ),
                    )
                )
    return plugins


def _parse_profile(
    profile_node: XmlNode, path: str, parent_properties: dict[str, str]
) -> MavenProfile:
    profile_id = profile_node.text_of("id") or ""
    activation = profile_node.first("activation")
    active_by_default = False
    if activation is not None:
        active_by_default = (activation.text_of("activeByDefault") or "").lower() == "true"

    props: dict[str, str] = {}
    props_node = profile_node.first("properties")
    if props_node is not None:
        for child in props_node.children:
            props[child.tag] = child.text.strip()

    merged = {**parent_properties, **props}
    container_id = _resolve(props.get("cargo.maven.containerId"), merged)

    return MavenProfile(
        id=profile_id,
        active_by_default=active_by_default,
        properties=props,
        container_id=container_id,
        location=Located(
            value=profile_id,
            selector=f"profile[{profile_id}]",
            start_line=profile_node.start_line,
            end_line=profile_node.end_line,
        ),
    )
