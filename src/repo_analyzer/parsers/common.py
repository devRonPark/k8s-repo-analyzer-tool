"""Shared parser primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Located:
    """A parsed value paired with its 1-based source line range and selector."""

    value: Any
    selector: str
    start_line: int
    end_line: int


@dataclass
class ParseIssue:
    """A construct the parser recognised but could not fully handle."""

    construct: str
    detail: str


@dataclass
class ParseResult:
    """Common envelope: every parser reports issues instead of silent skips."""

    issues: list[ParseIssue] = field(default_factory=list)
