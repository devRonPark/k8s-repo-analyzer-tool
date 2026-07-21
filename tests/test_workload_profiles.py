import pytest

from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.models import (
    AnalysisResult,
    Component,
    Evidence,
    Finding,
    RepositoryMetadata,
    WorkloadMapping,
)
from repo_analyzer.rules.kubernetes_p0 import _published_port_number, _workload_profile


def _profile(result, name):
    return next(profile for profile in result.workload_profiles if profile.name == name)


def test_full_stack_fastapi_profiles_group_build_and_runtime(golden_repo):
    result = analyze_repository(str(golden_repo), git_ref="4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8")

    assert [profile.name for profile in result.workload_profiles] == [
        "db",
        "adminer",
        "prestart",
        "backend",
        "frontend",
    ]

    backend = _profile(result, "backend")
    assert backend.image_build_profile.build_context == "."
    assert backend.image_build_profile.dockerfile == "backend/Dockerfile"
    assert backend.image_build_profile.evidence
    assert backend.runtime_deployment_profile.runtime == "FastAPI"
    assert backend.runtime_deployment_profile.command[:2] == ["fastapi", "run"]
    assert backend.runtime_deployment_profile.container_ports == [8000]
    assert backend.runtime_deployment_profile.evidence
    assert all(
        candidate.evidence_type
        for candidate in backend.runtime_deployment_profile.kubernetes_candidates
    )
    assert any(
        candidate.kind == "Deployment" and candidate.candidate_role == "workload_controller"
        for candidate in backend.runtime_deployment_profile.kubernetes_candidates
    )
    assert any(
        candidate.kind == "Service" and candidate.candidate_role == "companion_object"
        for candidate in backend.runtime_deployment_profile.kubernetes_candidates
    )
    assert backend.runtime_deployment_profile.probe_candidates[0].evidence_type == "compose_healthcheck"
    assert backend.runtime_deployment_profile.exposure_candidates[0].evidence_type == "compose_port"
    prestart = _profile(result, "prestart")
    assert any(
        candidate.kind == "Job"
        for candidate in prestart.runtime_deployment_profile.kubernetes_candidates
    )
    assert not any(
        candidate.kind == "Service"
        for candidate in prestart.runtime_deployment_profile.kubernetes_candidates
    )


def test_full_stack_profiles_keep_operational_decisions_out_of_image_build(golden_repo):
    result = analyze_repository(str(golden_repo))

    for name in ("backend", "db"):
        profile = _profile(result, name)
        assert profile.image_build_profile.unresolved == []
        assert profile.runtime_deployment_profile.unresolved

    backend_runtime = _profile(result, "backend").runtime_deployment_profile.unresolved
    assert "replica count" in backend_runtime
    assert "CPU/memory" in backend_runtime

    database_runtime = _profile(result, "db").runtime_deployment_profile.unresolved
    assert "PVC size" in database_runtime
    assert "StorageClass" in database_runtime
    assert "DB HA & backup policy" in database_runtime


def test_full_stack_profiles_do_not_reuse_kubernetes_mapping_as_role(golden_repo):
    result = analyze_repository(str(golden_repo))

    assert all(profile.role is None for profile in result.workload_profiles)


def test_full_stack_fastapi_profiles_include_relationships(golden_repo):
    result = analyze_repository(str(golden_repo), git_ref="4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8")

    prestart = _profile(result, "prestart")
    prestart_relationships = {
        (rel.source, rel.target, rel.relationship_type)
        for rel in prestart.runtime_deployment_profile.relationships
    }
    assert ("prestart", "db", "startup_order") in prestart_relationships
    prestart_db = next(
        rel
        for rel in prestart.runtime_deployment_profile.relationships
        if rel.source == "prestart" and rel.target == "db" and rel.relationship_type == "startup_order"
    )
    assert prestart_db.evidence_type == "compose_depends_on"
    assert all("depends_on" in evidence.selector for evidence in prestart_db.evidence)

    backend = _profile(result, "backend")
    relationships = {
        (rel.source, rel.target, rel.relationship_type)
        for rel in backend.runtime_deployment_profile.relationships
    }
    assert ("backend", "db", "startup_order") in relationships
    assert ("backend", "prestart", "startup_order") in relationships
    backend_db = next(
        rel
        for rel in backend.runtime_deployment_profile.relationships
        if rel.source == "backend" and rel.target == "db" and rel.relationship_type == "startup_order"
    )
    assert backend_db.evidence_type == "compose_depends_on"
    assert "service_healthy" in backend_db.description
    assert all("depends_on" in evidence.selector for evidence in backend_db.evidence)
    backend_prestart = next(
        rel
        for rel in backend.runtime_deployment_profile.relationships
        if rel.source == "backend"
        and rel.target == "prestart"
        and rel.relationship_type == "startup_order"
    )
    assert "service_completed_successfully" in backend_prestart.description
    assert all(
        rel.evidence_type == "compose_depends_on"
        for rel in backend.runtime_deployment_profile.relationships
        if rel.relationship_type == "startup_order"
    )

    adminer = _profile(result, "adminer")
    adminer_db = next(
        rel
        for rel in adminer.runtime_deployment_profile.relationships
        if rel.source == "adminer" and rel.target == "db" and rel.relationship_type == "startup_order"
    )
    assert adminer_db.evidence_type == "compose_depends_on"
    assert all("depends_on" in evidence.selector for evidence in adminer_db.evidence)

    frontend = _profile(result, "frontend")
    assert not any(
        rel.source == "frontend" and rel.target == "backend"
        for rel in frontend.runtime_deployment_profile.relationships
    )
    assert (
        "Resolve the target for build-time constraint frontend.vite_api_url_binding before deployment."
        in frontend.runtime_deployment_profile.open_decisions
    )


