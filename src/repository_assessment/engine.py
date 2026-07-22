"""Runtime-independent assessment state machine."""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .contracts import (
    ASSESSMENT_SCHEMA_VERSION,
    PROMPT_VERSION,
    AnalysisPlan,
    AssessmentRequest,
    AssessmentResult,
    AssessmentRun,
    CheckedTopicResult,
    EvidenceItem,
    ModelResponseMetadata,
    RepositoryScan,
    RunEvent,
    TopicAnalysisBatch,
    TopicResult,
    ValidatedPlan,
)
from .evidence import check_topics, validate_plan
from .ports import (
    EventSink,
    ModelProtocolError,
    ModelSchemaError,
    ModelUnavailableError,
    RepositoryAccessError,
    RepositoryLimitError,
    RepositoryToolError,
    RepositoryTools,
    StructuredModelClient,
)
from .prompts import BASE_TOPICS, build_plan_request, build_topic_request

_STATUS_ORDER = {
    "answered": 0,
    "partial": 1,
    "unresolved": 2,
    "unsupported": 3,
    "contradicted": 4,
}
_TOPIC_CATEGORY = {
    "application_identity": "identity",
    "build_profile": "build_and_image",
    "artifact_profile": "build_and_image",
    "runtime_profile": "runtime_and_lifecycle",
    "entrypoint": "runtime_and_lifecycle",
    "networking": "network",
    "dependencies": "dependencies",
    "config_and_secret": "configuration",
    "storage": "storage_and_state",
    "observability": "health_and_observability",
    "existing_deploy_hints": "deployment",
    "migration_risks": "deployment",
    "unknowns": "deployment",
}


class FatalAssessmentError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass
class _RunState:
    request: AssessmentRequest
    event_sink: EventSink
    started: float = field(default_factory=lambda: time.monotonic())
    sequence: int = 0
    model_calls: int = 0
    plan_rounds: int = 0
    scan: RepositoryScan | None = None
    plans: list[ValidatedPlan] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    topics: dict[tuple[str, str], TopicResult] = field(default_factory=dict)
    events: list[RunEvent] = field(default_factory=list)
    metadata: list[ModelResponseMetadata] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def guard(self) -> None:
        if self.event_sink.is_cancelled():
            raise FatalAssessmentError("cancelled", "assessment was cancelled")
        if time.monotonic() - self.started > self.request.limits.total_seconds:
            raise FatalAssessmentError("total_timeout", "total run time limit was exceeded")

    def emit(self, stage: str, kind: str, detail: dict[str, Any] | None = None) -> None:
        self.sequence += 1
        event = RunEvent(
            sequence=self.sequence,
            stage=stage,
            kind=kind,
            detail=detail or {},
        )
        self.events.append(event)
        self.event_sink.emit(event)

    def complete_model(
        self,
        client: StructuredModelClient,
        request,
        response_model,
    ):
        self.guard()
        if self.model_calls >= self.request.limits.model_calls:
            raise RepositoryLimitError("model_calls limit exhausted")
        self.model_calls += 1
        completion = client.complete(request, response_model)
        self.metadata.append(completion.metadata)
        return completion.value


def assess(
    request: AssessmentRequest,
    model_client: StructuredModelClient,
    repository_tools: RepositoryTools,
    event_sink: EventSink,
) -> AssessmentRun:
    """Run one bounded repository assessment through the injected interfaces."""

    state = _RunState(request=request, event_sink=event_sink)
    try:
        state.guard()
        _scan_repository(state, repository_tools)
        _run_model_rounds(state, model_client, repository_tools)
        checked = _check_evidence(state, repository_tools)
        result = _build_result(state, checked)
        status = _run_status(state, checked)
        return _finish_run(state, repository_tools, status, result, checked)
    except FatalAssessmentError as exc:
        return _failed_run(state, repository_tools, exc.error_type, str(exc))
    except (RepositoryAccessError, ModelUnavailableError) as exc:
        error_type = (
            "repository_unreadable"
            if isinstance(exc, RepositoryAccessError)
            else "model_unavailable"
        )
        return _failed_run(state, repository_tools, error_type, str(exc))


def _scan_repository(state: _RunState, repository_tools: RepositoryTools) -> None:
    state.emit("repository_scan", "started")
    state.guard()
    state.scan = repository_tools.scan()
    state.emit(
        "repository_scan",
        "completed",
        {"entry_count": len(state.scan.entries), "truncated": state.scan.truncated},
    )


