"""Minimal SQL script scanner for schema/data initialization idempotency.

Not a SQL parser: it recognises only the guard clauses that make a schema script
safe to re-run — ``CREATE TABLE IF NOT EXISTS`` and ``DROP TABLE ... IF EXISTS``
— and reports the line of the first such statement as evidence. It answers one
P0 question ("is startup SQL init idempotent?"); nothing more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CREATE_IF_NOT_EXISTS = re.compile(r"\bcreate\s+table\s+if\s+not\s+exists\b", re.IGNORECASE)
_DROP_IF_EXISTS = re.compile(r"\bdrop\s+table\b.*\bif\s+exists\b", re.IGNORECASE)
_CREATE_TABLE = re.compile(r"\bcreate\s+table\b", re.IGNORECASE)


@dataclass
class SqlInitScript:
    path: str
    create_table_lines: list[int] = field(default_factory=list)
    idempotent_create_lines: list[int] = field(default_factory=list)
    drop_if_exists_lines: list[int] = field(default_factory=list)

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
        if _CREATE_IF_NOT_EXISTS.search(raw):
            script.create_table_lines.append(line_no)
            script.idempotent_create_lines.append(line_no)
        elif _CREATE_TABLE.search(raw):
            script.create_table_lines.append(line_no)
        if _DROP_IF_EXISTS.search(raw):
            script.drop_if_exists_lines.append(line_no)
    return script
