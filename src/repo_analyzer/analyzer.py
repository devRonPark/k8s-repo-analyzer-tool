"""Orchestration: read files, run parsers, invoke the kubernetes-p0 rule engine.

This layer performs all filesystem reads (never writes to the analyzed repo) and
hands fully-parsed, line-located facts to the pure rule engine.
"""

from __future__ import annotations

import re
from pathlib import Path

from .inventory import build_inventory
from .models import AnalysisResult
from .parsers.compose import ComposeFile, parse_compose
from .parsers.dockerfile import Dockerfile, parse_dockerfile
from .parsers.dotenv import DotenvFile, parse_dotenv
from .parsers.nginx import NginxConfig, parse_nginx
from .parsers.python_settings import PythonSettings, parse_python_settings
from .rules.kubernetes_p0 import analyze_kubernetes_p0

SUPPORTED_PROFILES = {"kubernetes-p0"}

_SOURCE_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue"}
_ENV_USAGE_DIR_SKIP = {"node_modules", ".git", "dist", "build", ".venv"}


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8", errors="replace")


def analyze_repository(
    repository_path: str,
    profile: str = "kubernetes-p0",
    git_ref: str | None = None,
) -> AnalysisResult:
    """Analyze ``repository_path`` and return a deterministic ``AnalysisResult``."""

    if profile not in SUPPORTED_PROFILES:
        raise ValueError(
            f"unsupported profile {profile!r}; supported: {sorted(SUPPORTED_PROFILES)}"
        )
    root = Path(repository_path)
    if not root.exists():
        raise FileNotFoundError(f"repository path does not exist: {repository_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"repository path is not a directory: {repository_path}")

    inventory = build_inventory(root)

    compose: ComposeFile | None = None
    if inventory.compose_primary is not None:
        compose = parse_compose(_read(root, inventory.compose_primary), inventory.compose_primary)

    dockerfiles: dict[str, Dockerfile] = {
        rel: parse_dockerfile(_read(root, rel), rel) for rel in inventory.dockerfiles
    }
    dotenvs: dict[str, DotenvFile] = {
        rel: parse_dotenv(_read(root, rel), rel) for rel in inventory.dotenv_files
    }
    nginx: dict[str, NginxConfig] = {
        rel: parse_nginx(_read(root, rel), rel) for rel in inventory.nginx_files
    }
    settings: dict[str, PythonSettings] = {}
    for rel in inventory.settings_files:
        parsed = parse_python_settings(_read(root, rel), rel)
        if parsed.class_name is not None:
            settings[rel] = parsed

    shell_scripts: dict[str, list[str]] = {
        rel: _read(root, rel).splitlines() for rel in inventory.shell_scripts
    }

    build_arg_names = _collect_build_arg_names(compose)
    env_usage = _scan_env_usage(root, build_arg_names)

    return analyze_kubernetes_p0(
        repo_name=root.resolve().name,
        profile=profile,
        git_ref=git_ref,
        inventory=inventory,
        compose=compose,
        dockerfiles=dockerfiles,
        dotenvs=dotenvs,
        nginx=nginx,
        settings=settings,
        shell_scripts=shell_scripts,
        env_usage=env_usage,
    )


def _collect_build_arg_names(compose: ComposeFile | None) -> list[str]:
    if compose is None:
        return []
    names: list[str] = []
    for service in compose.services:
        for arg in service.build_args:
            name = str(arg.value).split("=", 1)[0].strip()
            if (name.startswith("VITE_") or "API_URL" in name.upper()) and name not in names:
                names.append(name)
    return names


def _scan_env_usage(root: Path, names: list[str]) -> dict[str, list[tuple[str, int]]]:
    """Find where build-time env vars are referenced in frontend source code."""

    usage: dict[str, list[tuple[str, int]]] = {name: [] for name in names}
    if not names:
        return usage
    patterns = {
        name: re.compile(r"(?:import\.meta\.env|process\.env)\." + re.escape(name) + r"\b")
        for name in names
    }
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _SOURCE_EXTS:
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in _ENV_USAGE_DIR_SKIP for part in rel_parts):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for offset, line in enumerate(text.splitlines()):
            for name, pattern in patterns.items():
                if pattern.search(line):
                    usage[name].append((rel, offset + 1))
    for name in usage:
        usage[name] = sorted(set(usage[name]))
    return usage
