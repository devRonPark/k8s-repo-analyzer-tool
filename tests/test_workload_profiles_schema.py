import pytest
from pydantic import ValidationError

from repo_analyzer.models import (
    AnalysisResult,
    Evidence,
    ExposureCandidate,
    ImageBuildProfile,
    KubernetesObjectCandidate,
    ProbeCandidateProfile,
    RepositoryMetadata,
    RuntimeDeploymentProfile,
    WorkloadRelationship,
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
                    evidence=[
                        Evidence(
                            path="compose.yml",
                            selector="services.backend.build",
                            symbol="build",
                            start_line=10,
                            end_line=13,
                        )
                    ],
                ),
                runtime_deployment_profile=RuntimeDeploymentProfile(
                    runtime="FastAPI",
                    language="Python",
                    container_ports=[8000],
                    evidence=[
                        Evidence(
                            path="compose.yml",
                            selector="services.backend",
                            symbol="service",
                            start_line=1,
                            end_line=20,
                        )
                    ],
                    exposure_candidates=[
                        ExposureCandidate(
                            port=8000,
                            source="container_port",
                            evidence_type="compose_port",
                            confidence="derived",
                            service_candidate=True,
                            description="backend listens on the published container port",
                        )
                    ],
                    probe_candidates=[
                        ProbeCandidateProfile(
                            probe_type="readiness",
                            value="/health",
                            evidence_type="compose_healthcheck",
                            confidence="derived",
                        )
                    ],
                    kubernetes_candidates=[
                        KubernetesObjectCandidate(
                            kind="Deployment",
                            candidate_role="workload_controller",
                            evidence_type="component_source",
                            confidence="derived",
                            rationale="stateless HTTP application",
                        ),
                        KubernetesObjectCandidate(
                            kind="Service",
                            candidate_role="companion_object",
                            evidence_type="compose_port",
                            confidence="derived",
                            rationale="inbound container port evidence",
                        ),
                    ],
                    relationships=[
                        WorkloadRelationship(
                            source="backend",
                            target="db",
                            relationship_type="startup_order",
                            evidence_type="compose_depends_on",
                            description="backend starts after db",
                            confidence="explicit",
                        )
                    ],
                ),
            )
        ],
    )

    dumped = result.model_dump()
    assert dumped["workload_profiles"][0]["image_build_profile"]["dockerfile"] == "backend/Dockerfile"
    assert dumped["workload_profiles"][0]["runtime_deployment_profile"]["kubernetes_candidates"][0]["kind"] == "Deployment"
    assert dumped["workload_profiles"][0]["runtime_deployment_profile"]["exposure_candidates"][0]["evidence_type"] == "compose_port"
    assert dumped["workload_profiles"][0]["runtime_deployment_profile"]["probe_candidates"][0]["evidence_type"] == "compose_healthcheck"
    assert dumped["workload_profiles"][0]["runtime_deployment_profile"]["relationships"][0]["evidence_type"] == "compose_depends_on"


@pytest.mark.parametrize(
    "profile_factory",
    [
        lambda: ImageBuildProfile(image_source="local_build"),
        lambda: RuntimeDeploymentProfile(runtime="FastAPI"),
        lambda: RuntimeDeploymentProfile(
            kubernetes_candidates=[
                KubernetesObjectCandidate(
                    kind="Deployment",
                    candidate_role="workload_controller",
                    evidence_type="component_source",
                    confidence="derived",
                    rationale="stateless HTTP application",
                )
            ]
        ),
    ],
)
def test_non_empty_profiles_require_evidence_or_unresolved(profile_factory):
    with pytest.raises(ValidationError, match="evidence, unresolved, or open decisions"):
        profile_factory()


@pytest.mark.parametrize(
    "profile_factory",
    [
        lambda: ImageBuildProfile(
            image_source="local_build",
            open_decisions=["Which registry should publish this image?"],
        ),
        lambda: RuntimeDeploymentProfile(
            runtime="FastAPI",
            open_decisions=["Should this workload be exposed outside the cluster?"],
        ),
    ],
)
def test_non_empty_profiles_accept_open_decision_provenance(profile_factory):
    profile = profile_factory()

    assert profile.open_decisions
