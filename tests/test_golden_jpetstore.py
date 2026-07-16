"""Integration golden test for the Maven WAR / external-servlet-container category.

Uses structured assertions (not a full-text snapshot) so the checks document the
required P0 facts an engineer needs to migrate jpetstore-6 to Kubernetes:
language/build/artifact, external application-server dependency, non-root HTTP
context path, embedded (ephemeral) datastore, image-build risks, and the items
that remain unresolved.
"""

from __future__ import annotations

import pytest

from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.models import AnalysisResult
from repo_analyzer.reporters.json_reporter import to_json


@pytest.fixture
def result(jpetstore_repo) -> AnalysisResult:
    return analyze_repository(
        str(jpetstore_repo), git_ref="5a7cc780505b88a60779b3e3c0a50b0e404cfb2d"
    )


def _app(result: AnalysisResult):
    return next(c for c in result.components if c.name == "jpetstore")


# --------------------------------------------------------------------------- #
# Language / build tool / artifact
# --------------------------------------------------------------------------- #
def test_language_frameworks_build_tool(result):
    app = _app(result)
    assert app.language == "Java 17"
    assert app.build_tool == "Maven (mvnw wrapper)"
    labels = " ".join(app.frameworks)
    assert "Spring Framework" in labels
    assert "MyBatis" in labels
    assert "Stripes" in labels


def test_build_command_and_artifact(result):
    app = _app(result)
    assert app.build_command == "./mvnw clean package"
    assert app.packaging == "war"
    assert app.build_artifact == "target/jpetstore.war"
    artifact = next(f for f in result.configuration if f.subject == "build.artifact")
    # Derived from finalName + packaging, both located in pom.xml.
    assert {e.path for e in artifact.evidence} == {"pom.xml"}


# --------------------------------------------------------------------------- #
# External servlet container / run mode
# --------------------------------------------------------------------------- #
def test_requires_external_servlet_container(result):
    app = _app(result)
    assert app.application_server is not None
    assert "Tomcat" in app.application_server
    assert "external servlet container" in app.runtime.lower()
    server = next(f for f in result.configuration if f.subject == "runtime.application_server")
    assert server.confidence == "derived"
    # Cross-referenced from POM profile, Dockerfile CMD and README.
    assert {e.path for e in server.evidence} == {"pom.xml", "Dockerfile", "README.md"}


def test_all_server_profiles_surfaced(result):
    profiles = {f.subject for f in result.configuration if f.subject.startswith("profile.")}
    assert profiles == {
        "profile.tomcat9",
        "profile.tomee80",
        "profile.wildfly26",
        "profile.liberty-ee8",
        "profile.jetty",
        "profile.glassfish5",
        "profile.payara5",
        "profile.resin",
    }


def test_start_command_captured(result):
    app = _app(result)
    assert app.command == ["./mvnw", "cargo:run", "-P", "tomcat90"]
    start = next(f for f in result.container_image if f.subject == "image.start_command")
    assert start.value == "./mvnw cargo:run -P tomcat90"


# --------------------------------------------------------------------------- #
# Ports / context path / routes
# --------------------------------------------------------------------------- #
def test_container_port_and_context_path(result):
    app = _app(result)
    assert app.container_ports == [8080]
    assert app.context_path == "/jpetstore"
    ctx = next(f for f in result.networking if f.subject == "app.context_path")
    assert ctx.value == "/jpetstore"
    assert ctx.confidence == "derived"
    paths = {e.path for e in ctx.evidence}
    assert "pom.xml" in paths and "README.md" in paths  # finalName + README URL


def test_context_path_readme_evidence_points_at_real_url_not_badge(result, jpetstore_repo):
    # Regression: the README evidence must point at the served URL line
    # (http://localhost:8080/jpetstore/), not an unrelated ".../jpetstore-6/" link.
    ctx = next(f for f in result.networking if f.subject == "app.context_path")
    readme_ev = next(e for e in ctx.evidence if e.path == "README.md")
    line = (jpetstore_repo / "README.md").read_text().splitlines()[readme_ev.start_line - 1]
    assert "/jpetstore/" in line and "localhost" in line