def _run_model_rounds(
    state: _RunState,
    model_client: StructuredModelClient,
    repository_tools: RepositoryTools,
) -> None:
    assert state.scan is not None
    gap_topics: list[str] = []
    for round_number in range(1, state.request.limits.plan_rounds + 1):
        state.plan_rounds = round_number
        state.emit("analysis_plan", "started", {"round": round_number})
        try:
            plan = state.complete_model(
                model_client,
                build_plan_request(
                    state.scan,
                    state.request.limits,
                    round_number,
                    prior_topics=list(state.topics.values()),
                    gap_topics=gap_topics,
                ),
                AnalysisPlan,
            )
        except ModelUnavailableError:
            raise
        except RepositoryLimitError as exc:
            _record_error(state, "model_calls_limit_exhausted", str(exc))
            state.emit("analysis_plan", "failed", {"round": round_number})
            break
        except (ModelProtocolError, ModelSchemaError) as exc:
            _record_error(state, "analysis_plan_invalid", str(exc))
            state.emit("analysis_plan", "failed", {"round": round_number})
            break
        validated = validate_plan(
            plan,
            state.scan,
            state.request.limits,
            [target for item in state.plans for target in item.targets],
            [search for item in state.plans for search in item.searches],
        )
        state.plans.append(validated)
        for rejected in validated.rejected:
            _record_error(state, rejected.reason, rejected.detail)
        state.emit(
            "analysis_plan",
            "completed",
            {
                "round": round_number,
                "targets": len(validated.targets),
                "searches": len(validated.searches),
                "rejected": len(validated.rejected),
            },
        )
        _extract_evidence(state, repository_tools, validated)
        batch = _analyze_topics(state, model_client)
        if batch is None or not batch.needs_more_evidence:
            break
        gap_topics = batch.gap_topics


def _extract_evidence(
    state: _RunState,
    repository_tools: RepositoryTools,
    plan: ValidatedPlan,
) -> None:
    state.emit("evidence_extraction", "started", {"round": plan.round})
    for target in plan.targets:
        state.guard()
        try:
            observation = (
                repository_tools.read_lines(
                    target.path, target.line_start, target.line_end
                )
                if target.method == "read_lines"
                else repository_tools.parse_structured(
                    target.path, target.line_start, target.line_end
                )
            )
            state.evidence.extend(observation.evidence)
        except RepositoryToolError as exc:
            _record_error(state, type(exc).__name__, str(exc))
    for search in plan.searches:
        state.guard()
        try:
            observation = repository_tools.search_text(
                search.pattern, search.paths, regex=search.regex
            )
            state.evidence.extend(observation.evidence)
        except RepositoryToolError as exc:
            _record_error(state, type(exc).__name__, str(exc))
    state.emit(
        "evidence_extraction",
        "completed",
        {"round": plan.round, "evidence_count": len(state.evidence)},
    )


def _analyze_topics(
    state: _RunState, model_client: StructuredModelClient
) -> TopicAnalysisBatch | None:
    state.emit("topic_analysis", "started", {"round": state.plan_rounds})
    rejected = [item for plan in state.plans for item in plan.rejected]
    try:
        batch = state.complete_model(
            model_client,
            build_topic_request(state.evidence, rejected, state.request.limits),
            TopicAnalysisBatch,
        )
    except ModelUnavailableError:
        raise
    except RepositoryLimitError as exc:
        _record_error(state, "model_calls_limit_exhausted", str(exc))
        state.emit("topic_analysis", "failed", {"round": state.plan_rounds})
        return None
    except (ModelProtocolError, ModelSchemaError) as exc:
        _record_error(state, "topic_analysis_invalid", str(exc))
        state.emit("topic_analysis", "failed", {"round": state.plan_rounds})
        return None
    for topic in batch.topics:
        state.topics[(topic.workload, topic.topic)] = topic
    state.emit(
        "topic_analysis",
        "completed",
        {"round": state.plan_rounds, "topic_count": len(batch.topics)},
    )
    return batch


def _check_evidence(state: _RunState, repository_tools: RepositoryTools):
    state.emit("evidence_check", "started")
    checked = check_topics(list(state.topics.values()), state.evidence, repository_tools)
    for rejected in checked.rejected_claims:
        _record_error(state, rejected["reason"], rejected["property_path"])
    state.emit(
        "evidence_check",
        "completed",
        {
            "topic_count": len(checked.topics),
            "conflict_count": len(checked.conflicts),
        },
    )
    return checked


