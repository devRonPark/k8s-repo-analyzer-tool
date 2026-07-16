"""Deterministic JSON reporter.

Key order is intrinsic (from the Pydantic field declaration order); lists are
already ordered by the rule engine. Output is UTF-8, 2-space indented, and
byte-stable for identical input.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import AnalysisResult


def to_json(result: AnalysisResult) -> str:
    data = result.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def write_json(result: AnalysisResult, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_json(result), encoding="utf-8")
