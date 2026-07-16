"""Pydantic result schema for the kubernetes-p0 analyzer.

Field declaration order is intentional: Pydantic v2 preserves it in
``model_dump``, which is what fixes the JSON key order downstream. Do not
reorder fields casually.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Confidence = Literal["explicit", "derived", "unresolved"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    components: list[Component] = Field(default_factory=list)
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
