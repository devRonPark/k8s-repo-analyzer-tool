"""Shared test fixtures. All fixtures are local; no network access is used."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "full-stack-fastapi"
JPETSTORE = FIXTURES / "jpetstore-6"
SPRING_PETCLINIC = FIXTURES / "spring-petclinic"


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


@pytest.fixture
def spring_petclinic_repo() -> Path:
    """Pinned local copy of the P0-relevant files from spring-projects/
    spring-petclinic @ f182358d02e4a68e52bdbabf55ca7800288511e7 (Spring Boot 4.x,
    Gradle + Maven both present, executable JAR). Wrapper scripts (gradlew/mvnw)
    are presence-only placeholders. No network access; the fixture is committed."""

    assert SPRING_PETCLINIC.is_dir(), "spring-petclinic fixture must be committed locally"
    return SPRING_PETCLINIC
