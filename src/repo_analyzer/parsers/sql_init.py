"""Minimal SQL script scanner for schema/data initialization P0 facts.

Not a SQL parser: it recognises only the small set of schema facts needed for a
Kubernetes migration overview:

* table names from ``CREATE TABLE`` statements, so the report can say what
  database data exists without reading application code;
* guard clauses that make a schema script safe to re-run —
  ``CREATE TABLE IF NOT EXISTS`` and ``DROP TABLE ... IF EXISTS``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .common import Located

SqlScriptKind = Literal["schema", "data", "mixed", "unknown"]

_CREATE_IF_NOT_EXISTS = re.compile(r"\bcreate\s+table\s+if\s+not\s+exists\b", re.IGNORECASE)
_DROP_IF_EXISTS = re.compile(r"\bdrop\s+table\b.*\bif\s+exists\b", re.IGNORECASE)
_CREATE_TABLE = re.compile(r"\bcreate\s+table\b", re.IGNORECASE)
_CREATE_TABLE_NAME = re.compile(
    r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?"
    r"(?P<name>(?:[`\"\[]?[\w$]+[`\"\]]?\.)?[`\"\[]?[\w$]+[`\"\]]?)",
    re.IGNORECASE,
)
_INSERT_TABLE_NAME = re.compile(
    r"\binsert\s+into\s+(?P<name>(?:[`\"\[]?[\w$]+[`\"\]]?\.)?[`\"\[]?[\w$]+[`\"\]]?)",
    re.IGNORECASE,
)


@dataclass
class SqlInitScript:
    path: str
    create_table_lines: list[int] = field(default_factory=list)
    idempotent_create_lines: list[int] = field(default_factory=list)
    drop_if_exists_lines: list[int] = field(default_factory=list)
    table_names: list[Located] = field(default_factory=list)
    insert_table_names: list[Located] = field(default_factory=list)

    @property
    def script_kind(self) -> SqlScriptKind:
        has_schema = bool(self.table_names)
        has_data = bool(self.insert_table_names)
        if has_schema and has_data:
            return "mixed"
        if has_schema:
            return "schema"
        if has_data:
            return "data"
        return "unknown"

    @property
    def has_create_tables(self) -> bool:
        return bool(self.create_table_lines)

    @property
    def is_idempotent(self) -> bool:
        """A script re-runs cleanly when every CREATE TABLE is guarded by
        ``IF NOT EXISTS``, or when tables are dropped with ``DROP TABLE ... IF
        EXISTS`` before being recreated (the H2 pattern)."""

        if not self.create_table_lines:
            return False
        if set(self.create_table_lines) == set(self.idempotent_create_lines):
            return True
        return bool(self.drop_if_exists_lines)

    @property
    def idempotency_marker_line(self) -> int | None:
        if self.idempotent_create_lines:
            return self.idempotent_create_lines[0]
        if self.drop_if_exists_lines:
            return self.drop_if_exists_lines[0]
        return None


def parse_sql_init(text: str, path: str) -> SqlInitScript:
    script = SqlInitScript(path=path)
    for index, raw in enumerate(text.splitlines()):
        line_no = index + 1
        table_match = _CREATE_TABLE_NAME.search(raw)
        if table_match:
            name = _normalise_table_name(table_match.group("name"))
            if name:
                script.table_names.append(
                    Located(value=name, selector=f"CREATE TABLE {name}", start_line=line_no, end_line=line_no)
                )
        insert_match = _INSERT_TABLE_NAME.search(raw)
        if insert_match:
            name = _normalise_table_name(insert_match.group("name"))
            if name:
                script.insert_table_names.append(
                    Located(value=name, selector=f"INSERT INTO {name}", start_line=line_no, end_line=line_no)
                )
        if _CREATE_IF_NOT_EXISTS.search(raw):
            script.create_table_lines.append(line_no)
            script.idempotent_create_lines.append(line_no)
        elif _CREATE_TABLE.search(raw):
            script.create_table_lines.append(line_no)
        if _DROP_IF_EXISTS.search(raw):
            script.drop_if_exists_lines.append(line_no)
    return script


def _normalise_table_name(raw: str) -> str:
    name = raw.strip().rstrip("(")
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    return name.strip("`\"[]")
