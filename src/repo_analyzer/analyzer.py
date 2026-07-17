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
from .parsers.gradle import (
    GradleBuild,
    apply_version_catalog,
    parse_gradle,
    parse_gradle_wrapper,
    parse_settings,
)
from .parsers.maven import MavenProject, parse_maven
from .parsers.nginx import NginxConfig, parse_nginx
from .parsers.python_settings import PythonSettings, parse_python_settings
from .parsers.spring_properties import SpringProperties, parse_spring_properties
from .parsers.spring_yaml import parse_spring_yaml
from .parsers.version_catalog import parse_version_catalog
from .parsers.spring_xml import SpringContext, parse_spring_xml
from .parsers.sql_init import SqlInitScript, parse_sql_init
from .parsers.webxml import WebApp, parse_webxml
from .rules.kubernetes_p0 import analyze_kubernetes_p0

SUPPORTED_PROFILES = {"kubernetes-p0"}
SUPPORTED_BUILD_SYSTEMS = {"auto", "gradle", "maven"}

_SOURCE_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue"}
_ENV_USAGE_DIR_SKIP = {"node_modules", ".git", "dist", "build", ".venv"}


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8", errors="replace")


def analyze_repository(
    repository_path: str,
    profile: str = "kubernetes-p0",
    git_ref: str | None = None,
    build_system: str = "auto",
) -> AnalysisResult:
    """Analyze ``repository_path`` and return a deterministic ``AnalysisResult``.

    ``build_system`` (``auto`` | ``gradle`` | ``maven``) forces which build system
    is analyzed when a repository ships more than one; ``auto`` selects
    deterministically and records the choice.
    """

    if profile not in SUPPORTED_PROFILES:
        raise ValueError(
            f"unsupported profile {profile!r}; supported: {sorted(SUPPORTED_PROFILES)}"
        )
    if build_system not in SUPPORTED_BUILD_SYSTEMS:
        raise ValueError(
            f"unsupported build_system {build_system!r}; supported: {sorted(SUPPORTED_BUILD_SYSTEMS)}"
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

    mavens: dict[str, MavenProject] = {
        rel: parse_maven(_read(root, rel), rel) for rel in inventory.maven_files
    }

    gradles: dict[str, GradleBuild] = {
        rel: parse_gradle(_read(root, rel), rel) for rel in inventory.gradle_files
    }
    if gradles:
        gradle_settings = (
            parse_settings(_read(root, inventory.gradle_settings_files[0]), inventory.gradle_settings_files[0])
            if inventory.gradle_settings_files
            else None
        )
        gradle_wrapper = (
            parse_gradle_wrapper(_read(root, inventory.gradle_wrapper_props[0]), inventory.gradle_wrapper_props[0])
            if inventory.gradle_wrapper_props
            else None
        )
        catalog = (
            parse_version_catalog(
                _read(root, inventory.version_catalog_files[0]), inventory.version_catalog_files[0]
            )
            if inventory.version_catalog_files
            else None
        )
        for build in gradles.values():
            if gradle_settings is not None:
                build.root_project_name, build.root_project_name_location = gradle_settings
            if gradle_wrapper is not None:
                build.wrapper_gradle_version, build.wrapper_location = gradle_wrapper
            if catalog is not None:
                apply_version_catalog(build, catalog)

    spring_props: dict[str, SpringProperties] = {
        rel: parse_spring_properties(_read(root, rel), rel) for rel in inventory.spring_property_files
    }
    # application*.yml/.yaml is parsed into the SAME SpringProperties model so the
    # Spring/Java rules consume both formats identically.
    spring_props.update(
        {rel: parse_spring_yaml(_read(root, rel), rel) for rel in inventory.spring_yaml_files}
    )
    sql_inits: dict[str, SqlInitScript] = {
        rel: parse_sql_init(_read(root, rel), rel) for rel in inventory.sql_init_files
    }

    webapps: dict[str, WebApp] = {
        rel: parse_webxml(_read(root, rel), rel) for rel in inventory.web_descriptors
    }
    springs: dict[str, SpringContext] = {}
    for rel in inventory.spring_xml_files:
        parsed = parse_spring_xml(_read(root, rel), rel)
        if parsed.is_spring:
            springs[rel] = parsed
    readmes: dict[str, list[str]] = {
        rel: _read(root, rel).splitlines() for rel in inventory.readme_files
    }

    build_arg_names = _collect_build_arg_names(compose)
    env_usage = _scan_env_usage(root, build_arg_names)

    return analyze_kubernetes_p0(
        repo_name=root.resolve().name,
        profile=profile,
        git_ref=git_ref,
        build_system=build_system,
        inventory=inventory,
        compose=compose,
        dockerfiles=dockerfiles,
        dotenvs=dotenvs,
        nginx=nginx,
        settings=settings,
        shell_scripts=shell_scripts,
        mavens=mavens,
        gradles=gradles,
        spring_props=spring_props,
        sql_inits=sql_inits,
        webapps=webapps,
        springs=springs,
        readmes=readmes,
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
