"""P0-2: component discovery when there is no *deployment* compose file.

Two behaviours:
1. A compose file under a documentation/examples/demo/test path is a
   sample/demo, NOT the deployment topology — it must not be selected as the
   primary compose, and its services must not become workloads.
2. A repo with no compose and no Java build system, but with a Dockerfile, must
   still yield a component synthesized from that Dockerfile (image/port/config).
"""

from __future__ import annotations

from pathlib import Path

from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.inventory import build_inventory

_PY_DOCKERFILE = """\
FROM python:3.11-slim AS base
WORKDIR /app
COPY . .

FROM base AS migrate
CMD ["alembic", "upgrade", "head"]

FROM base AS prod
RUN groupadd -r appuser && useradd -r -g appuser appuser
USER appuser
CMD ["sh", "-c", "fastapi run main.py --host 0.0.0.0 --port 8000 --workers $WORKERS"]
"""

_ENV = """\
ENVIRONMENT=production
POSTGRES_PASSWORD=changeme
SECRET_KEY=insecure-change-me
"""

_DEMO_COMPOSE = """\
services:
  postgres:
    image: postgres:16
    ports:
      - "5432:5432"
  kafka:
    image: confluentinc/cp-kafka:7.8.0
    ports:
      - "9092:9092"
"""


# --- inventory-level: non-deployment compose is not the topology -------------
def test_inventory_ignores_documentation_compose(tmp_path):
    doc = tmp_path / "documentation" / "compose"
    doc.mkdir(parents=True)
    (doc / "docker-compose.yaml").write_text(_DEMO_COMPOSE)
    (tmp_path / "Dockerfile").write_text(_PY_DOCKERFILE)

    inv = build_inventory(tmp_path)
    assert inv.compose_primary is None
    assert inv.compose_ignored == ["documentation/compose/docker-compose.yaml"]


def test_inventory_keeps_root_deployment_compose(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(_DEMO_COMPOSE)
    inv = build_inventory(tmp_path)
    assert inv.compose_primary == "docker-compose.yml"
    assert inv.compose_ignored == []


# --- integration: demo compose ignored + Dockerfile component synthesized ----
def test_demo_compose_ignored_and_dockerfile_component(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "Dockerfile").write_text(_PY_DOCKERFILE)
    (backend / ".env.example").write_text(_ENV)
    (backend / "alembic.ini").write_text("[alembic]\nscript_location = migrations\n")
    # A demo compose under documentation/ must NOT drive the topology.
    demo = tmp_path / "documentation"
    demo.mkdir()
    (demo / "docker-compose.yaml").write_text(_DEMO_COMPOSE)

    result = analyze_repository(str(tmp_path))

    # The demo compose's services must not become components.
    names = {c.name for c in result.components}
    assert "postgres" not in names and "kafka" not in names
    assert any(w.code == "compose_non_deployment_path" for w in result.warnings)
    assert not any(w.code == "no_compose" for w in result.warnings)

    # Exactly one component, synthesized from the Dockerfile.
    assert len(result.components) == 1
    comp = result.components[0]
    assert comp.name == "backend"
    assert comp.dockerfile == "backend/Dockerfile"
    assert comp.runtime == "FastAPI"
    assert comp.container_ports == [8000]
    # Config/secrets from the dotenv.
    assert any(s.subject == "secret.POSTGRES_PASSWORD" for s in result.secrets)
    assert any(s.subject == "secret.SECRET_KEY" for s in result.secrets)
    assert any(c.subject == "config.ENVIRONMENT" for c in result.configuration)
    # Alembic migration surfaced as a separate init step.
    assert any("migration" in f.subject for f in result.startup_order)
    # Non-root user surfaced from the Dockerfile.
    assert any("non_root" in f.subject or "non-root" in str(f.value).lower() for f in result.container_image)
    # Workload mapping: one stateless Deployment.
    assert len(result.workload_mappings) == 1
    assert "Deployment" in result.workload_mappings[0].kubernetes_kind


_WORKER_COMPOSE = """\
services:
  backend:
    build:
      context: ./backend
    ports:
      - "8000:8000"
  worker:
    build:
      context: ./backend
    command: celery -A app.worker worker --loglevel=info
  beat:
    build:
      context: ./backend
    command: ["celery", "-A", "app.worker", "worker", "--concurrency", "2"]
"""


def test_background_worker_service_maps_to_deployment_without_service(tmp_path):
    # A queue worker has no inbound port -> a Deployment but NO Service (a
    # ClusterIP Service would be wrong). An HTTP service is unaffected.
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "Dockerfile").write_text(_PY_DOCKERFILE)
    (tmp_path / "compose.yml").write_text(_WORKER_COMPOSE)

    result = analyze_repository(str(tmp_path))
    kinds = {w.component: w.kubernetes_kind for w in result.workload_mappings}

    # HTTP backend keeps a Service.
    assert kinds["backend"] == "Deployment + ClusterIP Service"
    # Workers: Deployment, explicitly no Service.
    for name in ("worker", "beat"):
        assert "Deployment" in kinds[name]
        assert "no Service" in kinds[name]
        assert "ClusterIP" not in kinds[name]
    worker = next(c for c in result.components if c.name == "worker")
    assert worker.container_ports == []
    assert worker.workload_candidate == kinds["worker"]


def test_no_compose_no_dockerfile_still_reports_absence(tmp_path):
    # Nothing analyzable -> honest no_compose (unchanged behaviour).
    (tmp_path / "README.md").write_text("# nothing here\n")
    result = analyze_repository(str(tmp_path))
    assert any(w.code == "no_compose" for w in result.warnings)
    assert result.components == []
