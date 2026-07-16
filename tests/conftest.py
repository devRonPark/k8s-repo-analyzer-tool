"""Shared test fixtures. All fixtures are local; no network access is used."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "full-stack-fastapi"


@pytest.fixture
def golden_repo() -> Path:
    assert GOLDEN.is_dir(), "golden fixture must be committed locally"
    return GOLDEN
