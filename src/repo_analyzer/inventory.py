"""Repository file discovery.

Finds P0-relevant files by well-known names and patterns (not fixed paths) and
classifies them. Contents are not parsed here; this layer only answers "what
exists and what kind is it", using repo-relative POSIX paths for determinism.
"""

from __future__ import annotations

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
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
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


@dataclass
class Inventory:
    root: Path
    compose_primary: str | None = None
    compose_extra: list[str] = field(default_factory=list)
    dockerfiles: list[str] = field(default_factory=list)
    dotenv_files: list[str] = field(default_factory=list)
    nginx_files: list[str] = field(default_factory=list)
    settings_files: list[str] = field(default_factory=list)
    shell_scripts: list[str] = field(default_factory=list)
    alembic_files: list[str] = field(default_factory=list)
    maven_files: list[str] = field(default_factory=list)
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


def _is_dockerfile(name: str) -> bool:
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")


def _is_dotenv(name: str) -> bool:
    return name == ".env" or name.startswith(".env.")


def _is_nginx(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(".conf") and ("nginx" in lower or lower == "default.conf")


def _is_readme(name: str) -> bool:
    return name.lower().split(".", 1)[0] == "readme"


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
        elif name == "web.xml":
            inv.web_descriptors.append(rel)
        elif name in _BUILD_WRAPPER_NAMES:
            inv.build_wrappers.append(rel)
        elif _is_readme(name):
            inv.readme_files.append(rel)
        if name != "web.xml" and _is_spring_xml_candidate(rel, name):
            inv.spring_xml_files.append(rel)

    inv.compose_primary = _pick_primary_compose(compose_candidates)
    inv.compose_extra = sorted(c for c in compose_candidates if c != inv.compose_primary)

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
        kind = "compose" if rel == inv.compose_primary else "compose-additional"
        detected.append(DetectedFile(path=rel, kind=kind))
    detected += [DetectedFile(path=p, kind="dockerfile") for p in inv.dockerfiles]
    detected += [DetectedFile(path=p, kind="dotenv") for p in inv.dotenv_files]
    detected += [DetectedFile(path=p, kind="nginx") for p in inv.nginx_files]
    detected += [DetectedFile(path=p, kind="python-settings") for p in inv.settings_files]
    detected += [DetectedFile(path=p, kind="shell-init") for p in inv.shell_scripts]
    detected += [DetectedFile(path=p, kind="alembic") for p in inv.alembic_files]
    detected += [DetectedFile(path=p, kind="maven-pom") for p in inv.maven_files]
    detected += [DetectedFile(path=p, kind="web-descriptor") for p in inv.web_descriptors]
    detected += [DetectedFile(path=p, kind="build-wrapper") for p in inv.build_wrappers]
    detected += [DetectedFile(path=p, kind="readme") for p in inv.readme_files]
    return sorted(detected, key=lambda d: d.path)
