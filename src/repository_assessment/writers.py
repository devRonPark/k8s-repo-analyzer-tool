"""Deterministic writers for checked assessment artifacts."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .contracts import (
    PROMPT_VERSION,
    RUN_LOG_SCHEMA_VERSION,
    ArtifactPaths,
    AssessmentRun,
    CheckedTopicResult,
)

_CATEGORY_LABELS = {
    "identity": "정체성과 역할",
    "build_and_image": "빌드와 이미지",
    "runtime_and_lifecycle": "런타임과 생명주기",
    "network": "네트워크",
    "dependencies": "의존성",
    "configuration": "설정과 Secret",
    "storage_and_state": "스토리지와 상태",
    "health_and_observability": "상태 확인과 관측성",
    "resources_and_scaling": "리소스와 확장",
    "security_and_access": "보안과 접근",
    "deployment": "배포",
}


def write_artifacts(
    run: AssessmentRun, output_directory: str | Path
) -> ArtifactPaths:
    """Atomically write the four v1 artifacts and return their paths."""

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    paths = ArtifactPaths(
        migration_inputs=output / "migration-inputs.yaml",
        migration_report=output / "migration-report.md",
        assessment_details=output / "assessment-details.json",
        run_log=output / "run-log.json",
    )
    _write_atomic(paths.migration_inputs, _migration_inputs_yaml(run))
    _write_atomic(paths.assessment_details, _details_json(run))
    _write_atomic(paths.run_log, _run_log_json(run))
    try:
        markdown = _migration_markdown(run)
    except Exception as exc:  # pragma: no cover - defensive artifact preservation
        markdown = (
            "# Kubernetes 이관 입력 보고서\n\n"
            "서술형 보고서를 만들지 못했습니다. 확인된 기계 결과는 "
            "`migration-inputs.yaml`과 `assessment-details.json`에서 확인하세요.\n\n"
            f"오류 유형: {type(exc).__name__}\n"
        )
    _write_atomic(paths.migration_report, markdown)
    return paths


def _migration_inputs_yaml(run: AssessmentRun) -> str:
    result = run.result
    workloads: dict[str, Any] = {}
    if result is not None:
        for workload in sorted(result.workloads):
            categories: dict[str, Any] = {}
            for category in sorted(result.workloads[workload]):
                categories[category] = _developer_category(
                    result.workloads[workload][category]
                )
            workloads[workload] = categories
    payload: dict[str, Any] = {
        "schema_version": "migration-assessment/v1",
        "repository": result.repository if result else {"revision": run.resolved_revision},
        "summary": {
            "run_status": run.status,
            "workload_count": len(workloads),
        },
        "workloads": workloads,
    }
    if result and result.required_inputs:
        payload["required_inputs"] = _sorted_mapping(result.required_inputs)
    if result and result.risks:
        payload["risks"] = result.risks
    if result and result.conflicts:
        payload["conflicts"] = [
            item.model_dump(mode="json") for item in result.conflicts
        ]
    return _yaml_text(_prune(payload))


def _developer_category(topic: CheckedTopicResult) -> dict[str, Any]:
    value: dict[str, Any] = {"status": topic.status}
    if topic.facts:
        value["facts"] = _sorted_mapping(topic.facts)
    if topic.kubernetes_candidates:
        value["kubernetes_candidates"] = _sorted_mapping(
            topic.kubernetes_candidates
        )
    if topic.required_inputs:
        value["required_inputs"] = _sorted_mapping(topic.required_inputs)
    if topic.migration_note:
        value["migration_note"] = topic.migration_note
    if topic.evidence_refs:
        value["evidence_refs"] = sorted(topic.evidence_refs)
    return value


def _details_json(run: AssessmentRun) -> str:
    payload = {
        "schema_version": "assessment-details/v1",
        "run_id": run.run_id,
        "run_status": run.status,
        "repository": (
            run.result.repository
            if run.result is not None
            else {"revision": run.resolved_revision}
        ),
        "checked_topics": [
            item.model_dump(mode="json") for item in run.checked_topics
        ],
        "evidence": [item.model_dump(mode="json") for item in run.evidence],
        "conflicts": (
            [item.model_dump(mode="json") for item in run.result.conflicts]
            if run.result
            else []
        ),
        "rejected_operations": [
            rejected.model_dump(mode="json")
            for plan in run.plans
            for rejected in plan.rejected
        ],
        "errors": run.errors,
    }
    return _json_text(payload)


def _run_log_json(run: AssessmentRun) -> str:
    payload = {
        "schema_version": RUN_LOG_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "run_id": run.run_id,
        "run_status": run.status,
        "resolved_revision": run.resolved_revision,
        "limits": run.request.limits.model_dump(mode="json"),
        "limits_used": _sorted_mapping(run.limits_used),
        "selected_plans": [plan.model_dump(mode="json") for plan in run.plans],
        "evidence": [
            {
                "id": item.id,
                "file": item.file,
                "lines": f"{item.line_start}-{item.line_end}",
                "digest": item.digest,
                "extraction_method": item.extraction_method,
            }
            for item in run.evidence
        ],
        "model_responses": [
            item.model_dump(mode="json") for item in run.model_metadata
        ],
        "events": [item.model_dump(mode="json") for item in run.events],
        "errors": run.errors,
        "topic_statuses": [
            {
                "workload": item.workload,
                "topic": item.topic,
                "status": item.status,
            }
            for item in run.checked_topics
        ],
    }
    return _json_text(payload)


def _migration_markdown(run: AssessmentRun) -> str:
    lines = [
        "# Kubernetes 이관 입력 보고서",
        "",
        f"- 실행 상태: {run.status}",
        f"- 저장소 리비전: {run.resolved_revision}",
        "",
    ]
    if run.result is None or not run.result.workloads:
        lines.extend(
            ["확인된 워크로드 결과가 없습니다. 기계 결과의 오류 기록을 확인하세요.", ""]
        )
        return "\n".join(lines)
    for workload in sorted(run.result.workloads):
        lines.extend([f"## 워크로드: {workload}", ""])
        for category in sorted(run.result.workloads[workload]):
            topic = run.result.workloads[workload][category]
            lines.extend(
                [
                    f"### {_CATEGORY_LABELS.get(category, category)}",
                    "",
                    f"- 상태: {topic.status}",
                ]
            )
            if topic.facts:
                lines.extend(["- 저장소 사실:", *_markdown_mapping(topic.facts, 2)])
            if topic.kubernetes_candidates:
                lines.extend(
                    [
                        "- Kubernetes 후보:",
                        *_markdown_mapping(topic.kubernetes_candidates, 2),
                    ]
                )
            if topic.required_inputs:
                lines.extend(
                    ["- 추가 입력:", *_markdown_mapping(topic.required_inputs, 2)]
                )
            if topic.migration_note:
                lines.append(f"- 이관 메모: {topic.migration_note}")
            if topic.evidence_refs:
                lines.append(f"- 근거: {', '.join(sorted(topic.evidence_refs))}")
            lines.append("")
    if run.result.conflicts:
        lines.extend(["## 충돌", ""])
        for conflict in run.result.conflicts:
            lines.append(
                f"- {conflict.workload}.{conflict.property_path}: "
                + _scalar(conflict.candidates)
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _markdown_mapping(value: dict[str, Any], indent: int) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent + "- "
    for key in sorted(value):
        item = value[key]
        if hasattr(item, "model_dump"):
            item = item.model_dump(mode="json")
        if isinstance(item, dict):
            lines.append(f"{prefix}{key}:")
            lines.extend(_markdown_mapping(item, indent + 2))
        elif isinstance(item, list):
            lines.append(f"{prefix}{key}:")
            for entry in item:
                if isinstance(entry, dict):
                    lines.append(" " * (indent + 2) + "-")
                    lines.extend(_markdown_mapping(entry, indent + 4))
                else:
                    lines.append(" " * (indent + 2) + f"- {_scalar(entry)}")
        else:
            lines.append(f"{prefix}{key}: {_scalar(item)}")
    return lines


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: transformed
            for key in value
            if (transformed := _prune(value[key])) not in (None, {}, [])
        }
    if isinstance(value, list):
        return [transformed for item in value if (transformed := _prune(item)) is not None]
    if hasattr(value, "model_dump"):
        return _prune(value.model_dump(mode="json"))
    return value


def _sorted_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in sorted(value)}


def _yaml_text(payload: dict[str, Any]) -> str:
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    stream = io.StringIO()
    yaml.dump(payload, stream)
    text = stream.getvalue()
    return text if text.endswith("\n") else text + "\n"


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_name("." + path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
