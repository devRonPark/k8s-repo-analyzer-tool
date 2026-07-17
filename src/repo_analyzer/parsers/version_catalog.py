"""Gradle version catalog (``libs.versions.toml``) parser.

Resolves the ``libs.…`` accessors used in build scripts to real Maven
coordinates / plugin ids, using the stdlib TOML reader (``tomllib``, Python
3.11+). Catalog alias keys are kebab-case; a build-script accessor
``libs.spring.starter.webflux`` maps to the ``[libraries]`` key
``spring-starter-webflux`` (``.`` <-> ``-``), and ``libs.plugins.spring.boot``
maps to the ``[plugins]`` key ``spring-boot``.

A malformed catalog is not silently ignored — a ``toml_parse_error`` issue is
recorded so the gap is visible.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field

from .common import ParseIssue


@dataclass
class VersionCatalog:
    path: str
    versions: dict[str, str] = field(default_factory=dict)
    libraries: dict[str, str] = field(default_factory=dict)  # alias key -> "group:artifact"
    _library_versions: dict[str, str | None] = field(default_factory=dict)
    plugins: dict[str, str] = field(default_factory=dict)  # alias key -> plugin id
    issues: list[ParseIssue] = field(default_factory=list)

    def library(self, accessor: str) -> str | None:
        return self.libraries.get(_accessor_key(accessor, "libs."))

    def library_version(self, accessor: str) -> str | None:
        return self._library_versions.get(_accessor_key(accessor, "libs."))

    def plugin(self, accessor: str) -> str | None:
        return self.plugins.get(_accessor_key(accessor, "libs.plugins."))


def _accessor_key(accessor: str, prefix: str) -> str:
    """``libs.spring.starter.webflux`` -> ``spring-starter-webflux``."""

    if accessor.startswith(prefix):
        accessor = accessor[len(prefix) :]
    return accessor.replace(".", "-")


def _spec_version(spec: dict, versions: dict[str, str]) -> str | None:
    value = spec.get("version")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        ref = value.get("ref")
        if isinstance(ref, str):
            return versions.get(ref)
    return None


def _library_module(spec: object, versions: dict[str, str]) -> tuple[str | None, str | None]:
    if isinstance(spec, str):
        parts = spec.split(":")
        if len(parts) >= 2:
            return f"{parts[0]}:{parts[1]}", (parts[2] if len(parts) > 2 else None)
        return None, None
    if isinstance(spec, dict):
        module = spec.get("module")
        if isinstance(module, str) and ":" in module:
            group, _, artifact = module.partition(":")
            return f"{group}:{artifact}", _spec_version(spec, versions)
        group = spec.get("group")
        name = spec.get("name")
        if isinstance(group, str) and isinstance(name, str):
            return f"{group}:{name}", _spec_version(spec, versions)
    return None, None


def _plugin_id(spec: object) -> str | None:
    if isinstance(spec, str):
        return spec.split(":")[0] or None
    if isinstance(spec, dict):
        pid = spec.get("id")
        if isinstance(pid, str):
            return pid
    return None


def parse_version_catalog(text: str, path: str) -> VersionCatalog:
    catalog = VersionCatalog(path=path)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        catalog.issues.append(ParseIssue("toml_parse_error", str(exc)))
        return catalog

    versions = data.get("versions", {})
    if isinstance(versions, dict):
        for key, value in versions.items():
            if isinstance(value, str):
                catalog.versions[key] = value

    libraries = data.get("libraries", {})
    if isinstance(libraries, dict):
        for alias, spec in libraries.items():
            module, version = _library_module(spec, catalog.versions)
            if module is not None:
                catalog.libraries[alias] = module
                catalog._library_versions[alias] = version
            else:
                catalog.issues.append(
                    ParseIssue("version_catalog_library", f"unparseable library alias '{alias}'")
                )

    plugins = data.get("plugins", {})
    if isinstance(plugins, dict):
        for alias, spec in plugins.items():
            pid = _plugin_id(spec)
            if pid is not None:
                catalog.plugins[alias] = pid
            else:
                catalog.issues.append(
                    ParseIssue("version_catalog_plugin", f"unparseable plugin alias '{alias}'")
                )

    return catalog
