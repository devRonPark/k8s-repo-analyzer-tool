from repo_analyzer.models import (
    AnalysisResult,
    ImageBuildProfile,
    KubernetesObjectCandidate,
    RepositoryMetadata,
    RuntimeDeploymentProfile,
    WorkloadProfile,
)


def test_analysis_result_accepts_explicit_workload_profiles():
    result = AnalysisResult(
        repository=RepositoryMetadata(name="repo", profile="kubernetes-p0", file_count=1),
        workload_profiles=[
            WorkloadProfile(
                name="backend",
                source_files=["compose.yml", "backend/Dockerfile"],
                image_build_profile=ImageBuildProfile(
                    build_context="./backend",
                    dockerfile="backend/Dockerfile",
                    build_tool="Dockerfile",
                    image_source="local_build",
                ),
                runtime_deployment_profile=RuntimeDeploymentProfile(
                    runtime="FastAPI",
                    language="Python",
                    container_ports=[8000],
                    kubernetes_candidates=[
                        KubernetesObjectCandidate(
                            kind="Deployment",
                            candidate_role="workload_controller",
                            confidence="derived",
                            rationale="stateless HTTP application",
                        ),
                        KubernetesObjectCandidate(
                            kind="Service",
                            candidate_role="companion_object",
                            confidence="derived",
                            rationale="inbound container port evidence",
                        ),
                    ],
                ),
            )
        ],
    )

    dumped = result.model_dump()
    assert dumped["workload_profiles"][0]["image_build_profile"]["dockerfile"] == "backend/Dockerfile"
    assert dumped["workload_profiles"][0]["runtime_deployment_profile"]["kubernetes_candidates"][0]["kind"] == "Deployment"
