from __future__ import annotations

from repo_analyzer.parsers.compose import parse_compose


def test_services_in_file_order(golden_repo):
    cf = parse_compose((golden_repo / "compose.yml").read_text(), "compose.yml")
    assert [s.name for s in cf.services] == ["db", "adminer", "prestart", "backend", "frontend"]


def test_healthcheck_real_line_range(golden_repo):
    cf = parse_compose((golden_repo / "compose.yml").read_text(), "compose.yml")
    backend = next(s for s in cf.services if s.name == "backend")
    assert backend.healthcheck is not None
    # Range is read from the YAML node, never hardcoded in a rule.
    assert backend.healthcheck.start_line == 112
    assert backend.healthcheck.end_line == 116
    assert backend.healthcheck.selector == "$.services.backend.healthcheck"


def test_db_image_and_volume(golden_repo):
    cf = parse_compose((golden_repo / "compose.yml").read_text(), "compose.yml")
    db = next(s for s in cf.services if s.name == "db")
    assert db.image.value == "postgres:18"
    assert db.image.start_line == 4
    assert any(v.value == "app-db-data:/var/lib/postgresql/data/pgdata" for v in db.volumes)


def test_build_and_depends_on(golden_repo):
    cf = parse_compose((golden_repo / "compose.yml").read_text(), "compose.yml")
    backend = next(s for s in cf.services if s.name == "backend")
    assert backend.build_dockerfile.value == "backend/Dockerfile"
    conditions = {d.value["service"]: d.value["condition"] for d in backend.depends_on}
    assert conditions == {"db": "service_healthy", "prestart": "service_completed_successfully"}


def test_frontend_build_args(golden_repo):
    cf = parse_compose((golden_repo / "compose.yml").read_text(), "compose.yml")
    frontend = next(s for s in cf.services if s.name == "frontend")
    values = [a.value for a in frontend.build_args]
    assert any(v.startswith("VITE_API_URL=") for v in values)


def test_non_mapping_service_is_reported():
    cf = parse_compose("services:\n  broken: 123\n", "compose.yml")
    assert any(i.construct == "compose_service" for i in cf.issues)


def test_malformed_yaml_is_reported():
    cf = parse_compose("services: [unclosed\n", "compose.yml")
    assert any(i.construct == "yaml_parse_error" for i in cf.issues)
    assert cf.services == []
