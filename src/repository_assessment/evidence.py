"""Pure plan validation and deterministic evidence checking."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from .contracts import (
    AnalysisPlan,
    CheckedClaim,
    CheckedTopicResult,
    Claim,
    Confidence,
    ConfidenceFactors,
    Conflict,
    EvidenceCheckResult,
    EvidenceItem,
    PlanTarget,
    RejectedOperation,
    RepositoryScan,
    RunLimits,
    SearchTarget,
    TopicResult,
    ValidatedPlan,
)
from .ports import RepositoryTools
from .repository import RepositoryToolError, SECRET_NAME

_STRUCTURED_SUFFIXES = (".json", ".yaml", ".yml", ".xml", ".toml", ".properties")
_NON_PRODUCTION_CONTEXTS = {"test", "example", "development", "generated"}


def validate_plan(
    plan: AnalysisPlan,
    scan: RepositoryScan,
    limits: RunLimits,
    prior_targets: Sequence[PlanTarget] = (),
    prior_searches: Sequence[SearchTarget] = (),
) -> ValidatedPlan:
    """Return accepted reads/searches and stable, narrow rejection records."""

    files = {entry.path for entry in scan.entries if entry.kind == "file"}
    paths = {entry.path for entry in scan.entries}
    target_keys = {_target_key(item) for item in prior_targets}
    search_keys = {_search_key(item) for item in prior_searches}
    accepted_targets: list[PlanTarget] = []
    accepted_searches: list[SearchTarget] = []
    rejected: list[RejectedOperation] = []

    for target in plan.targets:
        reason = _target_rejection_reason(
            target,
            files,
            target_keys,
            len(prior_targets) + len(accepted_targets),
            limits,
        )
        if reason:
            rejected.append(_rejected("read", target.model_dump(mode="json"), reason))
            continue
        target_keys.add(_target_key(target))
        accepted_targets.append(target)

    for search in plan.searches:
        reason = _search_rejection_reason(
            search,
            paths,
            search_keys,
            len(prior_searches) + len(accepted_searches),
            limits,
        )
        if reason:
            rejected.append(_rejected("search", search.model_dump(mode="json"), reason))
            continue
        search_keys.add(_search_key(search))
        accepted_searches.append(search)

    return ValidatedPlan(
        round=plan.round,
        targets=accepted_targets,
        searches=accepted_searches,
        rejected=rejected,
    )


def check_topics(
    topics: Sequence[TopicResult],
    evidence: Sequence[EvidenceItem],
    repository_tools: RepositoryTools,
) -> EvidenceCheckResult:
    """Verify topic claims against current repository bytes and normalize statuses."""

    evidence_by_id = {item.id: item for item in evidence}
    checked_topics: list[CheckedTopicResult] = []
    conflicts: list[Conflict] = []
    rejected_claims: list[dict[str, Any]] = []

    for topic in topics:
        valid: list[tuple[Claim, list[EvidenceItem]]] = []
        topic_rejected = False
        for claim in topic.claims:
            checked_evidence, reason = _check_claim(
                claim, evidence_by_id, repository_tools
            )
            if reason:
                topic_rejected = True
                rejected_claims.append(
                    {
                        "workload": topic.workload,
                        "topic": topic.topic,
                        "property_path": claim.property_path,
                        "reason": reason,
                    }
                )
                continue
            valid.append((claim, checked_evidence))

        facts: dict[str, Any] = {}
        checked_claims: list[CheckedClaim] = []
        evidence_refs: set[str] = set()
        primary_conflict = False
        grouped: dict[str, list[tuple[Claim, list[EvidenceItem]]]] = defaultdict(list)
        for claim, items in valid:
            grouped[claim.property_path].append((claim, items))

        for property_path, candidates in grouped.items():
            values = _distinct_values([claim.value for claim, _ in candidates])
            primary = [
                (claim, items)
                for claim, items in candidates
                if any(item.source_context == "primary" for item in items)
            ]
            primary_values = _distinct_values([claim.value for claim, _ in primary])
            selected: tuple[Claim, list[EvidenceItem]] | None
            if len(values) > 1:
                conflict_refs = sorted(
                    {item.id for _, items in candidates for item in items}
                )
                conflicts.append(
                    Conflict(
                        workload=topic.workload,
                        topic=topic.topic,
                        property_path=property_path,
                        candidates=values,
                        evidence_refs=conflict_refs,
                    )
                )
                if len(primary_values) > 1:
                    primary_conflict = True
                    selected = None
                elif primary:
                    selected = primary[0]
                else:
                    selected = None
                    topic_rejected = True
            else:
                selected = candidates[0]

            if selected is None:
                continue
            claim, items = selected
            factors = _confidence_factors(items, candidates, conflict_detected=False)
            checked_claims.append(
                CheckedClaim(
                    property_path=claim.property_path,
                    value=claim.value,
                    evidence_refs=claim.evidence_refs,
                    confidence=confidence_from(factors),
                )
            )
            _set_property(facts, claim.property_path, claim.value)
            evidence_refs.update(claim.evidence_refs)

        status = _normalized_status(
            topic,
            has_facts=bool(checked_claims),
            rejected=topic_rejected,
            primary_conflict=primary_conflict,
        )
        checked_topics.append(
            CheckedTopicResult(
                topic=topic.topic,
                workload=topic.workload,
                status=status,
                facts=facts,
                checked_claims=checked_claims,
                kubernetes_candidates=(
                    topic.kubernetes_candidates if checked_claims else {}
                ),
                required_inputs=topic.required_inputs,
                migration_note=_migration_note(status, bool(facts), bool(topic.required_inputs)),
                evidence_refs=sorted(evidence_refs),
            )
        )

    return EvidenceCheckResult(
        topics=checked_topics,
        conflicts=conflicts,
        rejected_claims=rejected_claims,
    )


def confidence_from(factors: ConfidenceFactors) -> Confidence:
    if factors.conflict_detected:
        return Confidence(level="low", factors=factors)
    if factors.source_context == "primary" and (
        (factors.direct_setting and factors.referenced_by_runtime_path)
        or factors.agreeing_primary_sources >= 2
    ):
        return Confidence(level="high", factors=factors)
    if factors.source_context == "primary" or factors.agreeing_primary_sources >= 1:
        return Confidence(level="medium", factors=factors)
    return Confidence(level="low", factors=factors)


def _target_rejection_reason(
    target: PlanTarget,
    files: set[str],
    seen: set[tuple[str, int, int, str]],
    accepted_count: int,
    limits: RunLimits,
) -> str | None:
    path = _normalized_relative(target.path)
    if path is None:
        return "invalid_path"
    if target.line_end < target.line_start:
        return "invalid_line_range"
    if path not in files:
        return "path_not_in_scan"
    key = (path, target.line_start, target.line_end, target.method)
    if key in seen:
        return "duplicate_target"
    if target.method == "parse_structured" and not path.lower().endswith(
        _STRUCTURED_SUFFIXES
    ):
        return "unsupported_method"
    if target.line_end - target.line_start + 1 > limits.lines_per_read:
        return "read_limit_exceeded"
    if accepted_count >= limits.selected_targets:
        return "target_limit_exhausted"
    return None


def _search_rejection_reason(
    search: SearchTarget,
    scan_paths: set[str],
    seen: set[tuple[str, tuple[str, ...], bool]],
    accepted_count: int,
    limits: RunLimits,
) -> str | None:
    normalized_paths = tuple(_normalized_relative(path) for path in search.paths)
    if any(path is None for path in normalized_paths):
        return "invalid_path"
    if any(
        path != "."
        and path not in scan_paths
        and not any(item.startswith(path + "/") for item in scan_paths)
        for path in normalized_paths
    ):
        return "path_not_in_scan"
    key = (search.pattern, tuple(path for path in normalized_paths if path), search.regex)
    if key in seen:
        return "duplicate_search"
    if accepted_count >= limits.search_calls:
        return "search_limit_exhausted"
    return None


def _check_claim(
    claim: Claim,
    evidence_by_id: dict[str, EvidenceItem],
    repository_tools: RepositoryTools,
) -> tuple[list[EvidenceItem], str | None]:
    items: list[EvidenceItem] = []
    for evidence_id in claim.evidence_refs:
        item = evidence_by_id.get(evidence_id)
        if item is None:
            return [], "missing_evidence"
        try:
            info = repository_tools.file_info(item.file)
        except RepositoryToolError:
            return [], "missing_file"
        if info.content["digest"] != item.digest:
            return [], "digest_mismatch"
        if info.content["source_context"] != item.source_context:
            return [], "source_context_mismatch"
        try:
            observed = repository_tools.read_lines(
                item.file, item.line_start, item.line_end
            )
        except RepositoryToolError:
            return [], "invalid_line_range"
        if observed.content.rstrip("\r\n") != item.excerpt.rstrip("\r\n"):
            return [], "excerpt_mismatch"
        if item.source_context == "generated":
            return [], "generated_source"
        if SECRET_NAME.search(item.excerpt) and not item.masked:
            return [], "unmasked_secret"
        items.append(item)
    if items and all(item.source_context in _NON_PRODUCTION_CONTEXTS for item in items):
        return [], "non_production_source"
    return items, None


def _confidence_factors(
    items: list[EvidenceItem],
    agreeing: list[tuple[Claim, list[EvidenceItem]]],
    *,
    conflict_detected: bool,
) -> ConfidenceFactors:
    primary_files = {
        item.file
        for _, evidence_items in agreeing
        for item in evidence_items
        if item.source_context == "primary"
    }
    source_context = (
        "primary"
        if any(item.source_context == "primary" for item in items)
        else items[0].source_context
    )
    return ConfidenceFactors(
        direct_setting=all(
            item.extraction_method
            in {
                "read_lines",
                "structured_json",
                "structured_yaml",
                "structured_xml",
                "structured_toml",
                "structured_properties",
            }
            for item in items
        ),
        referenced_by_runtime_path=source_context == "primary",
        agreeing_primary_sources=len(primary_files),
        source_context=source_context,
        conflict_detected=conflict_detected,
    )


def _normalized_status(
    topic: TopicResult,
    *,
    has_facts: bool,
    rejected: bool,
    primary_conflict: bool,
) -> str:
    if primary_conflict:
        return "contradicted"
    if topic.unsupported_reason and not has_facts:
        return "unsupported"
    if not has_facts and topic.required_inputs:
        return "unresolved"
    if rejected or topic.required_inputs:
        return "partial"
    if has_facts:
        return topic.status if topic.status in {"answered", "partial"} else "partial"
    return "partial"


def _migration_note(status: str, has_facts: bool, has_inputs: bool) -> str:
    if status == "answered":
        return "저장소 근거로 이 항목의 주요 값을 확인했습니다."
    if status == "contradicted":
        return "서로 다른 주요 저장소 근거가 충돌하므로 값을 확정하지 않았습니다."
    if status == "unsupported":
        return "현재 도구가 필요한 형식을 해석하지 못해 이 항목을 확인하지 못했습니다."
    if status == "unresolved":
        return "저장소만으로 결정할 수 없어 다음 단계의 입력이 필요합니다."
    if has_facts and has_inputs:
        return "일부 값은 확인했지만 다음 단계에 필요한 입력이 남아 있습니다."
    return "확인된 근거가 부족해 이 항목은 부분 결과로 남았습니다."


def _set_property(target: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in path.split(".") if part]
    if not parts:
        return
    cursor = target
    for part in parts[:-1]:
        nested = cursor.get(part)
        if not isinstance(nested, dict):
            nested = {}
            cursor[part] = nested
        cursor = nested
    cursor[parts[-1]] = value


def _distinct_values(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _normalized_relative(path: str) -> str | None:
    normalized = path.replace("\\", "/").removeprefix("./").rstrip("/") or "."
    parts = normalized.split("/")
    if normalized.startswith("/") or ".." in parts or "\x00" in normalized:
        return None
    return normalized


def _target_key(target: PlanTarget) -> tuple[str, int, int, str]:
    return (
        _normalized_relative(target.path) or target.path,
        target.line_start,
        target.line_end,
        target.method,
    )


def _search_key(search: SearchTarget) -> tuple[str, tuple[str, ...], bool]:
    return (
        search.pattern,
        tuple(_normalized_relative(path) or path for path in search.paths),
        search.regex,
    )


def _rejected(
    operation: str, subject: dict[str, Any], reason: str
) -> RejectedOperation:
    detail = {
        "invalid_path": "operation path is not repository-relative",
        "invalid_line_range": "line_end must be greater than or equal to line_start",
        "path_not_in_scan": "operation path was not present in the bounded scan",
        "duplicate_target": "the same read target was already accepted",
        "duplicate_search": "the same search was already accepted",
        "unsupported_method": "structured parsing does not support this file type",
        "read_limit_exceeded": "read range exceeds lines_per_read",
        "target_limit_exhausted": "selected target limit is exhausted",
        "search_limit_exhausted": "search call limit is exhausted",
    }[reason]
    return RejectedOperation(
        operation=operation,
        subject=subject,
        reason=reason,
        detail=detail,
    )