def _build_result(state: _RunState, checked) -> AssessmentResult:
    assert state.scan is not None
    state.emit("report_building", "started")
    grouped: dict[str, dict[str, list[CheckedTopicResult]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for topic in checked.topics:
        grouped[topic.workload][_category_for(topic)].append(topic)
    workloads: dict[str, dict[str, CheckedTopicResult]] = {}
    required_inputs = {}
    for workload in sorted(grouped):
        categories: dict[str, CheckedTopicResult] = {}
        for category in sorted(grouped[workload]):
            merged = _merge_category(category, grouped[workload][category])
            categories[category] = merged
            for key, value in merged.required_inputs.items():
                required_inputs[f"{workload}.{category}.{key}"] = value
        workloads[workload] = categories
    result = AssessmentResult(
        repository={
            "source": state.request.repository,
            "revision": state.scan.resolved_revision,
        },
        workloads=workloads,
        required_inputs=required_inputs,
        conflicts=checked.conflicts,
    )
    state.emit(
        "report_building",
        "completed",
        {"workload_count": len(workloads)},
    )
    return result


def _category_for(topic: CheckedTopicResult) -> str:
    if topic.topic == "unknowns":
        keys = set(topic.required_inputs)
        if keys and all(key.startswith("resources.") for key in keys):
            return "resources_and_scaling"
        if keys and all(key.startswith("security.") for key in keys):
            return "security_and_access"
    return _TOPIC_CATEGORY[topic.topic]


def _merge_category(
    category: str, topics: list[CheckedTopicResult]
) -> CheckedTopicResult:
    status = max((topic.status for topic in topics), key=lambda item: _STATUS_ORDER[item])
    facts: dict[str, Any] = {}
    candidates: dict[str, Any] = {}
    required = {}
    claims = []
    refs: set[str] = set()
    for topic in topics:
        _deep_merge(facts, topic.facts)
        _deep_merge(candidates, topic.kubernetes_candidates)
        required.update(topic.required_inputs)
        claims.extend(topic.checked_claims)
        refs.update(topic.evidence_refs)
    note = next(
        (topic.migration_note for topic in topics if topic.status == status), ""
    )
    return CheckedTopicResult(
        topic=category,
        workload=topics[0].workload,
        status=status,
        facts=facts,
        checked_claims=claims,
        kubernetes_candidates=candidates,
        required_inputs=required,
        migration_note=note,
        evidence_refs=sorted(refs),
    )


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _run_status(state: _RunState, checked) -> str:
    observed_topics = {topic.topic for topic in checked.topics}
    has_gap = (
        bool(state.errors)
        or any(topic.status != "answered" for topic in checked.topics)
        or not set(BASE_TOPICS).issubset(observed_topics)
    )
    return "completed_with_gaps" if has_gap else "completed"


def _finish_run(
    state: _RunState,
    repository_tools: RepositoryTools,
    status: str,
    result: AssessmentResult,
    checked,
) -> AssessmentRun:
    assert state.scan is not None
    return AssessmentRun(
        run_id=_run_id(state.request, state.scan.resolved_revision),
        status=status,
        request=state.request,
        resolved_revision=state.scan.resolved_revision,
        result=result,
        scan=state.scan,
        plans=state.plans,
        checked_topics=checked.topics,
        evidence=state.evidence,
        events=state.events,
        limits_used=_usage(state, repository_tools),
        model_metadata=state.metadata,
        errors=state.errors,
    )


def _failed_run(
    state: _RunState,
    repository_tools: RepositoryTools,
    error_type: str,
    message: str,
) -> AssessmentRun:
    _record_error(state, error_type, message)
    revision = state.scan.resolved_revision if state.scan else "unknown"
    return AssessmentRun(
        run_id=_run_id(state.request, revision),
        status="failed",
        request=state.request,
        resolved_revision=revision,
        result=None,
        scan=state.scan,
        plans=state.plans,
        evidence=state.evidence,
        events=state.events,
        limits_used=_usage(state, repository_tools),
        model_metadata=state.metadata,
        errors=state.errors,
    )


def _usage(state: _RunState, repository_tools: RepositoryTools) -> dict[str, int]:
    usage = getattr(repository_tools, "usage", None)
    if usage is None and hasattr(repository_tools, "wrapped"):
        usage = getattr(repository_tools.wrapped, "usage", None)
    result = {
        "model_calls": state.model_calls,
        "plan_rounds": state.plan_rounds,
        "physical_reads": 0,
        "search_calls": 0,
        "selected_targets": 0,
    }
    if usage is not None:
        snapshot = usage.model_dump()
        result.update(
            {
                key: snapshot[key]
                for key in ("physical_reads", "search_calls", "selected_targets")
            }
        )
    return result


def _record_error(state: _RunState, error_type: str, message: str) -> None:
    state.errors.append({"type": error_type, "message": message})


def _run_id(request: AssessmentRequest, revision: str) -> str:
    if request.run_id:
        return request.run_id
    payload = json.dumps(
        {
            "repository": request.repository,
            "revision": revision,
            "schema": ASSESSMENT_SCHEMA_VERSION,
            "prompt": PROMPT_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "run-" + hashlib.sha256(payload).hexdigest()[:16]
