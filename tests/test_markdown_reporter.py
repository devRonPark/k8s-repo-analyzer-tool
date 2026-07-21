from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.models import (
    AnalysisResult,
    Evidence,
    ImageBuildProfile,
    KubernetesObjectCandidate,
    RepositoryMetadata,
    RuntimeDeploymentProfile,
    WorkloadRelationship,
    WorkloadProfile,
)
from repo_analyzer.reporters.markdown_reporter import to_markdown


def test_markdown_reporter_uses_workload_profiles(golden_repo):
    result = analyze_repository(str(golden_repo))

    markdown = to_markdown(result)

    assert "## 1. Workload profiles" in markdown
    assert "Image build profile" in markdown
    assert "Runtime deployment profile" in markdown
    assert "Workload relationships" in markdown
    assert "Deployment candidate" in markdown
    assert "Service candidate" in markdown


def test_markdown_reporter_includes_candidate_and_relationship_open_decisions():
    result = AnalysisResult(
        repository=RepositoryMetadata(name="repo", profile="kubernetes-p0", file_count=1),
        workload_profiles=[
            WorkloadProfile(
                name="backend",
                image_build_profile=ImageBuildProfile(),
                runtime_deployment_profile=RuntimeDeploymentProfile(
                    evidence=[
                        Evidence(
                            path="compose.yml",
                            selector="services.backend",
                            symbol="service",
                            start_line=1,
                            end_line=2,
                        )
                    ],
                    kubernetes_candidates=[
                        KubernetesObjectCandidate(
                            kind="Deployment",
                            candidate_role="workload_controller",
                            evidence_type="component_source",
                            confidence="derived",
                            rationale="stateless application",
                            open_decisions=["Choose the deployment strategy."],
                        )
                    ],
                    relationships=[
                        WorkloadRelationship(
                            source="backend",
                            target="db",
                            relationship_type="runtime_dependency",
                            evidence_type="runtime_dependency",
                            description="backend uses db",
                            confidence="derived",
                            open_decisions=[
                                "Choose the deployment strategy.",
                                "Confirm the database endpoint.",
                            ],
                        )
                    ],
                ),
            )
        ],
    )

    markdown = to_markdown(result)

    assert "- Choose the deployment strategy." in markdown
    assert "- Confirm the database endpoint." in markdown
    assert markdown.count("- Choose the deployment strategy.") == 1
