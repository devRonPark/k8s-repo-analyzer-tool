from __future__ import annotations

import pytest

from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.models import AnalysisResult


@pytest.fixture
def result(golden_repo) -> AnalysisResult:
    return analyze_repository(str(golden_repo), git_ref="4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8")


def _component(result: AnalysisResult, name: str):
    return next(c for c in result.components if c.name == name)


def test_components(result):
    assert [c.name for c in result.components] == [
        "db",
        "adminer",
        "prestart",
        "backend",
        "frontend",
    ]


def test_database(result):
    db = _component(result, "db")
    assert db.image == "postgres:18"
    assert db.container_ports == [5432]
    storage = [f for f in result.storage if f.subject == "db.persistent_volume"]
    assert storage, "db must have a persistent volume finding"
    assert storage[0].value == {
        "volume": "app-db-data",
        "mount_path": "/var/lib/postgresql/data/pgdata",
    }


def test_backend(result):
    backend = _component(result, "backend")
    assert backend.container_ports == [8000]
    assert backend.dockerfile == "backend/Dockerfile"
    assert backend.workers == 4
    assert backend.command[:2] == ["fastapi", "run"]
    health = [f for f in result.health_checks if f.subject == "backend.health_path"]
    assert health and health[0].value == "/api/v1/utils/health-check/"


def test_frontend(result):
    frontend = _component(result, "frontend")
    assert frontend.dockerfile == "frontend/Dockerfile"
    assert frontend.runtime == "Nginx (static assets)"
    assert frontend.container_ports == [80]
    build_time = [
        f for f in result.build_time_constraints if f.subject == "frontend.vite_api_url_binding"
    ]
    assert build_time and build_time[0].value == "build-time"
    assert build_time[0].confidence == "derived"


def test_build_time_constraint_links_all_evidence(result):
    f = next(
        f for f in result.build_time_constraints if f.subject == "frontend.vite_api_url_binding"
    )
    paths = {e.path for e in f.evidence}
    # derived from compose build arg + Dockerfile ARG + frontend source usage
    assert "compose.yml" in paths
    assert "frontend/Dockerfile" in paths
    assert any(p.endswith("main.tsx") for p in paths)


def test_startup_order(result):
    order = next(f for f in result.startup_order if f.subject == "startup.order")
    assert order.value == [
        "database becomes ready",
        "run DB migrations",
        "create initial data",
        "backend starts",
    ]
    assert order.confidence == "derived"


def test_startup_steps_have_evidence(result):
    migration = [f for f in result.startup_order if f.subject == "startup.migration"]
    assert migration and migration[0].evidence[0].path.endswith("prestart.sh")


def test_workload_mappings(result):
    mapping = {w.component: w.kubernetes_kind for w in result.workload_mappings}
    assert "StatefulSet" in mapping["db"] or "external" in mapping["db"]
    assert mapping["prestart"].startswith("Job")
    assert "Deployment" in mapping["backend"] and "Service" in mapping["backend"]
    assert "Deployment" in mapping["frontend"] and "Service" in mapping["frontend"]
    assert "optional" in mapping["adminer"].lower()


def test_legacy_component_fields_remain_populated(result):
    backend = next(component for component in result.components if component.name == "backend")
    assert backend.dockerfile == "backend/Dockerfile"
    assert backend.container_ports == [8000]
    assert backend.workload_candidate

    mapping = next(mapping for mapping in result.workload_mappings if mapping.component == "backend")
    assert "Deployment" in mapping.kubernetes_kind


def test_secrets_detected(result):
    subjects = {f.subject for f in result.secrets}
    assert "secret.SECRET_KEY" in subjects
    assert "secret.POSTGRES_PASSWORD" in subjects
    assert "secret.FIRST_SUPERUSER_PASSWORD" in subjects


def test_config_map_candidates(result):
    subjects = {f.subject for f in result.configuration}
    assert "config.POSTGRES_SERVER" in subjects
    # A secret must never appear as a plain config key.
    assert "config.SECRET_KEY" not in subjects


def test_evidence_uses_real_line_numbers(result):
    health = next(f for f in result.health_checks if f.subject == "backend.health_path")
    ev = health.evidence[0]
    assert ev.path == "compose.yml"
    assert ev.start_line == 112 and ev.end_line == 116


def test_no_absolute_paths_anywhere(result):
    for finding in (
        result.networking
        + result.configuration
        + result.secrets
        + result.storage
        + result.health_checks
        + result.build_time_constraints
        + result.startup_order
    ):
        for ev in finding.evidence:
            assert not ev.path.startswith("/"), ev.path
    for df in result.detected_files:
        assert not df.path.startswith("/")


def test_unresolved_operational_inputs(result):
    subjects = {u.subject for u in result.unresolved_operational_inputs}
    assert {"replica_count", "resource_requests_limits", "pvc_size", "storage_class"} <= subjects
    assert all(u.no_default_used for u in result.unresolved_operational_inputs)


def test_override_warning_present(result):
    codes = {(w.code, w.path) for w in result.warnings}
    assert ("compose_override_not_merged", "compose.override.yml") in codes