def test_compose_undefined_dependency_is_an_unresolved_relationship(tmp_path):
    (tmp_path / "compose.yml").write_text(
        "services:\n"
        "  backend:\n"
        "    image: example/backend:latest\n"
        "    depends_on:\n"
        "      missing-db:\n"
        "        condition: service_healthy\n"
    )

    result = analyze_repository(str(tmp_path))

    backend = _profile(result, "backend")
    relationship = backend.runtime_deployment_profile.relationships[0]
    startup_finding = next(
        finding
        for finding in result.startup_order
        if finding.subject == "backend.waits_for.missing-db"
    )
    assert relationship.target == "missing-db"
    assert relationship.relationship_type == "startup_order"
    assert relationship.evidence_type == "compose_depends_on"
    assert relationship.confidence == "unresolved"
    assert relationship.evidence == startup_finding.evidence
    assert "service_healthy" in relationship.description
    assert relationship.open_decisions == [
        "Confirm how external dependency missing-db is provided and coordinated."
    ]


def test_workload_profile_does_not_infer_build_target_from_evidence_path():
    frontend = Component(name="frontend", workload_candidate="Deployment")
    result = AnalysisResult(
        repository=RepositoryMetadata(name="example", profile="test", file_count=0),
        components=[frontend, Component(name="backend", workload_candidate="Deployment")],
        build_time_constraints=[
            Finding(
                subject="frontend.vite_api_url_binding",
                value="build-time",
                confidence="derived",
                kubernetes_effect="requires an image rebuild",
                evidence=[
                    Evidence(
                        path="frontend/backend/reference.txt",
                        selector="VITE_API_URL",
                        start_line=1,
                        end_line=1,
                    )
                ],
            )
        ],
    )

    profile = _workload_profile(frontend, None, result, profile_count=2)

    assert not profile.runtime_deployment_profile.relationships
    assert profile.runtime_deployment_profile.open_decisions == [
        "Resolve the target for build-time constraint frontend.vite_api_url_binding before deployment."
    ]


def test_workload_profile_uses_exact_build_target_value():
    frontend = Component(name="frontend", workload_candidate="Deployment")
    mapping_evidence = Evidence(
        path="compose.yml",
        selector="$.services.frontend",
        start_line=1,
        end_line=1,
    )
    finding_evidence = Evidence(
        path="frontend/Dockerfile",
        selector="ARG VITE_API_URL",
        start_line=3,
        end_line=3,
    )
    result = AnalysisResult(
        repository=RepositoryMetadata(name="example", profile="test", file_count=0),
        components=[frontend, Component(name="backend", workload_candidate="Deployment")],
        build_time_constraints=[
            Finding(
                subject="frontend.vite_api_url_binding",
                value="backend",
                confidence="explicit",
                kubernetes_effect="requires an image rebuild",
                evidence=[finding_evidence],
            )
        ],
    )
    mapping = WorkloadMapping(
        component="frontend",
        kubernetes_kind="Deployment",
        confidence="explicit",
        rationale="fixture mapping",
        evidence=[mapping_evidence],
    )

    profile = _workload_profile(frontend, mapping, result, profile_count=2)

    assert len(profile.runtime_deployment_profile.relationships) == 1
    relationship = profile.runtime_deployment_profile.relationships[0]
    assert (relationship.source, relationship.target, relationship.relationship_type) == (
        "frontend",
        "backend",
        "build_time_binding",
    )
    assert relationship.evidence_type == "build_time_constraint"
    assert relationship.confidence == "explicit"
    assert relationship.evidence == [finding_evidence]
    assert not profile.runtime_deployment_profile.open_decisions


