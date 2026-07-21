from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.models import (
    AnalysisResult,
    ImageBuildProfile,
    RepositoryMetadata,
    RuntimeDeploymentProfile,
    WorkloadProfile,
)
from repo_analyzer.reporters.brief_reporter import to_brief


def _question_section(brief: str, result, question_id: str) -> str:
    index, question = next(
        (index, question)
        for index, question in enumerate(result.migration_questions, start=1)
        if question.id == question_id
    )
    heading = f"### {index}. {question.question}"
    start = brief.index(heading)
    next_heading = brief.find("\n### ", start + len(heading))
    return brief[start : next_heading if next_heading != -1 else None]


def test_brief_reporter_groups_build_and_runtime_by_workload(golden_repo):
    result = analyze_repository(str(golden_repo))

    brief = to_brief(result)

    assert "backend" in brief
    assert "Image build" in brief
    assert "Runtime deployment" in brief
    assert "backend -> db" in brief


def test_brief_reporter_enriches_relevant_question_answers_from_workload_profiles(golden_repo):
    result = analyze_repository(str(golden_repo))

    brief = to_brief(result)

    build_and_run = _question_section(brief, result, "build_and_run")
    ports_and_services = _question_section(brief, result, "ports_and_services")

    assert "backend: Image build:" in build_and_run
    assert "backend: Runtime deployment:" in build_and_run
    assert "Workload controller candidates:" in ports_and_services
    assert "Companion object candidates:" in ports_and_services
    assert "backend -> db" in ports_and_services


def test_brief_reporter_renders_and_enriches_profile_open_decisions(golden_repo):
    result = analyze_repository(str(golden_repo))
    backend = next(profile for profile in result.workload_profiles if profile.name == "backend")
    frontend = next(profile for profile in result.workload_profiles if profile.name == "frontend")

    backend.image_build_profile.open_decisions.append("Choose image provenance.")
    backend.runtime_deployment_profile.open_decisions.append("Choose rollout strategy.")
    backend.runtime_deployment_profile.kubernetes_candidates[0].open_decisions.extend(
        ["Choose rollout strategy.", "Confirm service ownership."]
    )
    backend.runtime_deployment_profile.probe_candidates[0].open_decisions.append(
        "Confirm probe thresholds."
    )
    backend.runtime_deployment_profile.relationships[0].open_decisions.append(
        "Confirm dependency coordination."
    )

    brief = to_brief(result)
    workload_section = brief[
        brief.index("## Workload profiles") : brief.index("## Seven migration questions")
    ]
    unknowns = _question_section(brief, result, "repository_unknowns")
    decisions = [
        "Choose image provenance.",
        "Choose rollout strategy.",
        "Confirm service ownership.",
        "Confirm probe thresholds.",
        "Confirm dependency coordination.",
        frontend.runtime_deployment_profile.open_decisions[0],
    ]

    for decision in decisions:
        assert decision in workload_section
        assert decision in unknowns
    assert workload_section.count("Choose rollout strategy.") == 1
    assert unknowns.count("Choose rollout strategy.") == 1


def test_brief_reporter_includes_generated_profile_unresolved_decisions(golden_repo):
    result = analyze_repository(str(golden_repo))

    brief = to_brief(result)
    workload_section = brief[
        brief.index("## Workload profiles") : brief.index("## Seven migration questions")
    ]
    unknowns = _question_section(brief, result, "repository_unknowns")

    for decision in ("replica count", "CPU/memory", "PVC size", "StorageClass"):
        assert decision in workload_section
        assert decision in unknowns


def test_brief_reporter_scopes_missing_profile_facts_to_scanned_repository_facts():
    result = AnalysisResult(
        repository=RepositoryMetadata(name="repo", profile="kubernetes-p0", file_count=0),
        workload_profiles=[
            WorkloadProfile(
                name="worker",
                image_build_profile=ImageBuildProfile(),
                runtime_deployment_profile=RuntimeDeploymentProfile(),
            )
        ],
    )

    brief = to_brief(result)

    assert "no profile facts detected in scanned repository facts" in brief


def test_brief_reporter_omits_service_for_traefik_host_without_port(tmp_path):
    (tmp_path / "compose.yml").write_text(
        "services:\n"
        "  api:\n"
        "    image: example/api:latest\n"
        "    labels:\n"
        '      - "traefik.http.routers.api.rule=Host(`api.example.com`)"\n'
    )

    result = analyze_repository(str(tmp_path))
    brief = to_brief(result)
    ports_and_services = _question_section(brief, result, "ports_and_services")

    assert result.workload_mappings[0].kubernetes_kind == "Deployment"
    assert "Workload controller candidates: Deployment" in ports_and_services
    assert "Companion object candidates: Ingress" in ports_and_services
    assert "ClusterIP Service" not in ports_and_services
    assert "Companion object candidates: Service" not in ports_and_services
