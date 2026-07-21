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
