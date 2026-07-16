"""AST-based parser for a pydantic-settings ``BaseSettings`` class.

Extracts declared configuration fields (name, whether a default exists, the
default's source text) with real line ranges from the AST. Used to corroborate
which environment variables the application expects and which are required.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .common import ParseIssue


@dataclass
class SettingField:
    name: str
    has_default: bool
    default_repr: str | None
    start_line: int
    end_line: int


@dataclass
class PythonSettings:
    path: str
    class_name: str | None = None
    fields: list[SettingField] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    def get(self, name: str) -> SettingField | None:
        for item in self.fields:
            if item.name == name:
                return item
        return None


def _base_names(node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def parse_python_settings(text: str, path: str) -> PythonSettings:
    result = PythonSettings(path=path)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:  # pragma: no cover - exercised via bad-input test
        result.issues.append(ParseIssue("python_syntax", str(exc)))
        return result

    target: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and "BaseSettings" in _base_names(node):
            target = node
            break
    if target is None:
        result.issues.append(
            ParseIssue("python_settings", "no BaseSettings subclass found")
        )
        return result

    result.class_name = target.name
    for stmt in target.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            has_default = stmt.value is not None
            default_repr = ast.unparse(stmt.value) if stmt.value is not None else None
            result.fields.append(
                SettingField(
                    name=stmt.target.id,
                    has_default=has_default,
                    default_repr=default_repr,
                    start_line=stmt.lineno,
                    end_line=getattr(stmt, "end_lineno", stmt.lineno) or stmt.lineno,
                )
            )
    return result