@pytest.mark.parametrize(
    "evidence",
    [
        Evidence(
            path="frontend/backend/reference.txt",
            selector="VITE_API_URL",
            start_line=1,
            end_line=1,
        ),
        Evidence(
            path="frontend/Dockerfile",
            selector="backend",
            start_line=1,
            end_line=1,
        ),
    ],
)
def test_workload_profile_does_not_infer_build_target_from_evidence(evidence):
    frontend = Component(name="frontend", workload_candidate="Deployment")
    result = AnalysisResult(
        repository=RepositoryMetadata(name="example", profile="test", file_count=0),
        components=[frontend, Component(name="backend", workload_candidate="Deployment")],
        build_time_constraints=[
            Finding(
                subject="frontend.vite_api_url_binding",
                value="build-time",
                confidence="derived",
                kubernetes_effect="requires an image rebuild",
                evidence=[evidence],
            )
        ],
    )

    profile = _workload_profile(frontend, None, result, profile_count=2)

    assert not profile.runtime_deployment_profile.relationships
    assert profile.runtime_deployment_profile.open_decisions == [
        "Resolve the target for build-time constraint frontend.vite_api_url_binding before deployment."
    ]


def test_workload_profile_omits_runtime_dependency_without_matching_finding():
    backend = Component(
        name="backend", workload_candidate="Deployment", runtime_dependencies=["database"]
    )
    mapping_evidence = Evidence(
        path="compose.yml", selector="$.services.backend", start_line=1, end_line=1
    )
    result = AnalysisResult(
        repository=RepositoryMetadata(name="example", profile="test", file_count=0),
        components=[backend, Component(name="database", workload_candidate="StatefulSet")],
    )
    mapping = WorkloadMapping(
        component="backend",
        kubernetes_kind="Deployment",
        confidence="explicit",
        rationale="fixture mapping",
        evidence=[mapping_evidence],
    )

    profile = _workload_profile(backend, mapping, result, profile_count=2)

    assert not any(
        relationship.relationship_type == "runtime_dependency"
        for relationship in profile.runtime_deployment_profile.relationships
    )


def test_full_stack_fastapi_profiles_scope_compose_findings_to_their_service(golden_repo):
    result = analyze_repository(str(golden_repo), git_ref="4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8")

    profiles = {profile.name: profile for profile in result.workload_profiles}

    assert {
        name
        for name, profile in profiles.items()
        if any(
            candidate.kind == "PVC"
            for candidate in profile.runtime_deployment_profile.kubernetes_candidates
        )
    } == {"db"}

    for name in ("prestart", "frontend"):
        assert all(
            "$.services.backend.healthcheck" not in evidence.selector
            for probe in profiles[name].runtime_deployment_profile.probe_candidates
            for evidence in probe.evidence
        )

    expected_ingress_profiles = {"adminer", "backend", "frontend"}
    assert {
        name
        for name, profile in profiles.items()
        if any(
            candidate.kind == "Ingress"
            for candidate in profile.runtime_deployment_profile.kubernetes_candidates
        )
    } == expected_ingress_profiles
    for name in expected_ingress_profiles:
        ingress = next(
            candidate
            for candidate in profiles[name].runtime_deployment_profile.kubernetes_candidates
            if candidate.kind == "Ingress"
        )
        assert all(f"$.services.{name}." in evidence.selector for evidence in ingress.evidence)

    expected_probe_selectors = {
        "db": {"$.services.db.healthcheck"},
        "adminer": set(),
        "prestart": set(),
        "backend": {"$.services.backend.healthcheck"},
        "frontend": set(),
    }
    for name, expected_selectors in expected_probe_selectors.items():
        assert {
            evidence.selector
            for probe in profiles[name].runtime_deployment_profile.probe_candidates
            for evidence in probe.evidence
        } == expected_selectors


def test_single_spring_boot_profile_uses_generic_port_and_probe_facts(tmp_path):
    (tmp_path / "build.gradle").write_text(
        "plugins {\n"
        "  id 'java'\n"
        "  id 'org.springframework.boot' version '3.4.1'\n"
        "}\n"
        "dependencies {\n"
        "  implementation 'org.springframework.boot:spring-boot-starter-web'\n"
        "  implementation 'org.springframework.boot:spring-boot-starter-actuator'\n"
        "}\n"
    )
    (tmp_path / "settings.gradle").write_text("rootProject.name = 'orders-service'\n")
    resources = tmp_path / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application.properties").write_text(
        "management.endpoints.web.exposure.include=health\n"
    )

    result = analyze_repository(str(tmp_path))

    assert [component.name for component in result.components] == ["orders-service"]
    profile = _profile(result, "orders-service")
    runtime = profile.runtime_deployment_profile

    exposure = next(candidate for candidate in runtime.exposure_candidates if candidate.port == 8080)
    port_fact = next(finding for finding in result.networking if finding.subject == "app.default_port")
    assert exposure.evidence == port_fact.evidence
    assert {candidate.probe_type for candidate in runtime.probe_candidates} == {
        "liveness",
        "readiness",
    }
    assert {candidate.value for candidate in runtime.probe_candidates} == {
        "/actuator/health/liveness",
        "/actuator/health/readiness",
    }
    assert {
        candidate.evidence_type for candidate in runtime.probe_candidates
    } == {"configuration_reference"}