def test_servlet_mapping_route(result):
    mapping = next(f for f in result.networking if f.subject == "servlet.StripesDispatcher")
    assert mapping.value == "*.action"
    assert mapping.evidence[0].path.endswith("web.xml")


# --------------------------------------------------------------------------- #
# Datastore / storage / init
# --------------------------------------------------------------------------- #
def test_embedded_database_no_external_dependency(result):
    embedded = [f for f in result.runtime_dependencies if f.subject == "database.embedded"]
    assert embedded, "embedded HSQLDB must be detected"
    assert "HSQL" in embedded[0].value
    assert embedded[0].evidence[0].path.endswith("applicationContext.xml")
    # In-memory DB implies no persistent volume.
    assert result.storage == []


def test_startup_db_init_scripts(result):
    inits = [f for f in result.startup_order if f.subject == "startup.db_init"]
    assert len(inits) == 2
    values = {f.value for f in inits}
    assert any("schema" in v for v in values)
    assert any("dataload" in v for v in values)


# --------------------------------------------------------------------------- #
# Container image build & runtime risks
# --------------------------------------------------------------------------- #
def test_image_findings(result):
    subjects = {f.subject for f in result.container_image}
    assert {
        "image.base",
        "image.build_command",
        "image.start_command",
        "image.runtime_server_download",
        "image.signal_handling",
        "image.runs_as_root",
    } <= subjects
    base = next(f for f in result.container_image if f.subject == "image.base")
    assert base.value == "openjdk:25"


def test_cross_check_warnings(result):
    codes = {w.code for w in result.warnings}
    # -P tomcat90 is referenced but not defined as a POM profile (tomcat9 is).
    assert "run_profile_undefined" in codes
    # openjdk:25 base vs Java 17 build target.
    assert "jdk_version_mismatch" in codes


# --------------------------------------------------------------------------- #
# Workload mapping & unresolved
# --------------------------------------------------------------------------- #
def test_workload_mapping(result):
    mapping = next(w for w in result.workload_mappings if w.component == "jpetstore")
    assert "Deployment" in mapping.kubernetes_kind
    assert "Service" in mapping.kubernetes_kind
    assert "Ingress" in mapping.kubernetes_kind  # non-root context path
    assert mapping.confidence == "derived"


def test_unresolved_includes_java_operational_items(result):
    subjects = {u.subject for u in result.unresolved_operational_inputs}
    assert {
        "readiness_liveness_probe",
        "security_context_run_as_non_root",
        "graceful_shutdown",
        "external_database_for_scaling",
        "replica_count",
        "resource_requests_limits",
    } <= subjects
    assert all(u.no_default_used for u in result.unresolved_operational_inputs)


def test_no_health_check_detected(result):
    assert result.health_checks == []


# --------------------------------------------------------------------------- #
# Discrimination & hygiene
# --------------------------------------------------------------------------- #
def test_cdi_beans_xml_not_treated_as_spring(result):
    # WEB-INF/beans.xml is a CDI descriptor (javaee namespace), not a Spring
    # context: it must not appear as a detected spring-context or in evidence.
    detected = {d.path for d in result.detected_files}
    assert not any(p.endswith("beans.xml") for p in detected)


def test_secrets_empty_no_credentials_invented(result):
    # The repo ships no credentials (embedded DB, no auth); none must be invented.
    assert result.secrets == []


def test_no_absolute_paths_in_evidence(result):
    findings = (
        result.networking
        + result.configuration
        + result.runtime_dependencies
        + result.startup_order
        + result.container_image
    )
    for finding in findings:
        for ev in finding.evidence:
            assert not ev.path.startswith("/"), ev.path
    for d in result.detected_files:
        assert not d.path.startswith("/")


def test_analysis_is_byte_deterministic(jpetstore_repo):
    first = to_json(analyze_repository(str(jpetstore_repo)))
    second = to_json(analyze_repository(str(jpetstore_repo)))
    assert first == second
