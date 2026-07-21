"""Pydantic result schema for the kubernetes-p0 analyzer.

Field declaration order is intentional: Pydantic v2 preserves it in
``model_dump``, which is what fixes the JSON key order downstream. Do not
reorder fields casually.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Confidence = Literal["explicit", "derived", "unresolved"]
RelationshipType = Literal[
    "startup_order",
    "runtime_dependency",
    "configuration_reference",
    "network_consumer",
    "build_time_binding",
]
ProfileEvidenceType = Literal[
    "component_source",
    "dockerfile",
    "compose_build",
    "compose_command",
    "compose_depends_on",
    "compose_port",
    "compose_healthcheck",
    "compose_volume",
    "kubernetes_manifest",
    "configuration_reference",
    "runtime_dependency",
    "container_image_finding",
    "build_time_constraint",
]
KubernetesObjectKind = Literal[
    "Deployment",
    "StatefulSet",
    "Job",
    "CronJob",
    "DaemonSet",
    "init_container",
    "Service",
    "PVC",
    "ConfigMap",
    "Secret",
    "Ingress",
    "Gateway",
]
QuestionStatus = Literal["answered", "partial", "unresolved", "not_detected"]
CoverageStatus = Literal["present", "missing", "ignored", "error"]
CoverageRole = Literal[
    "primary",
    "selected_primary",
    "supplemental",
    "sample_or_documented_deployment",
    "test_only",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _has_profile_claims(model: _Model, excluded_fields: set[str]) -> bool:
    for field_name, value in model.__dict__.items():
        if field_name in excluded_fields:
            continue
        if isinstance(value, (list, dict, set, tuple)):
            if value:
                return True
        elif value is not None:
            return True
    return False


class Evidence(_Model):
    """A pointer back to the exact source location a fact came from.

    ``selector`` is a structural locator (YAML path, env var name, Nginx
    directive). ``symbol`` optionally names a finer target (a Dockerfile
    instruction keyword, a Python AST symbol). Line numbers are 1-based and are
    produced by parsers from the real source node, never hardcoded.
    """

    path: str
    selector: str
    symbol: str | None = None
    start_line: int
    end_line: int


class Finding(_Model):
    subject: str
    value: Any
    confidence: Confidence
    kubernetes_effect: str
    evidence: list[Evidence] = Field(default_factory=list)


class Unresolved(_Model):
    subject: str
    reason: str
    needed_input: str
    kubernetes_effect: str
    no_default_used: bool = True


class UnsupportedConstruct(_Model):
    path: str
    construct_type: str
    detail: str


class Warning(_Model):
    code: str
    message: str
    path: str | None = None


class SourceCoverage(_Model):
    source_class: str
    status: CoverageStatus
    paths: list[str] = Field(default_factory=list)
    role: CoverageRole = "primary"
    detection: str


class AnswerBasis(_Model):
    source_section: str
    subject: str
    evidence: list[Evidence] = Field(default_factory=list)


class MigrationQuestionAnswer(_Model):
    id: str
    question: str
    status: QuestionStatus
    answer: str
    basis: list[AnswerBasis] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class DetectedFile(_Model):
    path: str
    kind: str


class Component(_Model):
    """Workload-centric summary of one application component.

    A component is usually a compose service, but may also be a build project
    (e.g. a Maven module) discovered without a compose file.
    """

    name: str
    source_files: list[str] = Field(default_factory=list)
    image: str | None = None
    build_context: str | None = None
    dockerfile: str | None = None
    build_args: list[str] = Field(default_factory=list)
    language: str | None = None
    frameworks: list[str] = Field(default_factory=list)
    build_tool: str | None = None
    build_command: str | None = None
    build_artifact: str | None = None
    packaging: str | None = None
    application_server: str | None = None
    runtime: str | None = None
    command: list[str] | None = None
    workers: int | None = None
    container_ports: list[int] = Field(default_factory=list)
    context_path: str | None = None
    published_ports: list[str] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    secret_candidates: list[str] = Field(default_factory=list)
    runtime_dependencies: list[str] = Field(default_factory=list)
    volumes: list[str] = Field(default_factory=list)
    healthcheck: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    workload_candidate: str
    unresolved: list[str] = Field(default_factory=list)


class WorkloadMapping(_Model):
    component: str
    kubernetes_kind: str
    confidence: Confidence
    rationale: str
    evidence: list[Evidence] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class WorkloadRelationship(_Model):
    source: str
    target: str
    relationship_type: RelationshipType
    evidence_type: ProfileEvidenceType
    description: str
    confidence: Confidence
    evidence: list[Evidence] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)


class ImageBuildProfile(_Model):
    build_tool: str | None = None
    build_command: str | None = None
    build_context: str | None = None
    dockerfile: str | None = None
    build_args: list[str] = Field(default_factory=list)
    build_artifact: str | None = None
    packaging: str | None = None
    image: str | None = None
    base_image: str | None = None
    builder_image: str | None = None
    image_source: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_provenance_for_claims(self) -> ImageBuildProfile:
        if _has_profile_claims(self, {"evidence", "unresolved", "open_decisions"}) and not (
            self.evidence or self.unresolved or self.open_decisions
        ):
            raise ValueError(
                "non-empty profile requires evidence, unresolved, or open decisions input"
            )
        return self


class ExposureCandidate(_Model):
    port: int
    source: str
    evidence_type: ProfileEvidenceType
    confidence: Confidence
    service_candidate: bool
    description: str
    evidence: list[Evidence] = Field(default_factory=list)


class ProbeCandidateProfile(_Model):
    probe_type: str
    value: str
    evidence_type: ProfileEvidenceType
    confidence: Confidence
    evidence: list[Evidence] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)


class KubernetesObjectCandidate(_Model):
    kind: KubernetesObjectKind
    name: str | None = None
    candidate_role: Literal["workload_controller", "companion_object"]
    evidence_type: ProfileEvidenceType
    confidence: Confidence
    rationale: str
    evidence: list[Evidence] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)


class RuntimeDeploymentProfile(_Model):
    runtime: str | None = None
    language: str | None = None
    frameworks: list[str] = Field(default_factory=list)
    application_server: str | None = None
    command: list[str] | None = None
    workers: int | None = None
    container_ports: list[int] = Field(default_factory=list)
    published_ports: list[str] = Field(default_factory=list)
    context_path: str | None = None
    environment: list[str] = Field(default_factory=list)
    configmap_candidates: list[str] = Field(default_factory=list)
    secret_candidates: list[str] = Field(default_factory=list)
    volumes: list[str] = Field(default_factory=list)
    exposure_candidates: list[ExposureCandidate] = Field(default_factory=list)
    probe_candidates: list[ProbeCandidateProfile] = Field(default_factory=list)
    kubernetes_candidates: list[KubernetesObjectCandidate] = Field(default_factory=list)
    relationships: list[WorkloadRelationship] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_provenance_for_claims(self) -> RuntimeDeploymentProfile:
        if _has_profile_claims(self, {"evidence", "unresolved", "open_decisions"}) and not (
            self.evidence or self.unresolved or self.open_decisions
        ):
            raise ValueError(
                "non-empty profile requires evidence, unresolved, or open decisions input"
            )
        return self


class WorkloadProfile(_Model):
    name: str
    role: str | None = None
    source_files: list[str] = Field(default_factory=list)
    image_build_profile: ImageBuildProfile
    runtime_deployment_profile: RuntimeDeploymentProfile


class RepositoryMetadata(_Model):
    name: str
    profile: str
    git_ref: str | None = None
    file_count: int


class AnalysisResult(_Model):
    """Top-level deterministic analysis document."""

    schema_version: str = "1.0"
    repository: RepositoryMetadata
    detected_files: list[DetectedFile] = Field(default_factory=list)
    source_coverage: list[SourceCoverage] = Field(default_factory=list)
    migration_questions: list[MigrationQuestionAnswer] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    workload_profiles: list[WorkloadProfile] = Field(default_factory=list)
    workload_mappings: list[WorkloadMapping] = Field(default_factory=list)
    networking: list[Finding] = Field(default_factory=list)
    configuration: list[Finding] = Field(default_factory=list)
    secrets: list[Finding] = Field(default_factory=list)
    storage: list[Finding] = Field(default_factory=list)
    runtime_dependencies: list[Finding] = Field(default_factory=list)
    startup_order: list[Finding] = Field(default_factory=list)
    health_checks: list[Finding] = Field(default_factory=list)
    build_time_constraints: list[Finding] = Field(default_factory=list)
    container_image: list[Finding] = Field(default_factory=list)
    unresolved_operational_inputs: list[Unresolved] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)
    unsupported_constructs: list[UnsupportedConstruct] = Field(default_factory=list)