def test_published_port_number_uses_host_side_port():
    assert _published_port_number("3000:8080") == 3000
    assert _published_port_number("127.0.0.1:3000:8080") == 3000
    assert _published_port_number("8080") is None
    assert _published_port_number("3000:8080/tcp") == 3000


def test_profile_separates_published_port_from_container_port(tmp_path):
    (tmp_path / "compose.yml").write_text(
        "services:\n"
        "  api:\n"
        "    image: example/api:latest\n"
        "    ports:\n"
        '      - "8082"\n'
        '      - "3000:8080/tcp"\n'
        '      - "127.0.0.1:3001:8081"\n'
    )

    result = analyze_repository(str(tmp_path))
    candidates = _profile(result, "api").runtime_deployment_profile.exposure_candidates

    assert [(candidate.source, candidate.port) for candidate in candidates] == [
        ("container_port", 8082),
        ("published_port", 3000),
        ("published_port", 3001),
    ]
    published_candidates = [
        candidate for candidate in candidates if candidate.source == "published_port"
    ]
    assert [candidate.evidence[0].selector for candidate in published_candidates] == [
        "$.services.api.ports[1]",
        "$.services.api.ports[2]",
    ]
    assert all(candidate.evidence for candidate in published_candidates)
    runtime = _profile(result, "api").runtime_deployment_profile
    assert runtime.container_ports == [8082]
    assert runtime.published_ports == ["3000:8080/tcp", "127.0.0.1:3001:8081"]


def test_inline_compose_environment_candidates_use_entry_evidence(tmp_path):
    (tmp_path / "compose.yml").write_text(
        "services:\n"
        "  api:\n"
        "    image: example/api:latest\n"
        "    environment:\n"
        "      LOG_LEVEL: info\n"
        "      API_TOKEN: top-secret\n"
    )

    result = analyze_repository(str(tmp_path))
    candidates = _profile(result, "api").runtime_deployment_profile.kubernetes_candidates

    configmap = next(candidate for candidate in candidates if candidate.kind == "ConfigMap")
    secret = next(candidate for candidate in candidates if candidate.kind == "Secret")
    config_finding = next(
        finding for finding in result.configuration if finding.subject == "api.config.LOG_LEVEL"
    )
    secret_finding = next(
        finding for finding in result.secrets if finding.subject == "api.secret.API_TOKEN"
    )

    assert config_finding.value == "info"
    assert secret_finding.value == "<redacted>"
    assert [evidence.selector for evidence in configmap.evidence] == [
        "$.services.api.environment.LOG_LEVEL"
    ]
    assert [evidence.selector for evidence in secret.evidence] == [
        "$.services.api.environment.API_TOKEN"
    ]


def test_image_only_compose_service_has_no_service_candidate(tmp_path):
    (tmp_path / "compose.yml").write_text(
        "services:\n"
        "  worker:\n"
        "    image: example/worker:latest\n"
    )

    result = analyze_repository(str(tmp_path))
    profile = _profile(result, "worker")

    service_candidates = [
        candidate
        for candidate in profile.runtime_deployment_profile.kubernetes_candidates
        if candidate.kind == "Service"
    ]
    assert service_candidates == []
    assert all(
        candidate.evidence_type != "compose_port"
        for candidate in profile.runtime_deployment_profile.kubernetes_candidates
    )


def test_traefik_host_label_without_port_has_ingress_but_no_service_candidate(tmp_path):
    (tmp_path / "compose.yml").write_text(
        "services:\n"
        "  api:\n"
        "    image: example/api:latest\n"
        "    labels:\n"
        '      - "traefik.http.routers.api.rule=Host(`api.example.com`)"\n'
    )

    result = analyze_repository(str(tmp_path))
    candidates = _profile(result, "api").runtime_deployment_profile.kubernetes_candidates

    ingress = next(candidate for candidate in candidates if candidate.kind == "Ingress")
    assert ingress.evidence_type == "component_source"
    assert all(evidence.symbol == "traefik.host" for evidence in ingress.evidence)
    assert not any(candidate.kind == "Service" for candidate in candidates)
    assert not any(candidate.evidence_type == "compose_port" for candidate in candidates)
