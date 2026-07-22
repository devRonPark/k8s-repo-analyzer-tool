"""Plain, versioned contracts shared across assessment modules and adapters."""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ASSESSMENT_SCHEMA_VERSION = "migration-assessment/v1"
RUN_LOG_SCHEMA_VERSION = "assessment-run-log/v1"
PROMPT_VERSION = "assessment-prompts/v1"

TopicStatus = Literal["answered", "partial", "unresolved", "unsupported", "contradicted"]
RunStatus = Literal["completed", "completed_with_gaps", "failed"]
RunStage = Literal[
    "repository_scan",
    "analysis_plan",
    "evidence_extraction",
    "topic_analysis",
    "evidence_check",
    "report_building",
]
SourceContext = Literal[
    "primary",
    "documentation",
    "test",
    "example",
    "development",
    "generated",
    "unknown",
]
ExtractionMethod = Literal[
    "list_tree",
    "find_files",
    "search_text",
    "read_lines",
    "file_info",
    "structured_json",
    "structured_yaml",
    "structured_xml",
    "structured_toml",
    "structured_properties",
]


class ContractModel(BaseModel):
    """Strict immutable base for data crossing an assessment seam."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RunLimits(ContractModel):
    tree_entries: int = Field(default=20_000, ge=1)
    selected_targets: int = Field(default=40, ge=1)
    single_file_bytes: int = Field(default=512 * 1024, ge=1)
    lines_per_read: int = Field(default=200, ge=1)
    search_calls: int = Field(default=20, ge=0)
    matches_per_search: int = Field(default=100, ge=1)
    plan_rounds: int = Field(default=2, ge=1)
    model_calls: int = Field(default=10, ge=1)
    schema_repairs: int = Field(default=1, ge=0, le=1)
    total_seconds: int = Field(default=300, ge=1)


class AssessmentRequest(ContractModel):
    run_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    repository: str
    revision: str | None = None
    output_directory: str
    language: Literal["ko"] = "ko"
    limits: RunLimits = Field(default_factory=RunLimits)

    @field_validator("repository")
    @classmethod
    def reject_url_credentials(cls, value: str) -> str:
        parsed = urllib.parse.urlsplit(value)
        if parsed.username or parsed.password:
            raise ValueError("repository URL credentials are not allowed")
        return value


class ScanEntry(ContractModel):
    path: str
    kind: Literal["file", "directory", "symlink"]
    size: int = Field(ge=0)
    source_context: SourceContext


class RepositoryScan(ContractModel):
    repository: str
    resolved_revision: str
    revision_source: Literal["requested", "git", "tree_digest"]
    entries: list[ScanEntry]
    truncated: bool = False
    excluded_paths: list[str] = Field(default_factory=list)


class PlanTarget(ContractModel):
    path: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    topics: list[str] = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=240)
    method: Literal["read_lines", "parse_structured"]
    priority: Literal["high", "medium", "low"]


class SearchTarget(ContractModel):
    pattern: str = Field(min_length=1, max_length=256)
    paths: list[str] = Field(min_length=1)
    regex: bool = False
    topics: list[str] = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=240)
    priority: Literal["high", "medium", "low"]


class AnalysisPlan(ContractModel):
    round: int = Field(ge=1, le=2)
    targets: list[PlanTarget]
    searches: list[SearchTarget] = Field(default_factory=list)


class EvidenceItem(ContractModel):
    id: str
    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    excerpt: str
    extraction_method: ExtractionMethod
    source_context: SourceContext
    digest: str
    masked: bool = False


class SearchMatch(ContractModel):
    file: str
    line: int = Field(ge=1)
    text: str
    masked: bool = False


class ToolObservation(ContractModel):
    operation: Literal[
        "list_tree", "find_files", "search_text", "read_lines", "file_info", "parse_structured"
    ]
    target: str
    content: Any
    evidence: list[EvidenceItem] = Field(default_factory=list)
    cached: bool = False
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


class UsageSnapshot(ContractModel):
    physical_reads: int = Field(default=0, ge=0)
    search_calls: int = Field(default=0, ge=0)
    selected_targets: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)


class RequiredInput(ContractModel):
    reason: str
    needed_for: str
    candidates: list[Any] = Field(default_factory=list)


class Claim(ContractModel):
    property_path: str
    value: Any
    evidence_refs: list[str] = Field(min_length=1)


class TopicResult(ContractModel):
    topic: str
    workload: str
    status: TopicStatus
    claims: list[Claim] = Field(default_factory=list)
    kubernetes_candidates: dict[str, Any] = Field(default_factory=dict)
    required_inputs: dict[str, RequiredInput] = Field(default_factory=dict)
    unsupported_reason: str | None = None


class TopicAnalysisBatch(ContractModel):
    topics: list[TopicResult]
    needs_more_evidence: bool = False
    gap_topics: list[str] = Field(default_factory=list)


class ConfidenceFactors(ContractModel):
    direct_setting: bool
    referenced_by_runtime_path: bool
    agreeing_primary_sources: int = Field(ge=0)
    source_context: SourceContext
    conflict_detected: bool


class Confidence(ContractModel):
    level: Literal["high", "medium", "low"]
    factors: ConfidenceFactors


class CheckedClaim(Claim):
    confidence: Confidence


class CheckedTopicResult(ContractModel):
    topic: str
    workload: str
    status: TopicStatus
    facts: dict[str, Any] = Field(default_factory=dict)
    checked_claims: list[CheckedClaim] = Field(default_factory=list)
    kubernetes_candidates: dict[str, Any] = Field(default_factory=dict)
    required_inputs: dict[str, RequiredInput] = Field(default_factory=dict)
    migration_note: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class Conflict(ContractModel):
    workload: str
    topic: str
    property_path: str
    candidates: list[Any]
    evidence_refs: list[str]


class AssessmentResult(ContractModel):
    schema_version: Literal["migration-assessment/v1"] = "migration-assessment/v1"
    repository: dict[str, str]
    workloads: dict[str, dict[str, CheckedTopicResult]]
    required_inputs: dict[str, RequiredInput] = Field(default_factory=dict)
    risks: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)


class RunEvent(ContractModel):
    sequence: int = Field(ge=1)
    stage: RunStage
    kind: Literal["started", "completed", "rejected", "warning", "failed"]
    detail: dict[str, Any] = Field(default_factory=dict)


class RejectedOperation(ContractModel):
    operation: Literal["read", "search"]
    subject: dict[str, Any]
    reason: str
    detail: str


class ValidatedPlan(ContractModel):
    round: int
    targets: list[PlanTarget] = Field(default_factory=list)
    searches: list[SearchTarget] = Field(default_factory=list)
    rejected: list[RejectedOperation] = Field(default_factory=list)


class EvidenceCheckResult(ContractModel):
    topics: list[CheckedTopicResult]
    conflicts: list[Conflict] = Field(default_factory=list)
    rejected_claims: list[dict[str, Any]] = Field(default_factory=list)


class ModelMessage(ContractModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ToolDefinition(ContractModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ModelRequest(ContractModel):
    stage: Literal["analysis_plan", "topic_analysis"]
    messages: list[ModelMessage]
    tools: list[ToolDefinition] = Field(default_factory=list)
    prompt_version: str = PROMPT_VERSION


class ModelResponseMetadata(ContractModel):
    endpoint: str
    model: str
    prompt_version: str
    response_digest: str
    attempt_count: int = Field(ge=1)
    response_mode: Literal["tool_call", "json_text", "recorded"]


TModel = TypeVar("TModel", bound=BaseModel)


class ModelCompletion(ContractModel, Generic[TModel]):
    value: TModel
    metadata: ModelResponseMetadata


class AssessmentRun(ContractModel):
    run_id: str
    status: RunStatus
    request: AssessmentRequest
    resolved_revision: str
    result: AssessmentResult | None
    scan: RepositoryScan | None = None
    plans: list[ValidatedPlan] = Field(default_factory=list)
    checked_topics: list[CheckedTopicResult] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    limits_used: dict[str, int] = Field(default_factory=dict)
    model_metadata: list[ModelResponseMetadata] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


class ArtifactPaths(ContractModel):
    migration_inputs: Path
    migration_report: Path
    assessment_details: Path
    run_log: Path


class RecordedCompletion(ContractModel):
    stage: Literal["analysis_plan", "topic_analysis"]
    schema_name: str
    value: dict[str, Any]
    metadata: ModelResponseMetadata


class RecordedCompletionFile(ContractModel):
    responses: list[RecordedCompletion]

    @model_validator(mode="after")
    def require_responses(self) -> RecordedCompletionFile:
        if not self.responses:
            raise ValueError("recorded response file must contain at least one response")
        return self
