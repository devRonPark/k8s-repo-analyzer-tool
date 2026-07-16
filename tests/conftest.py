"""Shared test fixtures. All fixtures are local; no network access is used."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "full-stack-fastapi"
JPETSTORE = FIXTURES / "jpetstore-6"


@pytest.fixture
def golden_repo() -> Path:
    assert GOLDEN.is_dir(), "golden fixture must be committed locally"
    return GOLDEN


@pytest.fixture
def jpetstore_repo() -> Path:
    """Pinned local copy of the P0-relevant files from mybatis/jpetstore-6 @
    5a7cc780505b88a60779b3e3c0a50b0e404cfb2d (Maven WAR, external servlet
    container). No network access; the fixture is committed."""

    assert JPETSTORE.is_dir(), "jpetstore fixture must be committed locally"
    return JPETSTORE
