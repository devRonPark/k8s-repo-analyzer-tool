"""Minimal, dependency-free ``.env`` parser.

Records each variable's name, default value, whether the value is empty, and the
source line. Quoting and ``export`` prefixes are handled; malformed lines are
reported as issues rather than dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import ParseIssue


@dataclass
class DotenvEntry:
    name: str
    value: str
    is_empty: bool
    line: int


@dataclass
class DotenvFile:
    path: str
    entries: list[DotenvEntry] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    def get(self, name: str) -> DotenvEntry | None:
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_dotenv(text: str, path: str) -> DotenvFile:
    result = DotenvFile(path=path)
    for offset, raw in enumerate(text.splitlines()):
        line_no = offset + 1
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            result.issues.append(
                ParseIssue("dotenv_line", f"line {line_no}: no '=' in {raw!r}")
            )
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        value = _strip_quotes(value.strip())
        if not name:
            result.issues.append(ParseIssue("dotenv_line", f"line {line_no}: empty key"))
            continue
        result.entries.append(
            DotenvEntry(name=name, value=value, is_empty=value == "", line=line_no)
        )
    return result
