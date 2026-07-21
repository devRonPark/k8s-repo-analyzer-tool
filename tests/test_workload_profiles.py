from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.rules.kubernetes_p0 import _published_port_number


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
    assert backend.runtime_deployment_profile.relationships == []

    prestart = _profile(result, "prestart")
    assert any(
        candidate.kind == "Job"
        for candidate in prestart.runtime_deployment_profile.kubernetes_candidates
    )
    assert not any(
        candidate.kind == "Service"
        for candidate in prestart.runtime_deployment_profile.kubernetes_candidates
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
    assert _published_port_number("8080") == 8080
    assert _published_port_number("3000:8080/tcp") == 3000


def test_profile_separates_published_port_from_container_port(tmp_path):
    (tmp_path / "compose.yml").write_text(
        "services:\n"
        "  api:\n"
        "    image: example/api:latest\n"
        "    ports:\n"
        '      - "3000:8080/tcp"\n'
        '      - "127.0.0.1:3001:8081"\n'
        '      - "8082"\n'
    )

    result = analyze_repository(str(tmp_path))
    candidates = _profile(result, "api").runtime_deployment_profile.exposure_candidates

    assert [(candidate.source, candidate.port) for candidate in candidates] == [
        ("container_port", 8080),
        ("published_port", 3000),
        ("published_port", 3001),
        ("published_port", 8082),
    ]
    published_candidates = [
        candidate for candidate in candidates if candidate.source == "published_port"
    ]
    assert [candidate.evidence[0].selector for candidate in published_candidates] == [
        "$.services.api.ports[0]",
        "$.services.api.ports[1]",
        "$.services.api.ports[2]",
    ]
    assert all(candidate.evidence for candidate in published_candidates)


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
