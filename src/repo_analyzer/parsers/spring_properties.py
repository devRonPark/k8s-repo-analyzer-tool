"""Spring Boot ``application*.properties`` parser with source-line tracking.

Reads a ``.properties`` file into ordered key/value entries, records the profile
implied by the file name (``application-<profile>.properties``), and extracts
``${ENV_VAR:default}`` placeholders so datasource URLs and credentials can be
mapped to ConfigMap/Secret candidates. Values are reported verbatim; nothing here
decides Kubernetes effects.

Only the ``.properties`` format is parsed structurally. A YAML config
(``application.yml``/``.yaml``) is not silently ignored: the caller records an
``unsupported_construct`` so the gap is visible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .common import ParseIssue

# ${NAME}  or  ${NAME:default}  (default may be empty or contain colons/slashes).
_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.]*)(?::([^}]*))?\}")


@dataclass
class EnvPlaceholder:
    name: str
    default: str | None


@dataclass
class SpringProperty:
    key: str
    value: str
    line: int
    placeholders: list[EnvPlaceholder] = field(default_factory=list)


@dataclass
class SpringProperties:
    path: str
    profile: str | None
    entries: list[SpringProperty] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    def get(self, key: str) -> SpringProperty | None:
        for entry in self.entries:
            if entry.key == key:
                return entry
        return None

    def get_all(self, key: str) -> list[SpringProperty]:
        return [entry for entry in self.entries if entry.key == key]


def profile_from_filename(path: str) -> str | None:
    """``application-mysql.properties`` -> ``mysql``; ``application.properties`` -> None."""

    name = path.rsplit("/", 1)[-1]
    match = re.fullmatch(r"application-([\w.-]+)\.properties", name)
    return match.group(1) if match else None


def _placeholders(value: str) -> list[EnvPlaceholder]:
    return [
        EnvPlaceholder(name=m.group(1), default=m.group(2))
        for m in _PLACEHOLDER_RE.finditer(value)
    ]


def parse_spring_properties(text: str, path: str) -> SpringProperties:
    result = SpringProperties(path=path, profile=profile_from_filename(path))
    for index, raw in enumerate(text.splitlines()):
        line_no = index + 1
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        if stripped.endswith("\\"):
            result.issues.append(
                ParseIssue(
                    "properties_line_continuation",
                    f"line continuation not modelled at line {line_no}",
                )
            )
        # Keys are separated from values by '=' or ':' (first occurrence wins).
        eq = stripped.find("=")
        colon = stripped.find(":")
        candidates = [pos for pos in (eq, colon) if pos != -1]
        if not candidates:
            result.issues.append(
                ParseIssue("properties_no_separator", f"no key/value separator at line {line_no}")
            )
            continue
        sep = min(candidates)
        key = stripped[:sep].strip()
        value = stripped[sep + 1 :].strip()
        if not key:
            continue
        result.entries.append(
            SpringProperty(
                key=key,
                value=value,
                line=line_no,
                placeholders=_placeholders(value),
            )
        )
    return result
