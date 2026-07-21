from repo_analyzer.analyzer import analyze_repository


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
