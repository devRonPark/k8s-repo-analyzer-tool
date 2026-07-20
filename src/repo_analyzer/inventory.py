"""Repository file discovery.

Finds P0-relevant files by well-known names and patterns (not fixed paths) and
classifies them. Contents are not parsed here; this layer only answers "what
exists and what kind is it", using repo-relative POSIX paths for determinism.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import DetectedFile

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    ".devcontainer",
    "htmlcov",
    "coverage",
}

_COMPOSE_PRIMARY_ORDER = [
    "compose.yml",
    "compose.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
]

_SHELL_INIT_NAMES = {"prestart.sh", "entrypoint.sh", "start.sh", "run.sh", "docker-entrypoint.sh"}
_SETTINGS_NAMES = {"config.py", "settings.py"}
_BUILD_WRAPPER_NAMES = {"mvnw", "mvnw.cmd", "gradlew", "gradlew.bat"}
MAX_CANDIDATE_BYTES = 10 * 1024 * 1024

_K8S_KIND_RE = re.compile(r"(?m)^\s*kind\s*:\s*[\"']?(?P<kind>[A-Za-z][A-Za-z0-9]*)[\"']?\s*$")
_K8S_KINDS = {
    "Deployment",
    "StatefulSet",
    "DaemonSet",
    "Service",
    "Ingress",
    "ConfigMap",
    "Secret",
    "Job",
    "CronJob",
    "PersistentVolumeClaim",
}


@dataclass
class Inventory:
    root: Path
    compose_primary: str | None = None
    compose_extra: list[str] = field(default_factory=list)
    compose_ignored: list[str] = field(default_factory=list)
    dockerfiles: list[str] = field(default_factory=list)
    dotenv_files: list[str] = field(default_factory=list)
    nginx_files: list[str] = field(default_factory=list)
    settings_files: list[str] = field(default_factory=list)
    shell_scripts: list[str] = field(default_factory=list)
    alembic_files: list[str] = field(default_factory=list)
    maven_files: list[str] = field(default_factory=list)
    gradle_files: list[str] = field(default_factory=list)
    gradle_settings_files: list[str] = field(default_factory=list)
    gradle_wrapper_props: list[str] = field(default_factory=list)
    version_catalog_files: list[str] = field(default_factory=list)
    spring_property_files: list[str] = field(default_factory=list)
    spring_yaml_files: list[str] = field(default_factory=list)
    sql_init_files: list[str] = field(default_factory=list)
    kubernetes_yaml_files: list[str] = field(default_factory=list)
    skipped_large_candidates: list[str] = field(default_factory=list)
    web_descriptors: list[str] = field(default_factory=list)
    spring_xml_files: list[str] = field(default_factory=list)
    readme_files: list[str] = field(default_factory=list)
    build_wrappers: list[str] = field(default_factory=list)
    detected: list[DetectedFile] = field(default_factory=list)


def _is_compose(name: str) -> bool:
    lower = name.lower()
    return (lower.startswith("compose") or lower.startswith("docker-compose")) and lower.endswith(
        (".yml", ".yaml")
    )


# Directory names that mark a compose file as a demo/sample/test rather than the
# repository's deployment topology (kafka-ui ships its only compose under
# `documentation/`). Matched as exact path segments, not substrings.
_NON_DEPLOYMENT_DIRS = {
    "documentation",
    "docs",
    "doc",
    "example",
    "examples",
    "sample",
    "samples",
    "demo",
    "demos",
    "e2e",
    "testing",
    "test",
    "tests",
    "contrib",
}


def is_non_deployment_path(rel: str) -> bool:
    """True if a file lives under a documentation/examples/demo/test path — a
    sample/demo, not part of the deployable application."""

    dirs = rel.split("/")[:-1]
    return any(part.lower() in _NON_DEPLOYMENT_DIRS for part in dirs)


def _is_nondeployment_compose(rel: str) -> bool:
    return is_non_deployment_path(rel)


def _is_dockerfile(name: str) -> bool:
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")


def _is_dotenv(name: str) -> bool:
    return name == ".env" or name.startswith(".env.")


def _is_nginx(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(".conf") and ("nginx" in lower or lower == "default.conf")


def _is_readme(name: str) -> bool:
    return name.lower().split(".", 1)[0] == "readme"


def _is_gradle_build(name: str) -> bool:
    return name in ("build.gradle", "build.gradle.kts")


def _is_gradle_settings(name: str) -> bool:
    return name in ("settings.gradle", "settings.gradle.kts")


def _is_spring_properties(name: str) -> bool:
    return name == "application.properties" or (
        name.startswith("application-") and name.endswith(".properties")
    )


def _is_spring_yaml(name: str) -> bool:
    return name in ("application.yml", "application.yaml") or (
        name.startswith("application-") and name.endswith((".yml", ".yaml"))
    )


def _is_sql_candidate(name: str) -> bool:
    return name.lower().endswith(".sql")


def _too_large_for_candidate_parse(path: Path) -> bool:
    try:
        return path.stat().st_size > MAX_CANDIDATE_BYTES
    except OSError:
        return False


def _looks_like_kubernetes_yaml(path: Path) -> bool:
    if path.suffix.lower() not in {".yml", ".yaml"}:
        return False
    if _too_large_for_candidate_parse(path):
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if "apiVersion:" not in text or "kind:" not in text:
        return False
    return any(match.group("kind") in _K8S_KINDS for match in _K8S_KIND_RE.finditer(text))


_SPRING_XML_NAME_HINTS = ("applicationcontext", "spring")


def _is_spring_xml_candidate(rel: str, name: str) -> bool:
    """Cheap name/location heuristic; the parser confirms it is truly Spring."""

    lower = name.lower()
    if not lower.endswith(".xml") or lower == "web.xml":
        return False
    if "/WEB-INF/" in f"/{rel}" or rel == "WEB-INF" or "WEB-INF" in rel.split("/"):
        return True
    if lower in {"applicationcontext.xml", "beans.xml"} or lower.endswith("-context.xml"):
        return True
    return any(lower.startswith(hint) for hint in _SPRING_XML_NAME_HINTS)


def build_inventory(root: Path) -> Inventory:
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"repository path is not a directory: {root}")

    inv = Inventory(root=root)
    compose_candidates: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        rel = path.relative_to(root).as_posix()
        name = path.name
        if _is_compose(name):
            compose_candidates.append(rel)
        elif _is_dockerfile(name):
            inv.dockerfiles.append(rel)
        elif _is_dotenv(name):
            inv.dotenv_files.append(rel)
        elif _is_nginx(name):
            inv.nginx_files.append(rel)
        elif name in _SETTINGS_NAMES:
            inv.settings_files.append(rel)
        elif name in _SHELL_INIT_NAMES:
            inv.shell_scripts.append(rel)
        elif name == "alembic.ini":
            inv.alembic_files.append(rel)
        elif name == "pom.xml":
            inv.maven_files.append(rel)
        elif _is_gradle_build(name):
            inv.gradle_files.append(rel)
        elif _is_gradle_settings(name):
            inv.gradle_settings_files.append(rel)
        elif name == "gradle-wrapper.properties":
            inv.gradle_wrapper_props.append(rel)
        elif name == "libs.versions.toml":
            inv.version_catalog_files.append(rel)
        elif _is_spring_properties(name):
            inv.spring_property_files.append(rel)
        elif _is_spring_yaml(name):
            inv.spring_yaml_files.append(rel)
        elif _is_sql_candidate(name):
            if _too_large_for_candidate_parse(path):
                inv.skipped_large_candidates.append(rel)
            else:
                inv.sql_init_files.append(rel)
        elif name == "web.xml":
            inv.web_descriptors.append(rel)
        elif name in _BUILD_WRAPPER_NAMES:
            inv.build_wrappers.append(rel)
        elif _is_readme(name):
            inv.readme_files.append(rel)
        if name != "web.xml" and _is_spring_xml_candidate(rel, name):
            inv.spring_xml_files.append(rel)
        if path.suffix.lower() in {".yml", ".yaml"}:
            if _too_large_for_candidate_parse(path):
                if rel not in inv.skipped_large_candidates:
                    inv.skipped_large_candidates.append(rel)
            elif _looks_like_kubernetes_yaml(path):
                inv.kubernetes_yaml_files.append(rel)

    deployment_composes = [c for c in compose_candidates if not _is_nondeployment_compose(c)]
    inv.compose_ignored = sorted(c for c in compose_candidates if _is_nondeployment_compose(c))
    inv.compose_primary = _pick_primary_compose(deployment_composes)
    inv.compose_extra = sorted(c for c in deployment_composes if c != inv.compose_primary)

    inv.detected = _build_detected(inv, compose_candidates)
    return inv


def _pick_primary_compose(candidates: list[str]) -> str | None:
    by_name = {Path(c).name: c for c in candidates if "/" not in c}
    for preferred in _COMPOSE_PRIMARY_ORDER:
        if preferred in by_name and "override" not in preferred:
            return by_name[preferred]
    # Fall back to the shortest-path, non-override candidate for stability.
    non_override = sorted(c for c in candidates if "override" not in Path(c).name)
    return non_override[0] if non_override else (sorted(candidates)[0] if candidates else None)


def _build_detected(inv: Inventory, compose_candidates: list[str]) -> list[DetectedFile]:
    detected: list[DetectedFile] = []
    for rel in compose_candidates:
        if rel == inv.compose_primary:
            kind = "compose"
        elif rel in inv.compose_ignored:
            kind = "compose-ignored"
        else:
            kind = "compose-additional"
        detected.append(DetectedFile(path=rel, kind=kind))
    detected += [DetectedFile(path=p, kind="dockerfile") for p in inv.dockerfiles]
    detected += [DetectedFile(path=p, kind="dotenv") for p in inv.dotenv_files]
    detected += [DetectedFile(path=p, kind="nginx") for p in inv.nginx_files]
    detected += [DetectedFile(path=p, kind="python-settings") for p in inv.settings_files]
    detected += [DetectedFile(path=p, kind="shell-init") for p in inv.shell_scripts]
    detected += [DetectedFile(path=p, kind="alembic") for p in inv.alembic_files]
    detected += [DetectedFile(path=p, kind="maven-pom") for p in inv.maven_files]
    detected += [DetectedFile(path=p, kind="gradle-build") for p in inv.gradle_files]
    detected += [DetectedFile(path=p, kind="gradle-settings") for p in inv.gradle_settings_files]
    detected += [DetectedFile(path=p, kind="gradle-wrapper") for p in inv.gradle_wrapper_props]
    detected += [DetectedFile(path=p, kind="version-catalog") for p in inv.version_catalog_files]
    detected += [DetectedFile(path=p, kind="spring-properties") for p in inv.spring_property_files]
    detected += [DetectedFile(path=p, kind="spring-yaml") for p in inv.spring_yaml_files]
    detected += [DetectedFile(path=p, kind="sql-candidate") for p in inv.sql_init_files]
    detected += [
        DetectedFile(path=p, kind="kubernetes-yaml-candidate")
        for p in inv.kubernetes_yaml_files
    ]
    detected += [
        DetectedFile(path=p, kind="candidate-skipped-large")
        for p in inv.skipped_large_candidates
    ]
    detected += [DetectedFile(path=p, kind="web-descriptor") for p in inv.web_descriptors]
    detected += [DetectedFile(path=p, kind="build-wrapper") for p in inv.build_wrappers]
    detected += [DetectedFile(path=p, kind="readme") for p in inv.readme_files]
    return sorted(detected, key=lambda d: d.path)
