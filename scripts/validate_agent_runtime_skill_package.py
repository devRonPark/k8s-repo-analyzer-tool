"""Validate runtime-neutral agent skill package structure."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

REQUIRED_MANIFEST_FILE = "package.yaml"
REQUIRED_INTAKE_CARD_FILE = "canonical/intake-card.json"
REQUIRED_CANDIDATE_RECOMMENDATION_FILE = "canonical/candidate-recommendation.json"
REQUIRED_CONFIRMED_SCOPE_EVIDENCE_RESULT_FILE = (
    "canonical/confirmed-scope-evidence-result.json"
)
REQUIRED_MIGRATION_DIAGNOSIS_PACKAGE_FILE = (
    "canonical/migration-diagnosis-package.json"
)
REQUIRED_CANONICAL_FILES = (
    "canonical/workflow.md",
    "canonical/evidence-rules.md",
    "canonical/intake.md",
    REQUIRED_INTAKE_CARD_FILE,
    "canonical/candidate-recommendation.md",
    REQUIRED_CANDIDATE_RECOMMENDATION_FILE,
    "canonical/confirmed-scope-evidence-result.md",
    REQUIRED_CONFIRMED_SCOPE_EVIDENCE_RESULT_FILE,
    REQUIRED_MIGRATION_DIAGNOSIS_PACKAGE_FILE,
    "canonical/diagnosis-package-rubric.md",
    "canonical/validation.md",
)
REQUIRED_ADAPTER_FILES = (
    "adapters/codex/SKILL.md",
    "adapters/claude-code/COMMAND.md",
    "adapters/opencode/COMMAND.md",
)
REQUIRED_TERMS = (
    "Agent Runtime Skill Package",
    "Kubernetes Migration Field Assessment",
    "Evidence Result",
    "Migration Diagnosis Package",
    "Secret masking",
    "no-invention",
)
REQUIRED_FORBIDDEN_USER_PHRASES = (
    "고객이 선정한",
    "customer selected",
    "Runnable Unit",
    "Evidence Result",
)
REQUIRED_DIRECT_INPUT_FIELDS = (
    "raw_text",
    "normalized_meaning",
    "assumptions",
    "follow_up_checks",
)
REQUIRED_CONFIRMATION_OPTIONS = ("proceed", "edit")
REQUIRED_CANDIDATE_FIELDS = (
    "id",
    "display_name",
    "candidate_kind",
    "source_paths",
    "evidence_summary",
    "recommendation_reason",
    "confidence",
    "recommended",
)
REQUIRED_CANDIDATE_CHOICE_FIELDS = (
    "display_name",
    "evidence_summary",
    "recommendation_reason",
)
REQUIRED_SCAN_ALLOWED_INPUTS = ("path", "file_kind", "source_context")
REQUIRED_SCAN_FORBIDDEN_INPUTS = (
    "full_repository_text",
    "file_contents",
    "secrets",
)
REQUIRED_CANDIDATE_SELECTION_FLAGS = (
    "enter_selects_recommended",
    "number_selects_candidate",
    "multiple_candidates_supported",
    "direct_input_allowed",
    "direct_input_requires_normalization",
)
CANDIDATE_KIND_METADATA = {
    "web_api": {
        "priority": 0,
        "keywords": ("api", "http", "web", "controller", "fastapi", "express"),
        "label": "웹/API 서버",
        "reason": "HTTP/API 실행 흔적이 있어 운영 서비스 후보임",
    },
    "batch": {
        "priority": 1,
        "keywords": ("batch", "cron", "schedule", "scheduler", "job"),
        "label": "배치",
        "reason": "스케줄 또는 배치 실행 흔적이 있어 Job 후보임",
    },
    "worker": {
        "priority": 2,
        "keywords": ("worker", "queue", "consumer", "listener"),
        "label": "워커",
        "reason": "비동기 처리 흔적이 있어 워커 후보임",
    },
    "static_frontend": {
        "priority": 3,
        "keywords": ("vite", "next", "react", "static", "frontend"),
        "label": "정적 프론트엔드",
        "reason": "정적 자산 빌드 흔적이 있어 프론트엔드 후보임",
    },
    "unknown": {
        "priority": 4,
        "keywords": (),
        "label": "애플리케이션",
        "reason": "실행 관련 파일이 모여 있어 확인 대상 후보임",
    },
}
REQUIRED_EVIDENCE_CORE_REQUEST_FIELDS = (
    "target_candidate_id",
    "repository_root",
    "source_path_filters",
    "analysis_topics",
)
REQUIRED_EVIDENCE_RESULT_SECTIONS = (
    "scope",
    "source_confirmed_facts",
    "user_input_context",
    "required_inputs",
    "conflicts",
    "secret_masking_events",
    "no_invention_rules",
)
REQUIRED_EVIDENCE_RESULT_POLICY = {
    "keep_user_context_separate": True,
    "mask_secrets": True,
    "no_invention": True,
    "report_conflicts": True,
}
REQUIRED_NO_INVENTION_INPUTS = (
    "replicas",
    "resource_requests",
    "ingress_host",
    "storage_class",
    "production_secret_values",
)
REQUIRED_MIGRATION_DIAGNOSIS_SECTIONS = (
    "analysis_target",
    "source_confirmed_facts",
    "required_inputs",
    "migration_risks",
    "input_source_conflicts",
    "follow_up_questions",
    "evidence_appendix",
)
REQUIRED_FIELD_LANGUAGE_POLICY = {
    "audience": [
        "kubernetes_migration_engineer",
        "customer_or_application_team",
    ],
    "internal_terms_only_in": ["evidence_appendix"],
}
REQUIRED_DIAGNOSIS_REFERENCE_FIELDS = (
    "source_fact_id",
    "user_context_id",
    "required_input_id",
    "conflict_id",
    "evidence_ref",
    "evidence_result_ref",
)
REQUIRED_FOLLOW_UP_QUESTION_FIELDS = (
    "id",
    "ask_to",
    "question",
    "why_needed",
)
REQUIRED_FOLLOW_UP_REFERENCE_FIELDS = (
    "source_required_input_id",
    "source_conflict_id",
)
REQUIRED_DIAGNOSIS_NON_GOALS = (
    "manifest_generation",
    "replica_guess",
    "resource_sizing_guess",
    "secret_value_output",
)
MASKED_SECRET_VALUE = "[MASKED_SECRET]"
SECRET_PROPERTY_PATTERNS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
)
SECRET_VALUE_PATTERNS = (
    "password",
    "passwd",
    "secret=",
    "token=",
    "bearer ",
    "api_key=",
    "apikey=",
)
DIAGNOSIS_PROPERTY_LABELS = {
    "current_runtime": "현재 실행 런타임",
    "container_port": "컨테이너 포트",
    "resource_requests": "CPU/Memory 요청과 제한",
    "replicas": "replica 수",
    "ingress_host": "외부 접속 호스트",
    "storage_class": "스토리지 클래스",
    "production_secret_values": "운영 Secret 값",
}
FOLLOW_UP_QUESTION_TEXT = {
    "resource_requests": "운영 기준 CPU/Memory requests/limits 값을 확인해 주세요.",
    "replicas": "운영 기준 replica 수를 확인해 주세요.",
    "ingress_host": "외부 접속에 사용할 host 또는 도메인을 확인해 주세요.",
    "storage_class": "운영 클러스터에서 사용할 StorageClass를 확인해 주세요.",
    "production_secret_values": "운영 Secret 값은 별도 보안 경로로 제공 여부만 확인해 주세요.",
}
DIAGNOSIS_TOPIC_LABELS = {
    "runtime": "실행 방식",
    "networking": "네트워크",
    "build": "빌드",
    "configuration": "설정",
    "storage": "스토리지",
    "health": "상태 확인",
}
DIAGNOSIS_REASON_LABELS = {
    "repository_cannot_determine": "레포지토리만으로 결정할 수 없음",
}
DIAGNOSIS_NEEDED_FOR_LABELS = {
    "Pod sizing": "Pod 크기 산정",
    "migration decision": "이관 판단",
    "probe design": "Probe 설계",
}
FORBIDDEN_CANONICAL_TERMS = (
    "Codex-only",
    "Claude Code-only",
    "OpenCode-only",
)


def validate_package(package_root: Path) -> list[str]:
    errors: list[str] = []
    if not package_root.is_dir():
        return [f"package root does not exist: {package_root}"]

    canonical_files, adapter_files, manifest_errors = _manifest_paths(package_root)
    errors.extend(manifest_errors)
    for expected in REQUIRED_CANONICAL_FILES:
        if expected not in canonical_files:
            errors.append(f"manifest does not list canonical file: {expected}")
    for expected in REQUIRED_ADAPTER_FILES:
        if expected not in adapter_files:
            errors.append(f"manifest does not list adapter file: {expected}")

    canonical_texts: list[str] = []
    for relative in canonical_files:
        path = package_root / relative
        if not path.is_file():
            errors.append(f"missing canonical file: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        canonical_texts.append(text)
        for forbidden in FORBIDDEN_CANONICAL_TERMS:
            if forbidden in text:
                errors.append(f"{relative} contains runtime-specific term: {forbidden}")

    combined = "\n".join(canonical_texts)
    for term in REQUIRED_TERMS:
        if term not in combined:
            errors.append(f"canonical package does not define required term: {term}")

    _validate_intake_card(package_root, errors)
    _validate_candidate_recommendation(package_root, errors)
    _validate_confirmed_scope_evidence_result(package_root, errors)
    _validate_migration_diagnosis_package_contract(package_root, errors)

    for relative in adapter_files:
        path = package_root / relative
        if not path.is_file():
            errors.append(f"missing adapter file: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        if "canonical/" not in text:
            errors.append(f"{relative} does not reference canonical/")
        for canonical_file in canonical_files:
            canonical_ref = canonical_file.replace("canonical/", "../../canonical/")
            if canonical_ref not in text:
                errors.append(f"{relative} does not reference {canonical_ref}")
        if "Evidence Result" not in text:
            errors.append(f"{relative} does not preserve Evidence Result semantics")

    return errors


def load_intake_card(package_root: Path) -> dict[str, Any]:
    path = package_root / REQUIRED_INTAKE_CARD_FILE
    card = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(card, dict):
        raise ValueError("intake card root must be an object")
    return card


def resolve_intake_answer(
    card: dict[str, Any], question: dict[str, Any], raw_input: str
) -> dict[str, Any]:
    value = raw_input.strip()
    if not value:
        return {
            "mode": "selected_option",
            "advance": True,
            "option_id": question["recommended_option_id"],
        }
    option_ids = {
        option["id"]
        for option in question.get("options", [])
        if isinstance(option, dict) and isinstance(option.get("id"), str)
    }
    if value in option_ids:
        return {"mode": "selected_option", "advance": True, "option_id": value}
    direct_input = card["direct_input"]
    return {
        "mode": "direct_input",
        "advance": False,
        "raw_text": value,
        "requires_normalization": direct_input["normalization_required"],
        "requires_confirmation": direct_input["confirmation_required"],
        "structured_interpretation_fields": direct_input[
            "structured_interpretation_fields"
        ],
        "confirmation_options": direct_input["confirmation_options"],
    }


def load_candidate_recommendation(package_root: Path) -> dict[str, Any]:
    path = package_root / REQUIRED_CANDIDATE_RECOMMENDATION_FILE
    contract = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("candidate recommendation root must be an object")
    return contract


def load_confirmed_scope_evidence_result(package_root: Path) -> dict[str, Any]:
    path = package_root / REQUIRED_CONFIRMED_SCOPE_EVIDENCE_RESULT_FILE
    contract = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("confirmed scope evidence result root must be an object")
    return contract


def load_migration_diagnosis_package(package_root: Path) -> dict[str, Any]:
    path = package_root / REQUIRED_MIGRATION_DIAGNOSIS_PACKAGE_FILE
    contract = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("migration diagnosis package root must be an object")
    return contract


def resolve_candidate_selection(
    candidates: list[dict[str, Any]], raw_input: str
) -> dict[str, Any]:
    value = raw_input.strip()
    if not value:
        candidate = _recommended_candidate(candidates)
        return {
            "mode": "selected_candidate",
            "advance": True,
            "candidate_id": candidate["id"],
            "selection_source": "recommended_default",
        }
    if value.isdecimal():
        index = int(value) - 1
        if 0 <= index < len(candidates):
            return {
                "mode": "selected_candidate",
                "advance": True,
                "candidate_id": candidates[index]["id"],
                "selection_source": "numbered_choice",
            }
        return {
            "mode": "invalid_selection",
            "advance": False,
            "raw_text": value,
            "message": "후보 번호를 선택하거나 Enter로 추천값을 선택하세요.",
        }
    return {
        "mode": "direct_input",
        "advance": False,
        "raw_text": value,
        "requires_normalization": True,
        "requires_confirmation": True,
        "structured_interpretation_fields": list(REQUIRED_DIRECT_INPUT_FIELDS),
        "confirmation_options": list(REQUIRED_CONFIRMATION_OPTIONS),
    }


def recommend_application_candidates(
    contract: dict[str, Any], scan_facts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    allowed_inputs = set(contract["scan_policy"]["allowed_inputs"])
    forbidden_inputs = set(contract["scan_policy"]["forbidden_inputs"])
    groups: dict[str, dict[str, Any]] = {}
    for fact in scan_facts:
        _validate_scan_fact(fact, allowed_inputs, forbidden_inputs)
        path = str(fact.get("path", "")).strip()
        if not path:
            continue
        file_kind = str(fact.get("file_kind", "")).strip()
        source_context = str(fact.get("source_context", "")).strip()
        root = _candidate_root(path)
        group = groups.setdefault(
            root,
            {
                "root": root,
                "paths": [],
                "score": 0,
                "kind_scores": {},
            },
        )
        if path not in group["paths"]:
            group["paths"].append(path)
        score, kind_scores = _score_scan_fact(path, file_kind, source_context)
        group["score"] += score
        for kind, kind_score in kind_scores.items():
            group["kind_scores"][kind] = (
                group["kind_scores"].get(kind, 0) + kind_score
            )

    ranked_groups = sorted(
        groups.values(),
        key=lambda item: (-item["score"], item["root"]),
    )
    recommended_index = _recommended_group_index(ranked_groups)
    candidates = [
        _candidate_from_group(group, recommended=index == recommended_index)
        for index, group in enumerate(ranked_groups)
    ]
    return candidates


def render_candidate_choices(
    contract: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    required_fields = contract["presentation"]["required_choice_fields"]
    choices = []
    for index, candidate in enumerate(candidates, start=1):
        for field in required_fields:
            if not candidate.get(field):
                raise ValueError(f"candidate is missing display field: {field}")
        choices.append(
            {
                "number": index,
                "candidate_id": candidate["id"],
                "label": candidate["display_name"],
                "recommended": candidate.get("recommended") is True,
                "evidence_summary": candidate["evidence_summary"],
                "recommendation_reason": candidate["recommendation_reason"],
            }
        )
    return choices


def build_evidence_core_request(
    contract: dict[str, Any],
    confirmed_scope: dict[str, Any],
) -> dict[str, Any]:
    scope = confirmed_scope["confirmed_scope"]
    return {
        "operation": contract["evidence_core_request"]["operation"],
        "target_candidate_id": confirmed_scope["target_candidate_id"],
        "repository_root": confirmed_scope["repository_root"],
        "source_path_filters": {
            "include_paths": list(scope.get("include_paths", [])),
            "exclude_paths": list(scope.get("exclude_paths", [])),
        },
        "analysis_topics": list(scope.get("analysis_topics", [])),
        "user_input_context": list(confirmed_scope.get("user_input_context", [])),
        "result_policy": contract["evidence_core_request"]["result_policy"],
    }


def build_evidence_result(
    contract: dict[str, Any],
    evidence_core_request: dict[str, Any],
    *,
    source_facts: list[dict[str, Any]],
    user_context: list[dict[str, Any]],
    repository_unknowns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_confirmed_facts, source_secret_events = _normalize_source_facts(source_facts)
    user_input_context, user_secret_events = _normalize_user_context(user_context)
    required_inputs = _required_inputs(
        contract,
        source_confirmed_facts,
        user_input_context,
        repository_unknowns or [],
    )
    return {
        "schema_version": "evidence-result/v1",
        "scope": {
            "target_candidate_id": evidence_core_request["target_candidate_id"],
            "repository_root": evidence_core_request["repository_root"],
            "source_path_filters": evidence_core_request["source_path_filters"],
            "analysis_topics": evidence_core_request["analysis_topics"],
        },
        "source_confirmed_facts": source_confirmed_facts,
        "user_input_context": user_input_context,
        "required_inputs": required_inputs,
        "conflicts": _conflicts(source_facts, user_context),
        "secret_masking_events": source_secret_events + user_secret_events,
        "no_invention_rules": [
            item["id"] for item in contract["no_invention_required_inputs"]
        ],
    }


def run_confirmed_scope_evidence_core(
    contract: dict[str, Any],
    confirmed_scope: dict[str, Any],
    *,
    evidence_core: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    request = build_evidence_core_request(contract, confirmed_scope)
    evidence_core_result = evidence_core(request)
    return {
        "evidence_core_request": request,
        "evidence_result": build_evidence_result(
            contract,
            request,
            source_facts=list(evidence_core_result.get("source_facts", [])),
            user_context=request["user_input_context"],
            repository_unknowns=list(
                evidence_core_result.get("repository_unknowns", [])
            ),
        ),
    }


def build_migration_diagnosis_package(
    contract: dict[str, Any],
    evidence_result: dict[str, Any],
) -> dict[str, Any]:
    package = {
        "schema_version": contract["schema_version"],
        "analysis_target": _diagnosis_analysis_target(evidence_result),
        "source_confirmed_facts": _diagnosis_source_facts(evidence_result),
        "required_inputs": _diagnosis_required_inputs(evidence_result),
        "input_source_conflicts": _diagnosis_conflicts(evidence_result),
        "migration_risks": _diagnosis_risks(evidence_result),
        "follow_up_questions": _diagnosis_follow_up_questions(evidence_result),
        "evidence_appendix": _diagnosis_evidence_appendix(evidence_result),
    }
    errors = validate_migration_diagnosis_package(contract, package)
    if errors:
        raise ValueError("; ".join(errors))
    return package


def validate_migration_diagnosis_package(
    contract: dict[str, Any],
    package: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    evidence_index = _diagnosis_evidence_index(package.get("evidence_appendix", {}))
    if package.get("schema_version") != "migration-diagnosis-package/v1":
        errors.append(
            "migration diagnosis package schema_version must be "
            "migration-diagnosis-package/v1"
        )

    diagnosis = contract.get("diagnosis_package", {})
    required_sections = diagnosis.get("required_sections", [])
    if isinstance(required_sections, list):
        for section in required_sections:
            if section not in package:
                errors.append(f"diagnosis package missing section: {section}")
    else:
        errors.append("migration diagnosis contract required_sections are invalid")

    if not _has_reference(
        package.get("analysis_target", {}),
        ("evidence_result_ref", "source_fact_id", "evidence_ref"),
    ):
        errors.append("analysis_target must reference Evidence Result scope")
    elif not _analysis_target_reference_exists(
        package.get("analysis_target", {}),
        evidence_index,
    ):
        errors.append("analysis_target reference is missing from evidence appendix")

    for index, item in enumerate(package.get("source_confirmed_facts", [])):
        if not _has_reference(item, ("source_fact_id", "evidence_ref")):
            errors.append(
                f"source_confirmed_facts[{index}] must reference repository evidence"
            )
            continue
        source_fact_id = item.get("source_fact_id")
        if (
            source_fact_id is not None
            and source_fact_id not in evidence_index["source_fact_ids"]
        ):
            errors.append(
                f"source_confirmed_facts[{index}] source_fact_id is missing "
                "from evidence appendix"
            )
        evidence_ref = item.get("evidence_ref")
        if (
            evidence_ref is not None
            and evidence_ref not in evidence_index["evidence_refs"]
        ):
            errors.append(
                f"source_confirmed_facts[{index}] evidence_ref is missing "
                "from evidence appendix"
            )

    for index, item in enumerate(package.get("required_inputs", [])):
        if not _has_reference(item, ("required_input_id",)):
            errors.append(
                f"required_inputs[{index}] must reference an Evidence Result item"
            )
            continue
        if item.get("required_input_id") not in evidence_index["required_input_ids"]:
            errors.append(
                f"required_inputs[{index}] required_input_id is missing "
                "from evidence appendix"
            )

    for index, item in enumerate(package.get("migration_risks", [])):
        if not _has_reference(
            item,
            (
                "required_input_id",
                "conflict_id",
                "source_fact_id",
                "user_context_id",
                "evidence_ref",
            ),
        ):
            errors.append(
                f"migration_risks[{index}] must reference an Evidence Result item"
            )
            continue
        _validate_optional_reference(
            errors,
            item,
            "required_input_id",
            evidence_index["required_input_ids"],
            f"migration_risks[{index}]",
        )
        _validate_optional_reference(
            errors,
            item,
            "conflict_id",
            evidence_index["conflict_ids"],
            f"migration_risks[{index}]",
        )
        _validate_optional_reference(
            errors,
            item,
            "source_fact_id",
            evidence_index["source_fact_ids"],
            f"migration_risks[{index}]",
        )
        _validate_optional_reference(
            errors,
            item,
            "user_context_id",
            evidence_index["user_context_ids"],
            f"migration_risks[{index}]",
        )
        _validate_optional_reference(
            errors,
            item,
            "evidence_ref",
            evidence_index["evidence_refs"],
            f"migration_risks[{index}]",
        )

    for index, item in enumerate(package.get("input_source_conflicts", [])):
        if not _has_all_references(item, ("source_fact_id", "user_context_id")):
            errors.append(
                f"input_source_conflicts[{index}] must reference both conflict sides"
            )
            continue
        if item.get("source_fact_id") not in evidence_index["source_fact_ids"]:
            errors.append(
                f"input_source_conflicts[{index}] source_fact_id is missing "
                "from evidence appendix"
            )
        if item.get("user_context_id") not in evidence_index["user_context_ids"]:
            errors.append(
                f"input_source_conflicts[{index}] user_context_id is missing "
                "from evidence appendix"
            )

    question_fields = contract.get("follow_up_question_contract", {}).get(
        "required_fields",
        [],
    )
    if isinstance(question_fields, list):
        for index, item in enumerate(package.get("follow_up_questions", [])):
            missing = [field for field in question_fields if field not in item]
            if missing:
                errors.append(
                    f"follow_up_questions[{index}] missing fields: "
                    f"{', '.join(missing)}"
                )
            if not _has_reference(item, REQUIRED_FOLLOW_UP_REFERENCE_FIELDS):
                errors.append(
                    f"follow_up_questions[{index}] must reference a source item"
                )
                continue
            if (
                item.get("source_required_input_id") is not None
                and item.get("source_required_input_id")
                not in evidence_index["required_input_ids"]
            ):
                errors.append(
                    f"follow_up_questions[{index}] source_required_input_id "
                    "is missing from evidence appendix"
                )
            if (
                item.get("source_conflict_id") is not None
                and item.get("source_conflict_id")
                not in evidence_index["conflict_ids"]
            ):
                errors.append(
                    f"follow_up_questions[{index}] source_conflict_id "
                    "is missing from evidence appendix"
                )

    if "kubernetes_manifests" in package:
        errors.append("diagnosis package must not generate Kubernetes manifests")
    for artifact in package.get("generated_artifacts", []):
        if isinstance(artifact, dict) and artifact.get("type") == "kubernetes_manifest":
            errors.append("diagnosis package must not generate Kubernetes manifests")
            break

    return errors


def _validate_intake_card(package_root: Path, errors: list[str]) -> None:
    path = package_root / REQUIRED_INTAKE_CARD_FILE
    if not path.is_file():
        errors.append(f"missing intake card file: {REQUIRED_INTAKE_CARD_FILE}")
        return
    try:
        card = load_intake_card(package_root)
    except json.JSONDecodeError as exc:
        errors.append(f"invalid intake card JSON: {exc}")
        return
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        return

    if card.get("schema_version") != "analysis-start-card/v1":
        errors.append("intake card schema_version must be analysis-start-card/v1")

    direct_input = card.get("direct_input")
    if not isinstance(direct_input, dict):
        errors.append("intake card must define direct_input policy")
    else:
        for key in ("allowed", "normalization_required", "confirmation_required"):
            if direct_input.get(key) is not True:
                errors.append(f"intake card direct_input.{key} must be true")
        if direct_input.get("structured_interpretation_fields") != list(
            REQUIRED_DIRECT_INPUT_FIELDS
        ):
            errors.append("intake card direct input fields are invalid")
        if direct_input.get("confirmation_options") != list(
            REQUIRED_CONFIRMATION_OPTIONS
        ):
            errors.append("intake card confirmation options are invalid")

    forbidden = card.get("forbidden_user_phrases")
    if not isinstance(forbidden, list) or not set(
        REQUIRED_FORBIDDEN_USER_PHRASES
    ).issubset(set(forbidden)):
        errors.append("intake card must forbid customer-selection and internal terms")
        forbidden = []

    questions = card.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append("intake card must define questions")
        return
    for question in questions:
        if not isinstance(question, dict):
            errors.append("intake card question must be an object")
            continue
        prompt = question.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            errors.append("intake card question must define prompt")
            prompt = ""
        if question.get("allow_direct_input") is not True:
            errors.append(f"intake card question {question.get('id')} must allow direct input")
        options = question.get("options")
        if not isinstance(options, list) or not options:
            errors.append(f"intake card question {question.get('id')} must define options")
            continue
        option_ids = {
            option.get("id")
            for option in options
            if isinstance(option, dict) and isinstance(option.get("id"), str)
        }
        if question.get("recommended_option_id") not in option_ids:
            errors.append(
                f"intake card question {question.get('id')} recommended option is invalid"
            )
        user_facing_text = [prompt]
        user_facing_text.extend(
            option.get("label", "")
            for option in options
            if isinstance(option, dict)
        )
        for phrase in forbidden:
            if isinstance(phrase, str) and any(
                phrase in text for text in user_facing_text
            ):
                errors.append(
                    "intake card user-facing text contains forbidden phrase: "
                    f"{phrase}"
                )


def _validate_candidate_recommendation(package_root: Path, errors: list[str]) -> None:
    path = package_root / REQUIRED_CANDIDATE_RECOMMENDATION_FILE
    if not path.is_file():
        errors.append(
            "missing candidate recommendation file: "
            f"{REQUIRED_CANDIDATE_RECOMMENDATION_FILE}"
        )
        return
    try:
        contract = load_candidate_recommendation(package_root)
    except json.JSONDecodeError as exc:
        errors.append(f"invalid candidate recommendation JSON: {exc}")
        return
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        return

    if contract.get("schema_version") != "application-candidate-recommendation/v1":
        errors.append(
            "candidate recommendation schema_version must be "
            "application-candidate-recommendation/v1"
        )

    scan_policy = contract.get("scan_policy")
    if not isinstance(scan_policy, dict):
        errors.append("candidate recommendation must define scan_policy")
    else:
        if scan_policy.get("stage") != "cheap_repository_scan":
            errors.append("candidate recommendation scan stage must be cheap scan")
        if scan_policy.get("model_repository_text") is not False:
            errors.append(
                "candidate recommendation must not send full repository text "
                "to the model"
            )
        allowed_inputs = scan_policy.get("allowed_inputs")
        forbidden_inputs = scan_policy.get("forbidden_inputs")
        if not isinstance(allowed_inputs, list):
            errors.append("candidate recommendation allowed_inputs must be a list")
            allowed_inputs = []
        if not isinstance(forbidden_inputs, list):
            errors.append("candidate recommendation forbidden_inputs must be a list")
            forbidden_inputs = []
        if not set(REQUIRED_SCAN_ALLOWED_INPUTS).issubset(set(allowed_inputs)):
            errors.append("candidate recommendation cheap scan inputs are incomplete")
        if "file_contents" in allowed_inputs:
            errors.append("candidate recommendation cannot allow file_contents")
        if not set(REQUIRED_SCAN_FORBIDDEN_INPUTS).issubset(set(forbidden_inputs)):
            errors.append("candidate recommendation forbidden inputs are incomplete")

    candidate_fields = contract.get("candidate_fields")
    if not isinstance(candidate_fields, list) or not set(
        REQUIRED_CANDIDATE_FIELDS
    ).issubset(set(candidate_fields)):
        errors.append("candidate recommendation candidate_fields are incomplete")

    presentation = contract.get("presentation")
    if not isinstance(presentation, dict):
        errors.append("candidate recommendation must define presentation")
    else:
        choice_fields = presentation.get("required_choice_fields")
        if not isinstance(choice_fields, list) or not set(
            REQUIRED_CANDIDATE_CHOICE_FIELDS
        ).issubset(set(choice_fields)):
            errors.append(
                "candidate recommendation choice display fields are incomplete"
            )

    selection_behavior = contract.get("selection_behavior")
    if not isinstance(selection_behavior, dict):
        errors.append("candidate recommendation must define selection_behavior")
    else:
        for flag in REQUIRED_CANDIDATE_SELECTION_FLAGS:
            if selection_behavior.get(flag) is not True:
                errors.append(f"candidate recommendation {flag} must be true")


def _validate_confirmed_scope_evidence_result(
    package_root: Path,
    errors: list[str],
) -> None:
    path = package_root / REQUIRED_CONFIRMED_SCOPE_EVIDENCE_RESULT_FILE
    if not path.is_file():
        errors.append(
            "missing confirmed scope evidence result file: "
            f"{REQUIRED_CONFIRMED_SCOPE_EVIDENCE_RESULT_FILE}"
        )
        return
    try:
        contract = load_confirmed_scope_evidence_result(package_root)
    except json.JSONDecodeError as exc:
        errors.append(f"invalid confirmed scope evidence result JSON: {exc}")
        return
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        return

    if contract.get("schema_version") != "confirmed-scope-evidence-result/v1":
        errors.append(
            "confirmed scope evidence result schema_version must be "
            "confirmed-scope-evidence-result/v1"
        )

    request_contract = contract.get("evidence_core_request")
    if not isinstance(request_contract, dict):
        errors.append("confirmed scope contract must define evidence_core_request")
    else:
        if request_contract.get("operation") != "run_evidence_core":
            errors.append("confirmed scope contract operation must run Evidence Core")
        required_fields = request_contract.get("required_fields")
        if not isinstance(required_fields, list) or not set(
            REQUIRED_EVIDENCE_CORE_REQUEST_FIELDS
        ).issubset(set(required_fields)):
            errors.append("confirmed scope request fields are incomplete")
        if request_contract.get("result_policy") != REQUIRED_EVIDENCE_RESULT_POLICY:
            errors.append("confirmed scope result policy is invalid")

    result_contract = contract.get("evidence_result")
    if not isinstance(result_contract, dict):
        errors.append("confirmed scope contract must define evidence_result")
    else:
        required_sections = result_contract.get("required_sections")
        if not isinstance(required_sections, list) or not set(
            REQUIRED_EVIDENCE_RESULT_SECTIONS
        ).issubset(set(required_sections)):
            errors.append("confirmed scope evidence result sections are incomplete")

    required_inputs = contract.get("no_invention_required_inputs")
    if not isinstance(required_inputs, list):
        errors.append("confirmed scope contract must define no-invention inputs")
    else:
        input_ids = {
            item.get("id")
            for item in required_inputs
            if isinstance(item, dict)
        }
        if not set(REQUIRED_NO_INVENTION_INPUTS).issubset(input_ids):
            errors.append("confirmed scope no-invention inputs are incomplete")

    secret_masking = contract.get("secret_masking")
    if not isinstance(secret_masking, dict):
        errors.append("confirmed scope contract must define secret masking")
    else:
        if secret_masking.get("masked_value") != MASKED_SECRET_VALUE:
            errors.append("confirmed scope masked secret value is invalid")
        patterns = secret_masking.get("property_patterns")
        if not isinstance(patterns, list) or not set(
            SECRET_PROPERTY_PATTERNS
        ).issubset(set(patterns)):
            errors.append("confirmed scope secret masking patterns are incomplete")
        value_patterns = secret_masking.get("value_patterns")
        if not isinstance(value_patterns, list) or not set(
            SECRET_VALUE_PATTERNS
        ).issubset(set(value_patterns)):
            errors.append("confirmed scope secret value patterns are incomplete")


def _validate_migration_diagnosis_package_contract(
    package_root: Path,
    errors: list[str],
) -> None:
    path = package_root / REQUIRED_MIGRATION_DIAGNOSIS_PACKAGE_FILE
    if not path.is_file():
        errors.append(
            "missing migration diagnosis package file: "
            f"{REQUIRED_MIGRATION_DIAGNOSIS_PACKAGE_FILE}"
        )
        return
    try:
        contract = load_migration_diagnosis_package(package_root)
    except json.JSONDecodeError as exc:
        errors.append(f"invalid migration diagnosis package JSON: {exc}")
        return
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        return

    if contract.get("schema_version") != "migration-diagnosis-package/v1":
        errors.append(
            "migration diagnosis package schema_version must be "
            "migration-diagnosis-package/v1"
        )

    diagnosis = contract.get("diagnosis_package")
    if not isinstance(diagnosis, dict):
        errors.append("migration diagnosis package must define diagnosis_package")
    else:
        required_sections = diagnosis.get("required_sections")
        if not isinstance(required_sections, list) or not set(
            REQUIRED_MIGRATION_DIAGNOSIS_SECTIONS
        ).issubset(set(required_sections)):
            errors.append("migration diagnosis required sections are incomplete")

        field_language = diagnosis.get("field_language")
        if not isinstance(field_language, dict):
            errors.append("migration diagnosis package must define field language")
        else:
            if field_language.get("audience") != REQUIRED_FIELD_LANGUAGE_POLICY[
                "audience"
            ]:
                errors.append("migration diagnosis audience policy is invalid")
            if field_language.get(
                "internal_terms_only_in"
            ) != REQUIRED_FIELD_LANGUAGE_POLICY["internal_terms_only_in"]:
                errors.append("migration diagnosis internal term policy is invalid")

        traceability = diagnosis.get("traceability")
        if not isinstance(traceability, dict):
            errors.append("migration diagnosis package must define traceability")
        else:
            if traceability.get("major_judgments_require_reference") is not True:
                errors.append("migration diagnosis judgments must require references")
            allowed_fields = traceability.get("allowed_reference_fields")
            if not isinstance(allowed_fields, list) or not set(
                REQUIRED_DIAGNOSIS_REFERENCE_FIELDS
            ).issubset(set(allowed_fields)):
                errors.append("migration diagnosis reference fields are incomplete")

    follow_up_contract = contract.get("follow_up_question_contract")
    if not isinstance(follow_up_contract, dict):
        errors.append(
            "migration diagnosis package must define follow-up question contract"
        )
    else:
        question_fields = follow_up_contract.get("required_fields")
        if not isinstance(question_fields, list) or not set(
            REQUIRED_FOLLOW_UP_QUESTION_FIELDS
        ).issubset(set(question_fields)):
            errors.append("migration diagnosis follow-up fields are incomplete")
        reference_fields = follow_up_contract.get("reference_fields")
        if not isinstance(reference_fields, list) or not set(
            REQUIRED_FOLLOW_UP_REFERENCE_FIELDS
        ).issubset(set(reference_fields)):
            errors.append(
                "migration diagnosis follow-up reference fields are incomplete"
            )

    non_goals = contract.get("non_goals")
    if not isinstance(non_goals, list) or not set(
        REQUIRED_DIAGNOSIS_NON_GOALS
    ).issubset(set(non_goals)):
        errors.append("migration diagnosis non-goals are incomplete")


def _diagnosis_analysis_target(evidence_result: dict[str, Any]) -> dict[str, Any]:
    scope = evidence_result["scope"]
    target_candidate_id = scope["target_candidate_id"]
    return {
        "target_candidate_id": target_candidate_id,
        "display_name": scope.get("target_display_name", target_candidate_id),
        "repository_root": scope["repository_root"],
        "source_path_filters": scope["source_path_filters"],
        "analysis_topics": [
            _topic_label(topic) for topic in scope["analysis_topics"]
        ],
        "selection_reason": scope.get(
            "selection_reason",
            "분석 범위로 확정된 애플리케이션입니다.",
        ),
        "evidence_result_ref": "scope.target_candidate_id",
    }


def _diagnosis_source_facts(evidence_result: dict[str, Any]) -> list[dict[str, Any]]:
    facts = []
    for fact in evidence_result.get("source_confirmed_facts", []):
        facts.append(
            {
                "id": f"diagnosis-fact-{fact['id']}",
                "statement": (
                    f"{_property_label(fact['property'])} 값은 "
                    f"{fact['value']}로 확인되었습니다."
                ),
                "source_fact_id": fact["id"],
                "evidence_ref": fact["evidence_ref"],
            }
        )
    return facts


def _diagnosis_required_inputs(
    evidence_result: dict[str, Any],
) -> list[dict[str, Any]]:
    required_inputs = []
    for item in evidence_result.get("required_inputs", []):
        required_inputs.append(
            {
                "id": item["id"],
                "statement": (
                    f"{_property_label(item['id'])} 값은 "
                    "소스만으로 확정할 수 없습니다."
                ),
                "reason": _reason_label(item["reason"]),
                "needed_for": _needed_for_label(item["needed_for"]),
                "user_context_available": item["user_context_available"],
                "required_input_id": item["id"],
            }
        )
    return required_inputs


def _diagnosis_conflicts(evidence_result: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts = []
    for conflict in evidence_result.get("conflicts", []):
        conflict_id = _diagnosis_conflict_id(conflict)
        conflicts.append(
            {
                "id": conflict_id,
                "field_name": _property_label(conflict["property"]),
                "summary": (
                    f"{_property_label(conflict['property'])} 값이 "
                    "소스와 입력에서 다릅니다."
                ),
                "source_fact_id": conflict["source_fact_id"],
                "user_context_id": conflict["user_context_id"],
                "source_value": conflict["source_value"],
                "user_value": conflict["user_value"],
                "resolution_required": conflict["resolution_required"],
            }
        )
    return conflicts


def _diagnosis_risks(evidence_result: dict[str, Any]) -> list[dict[str, Any]]:
    risks = []
    for item in evidence_result.get("required_inputs", []):
        risks.append(
            {
                "id": f"risk-required-{item['id']}",
                "risk_category": "미확인 운영 입력",
                "summary": (
                    f"{_property_label(item['id'])} 값이 확정되지 않아 "
                    f"{_needed_for_label(item['needed_for'])} 판단을 보류합니다."
                ),
                "required_input_id": item["id"],
            }
        )
    for conflict in evidence_result.get("conflicts", []):
        conflict_id = _diagnosis_conflict_id(conflict)
        risks.append(
            {
                "id": f"risk-{conflict_id}",
                "risk_category": "입력-소스 충돌",
                "summary": (
                    f"{_property_label(conflict['property'])} 값이 충돌하여 "
                    "이관 설계 전에 확인이 필요합니다."
                ),
                "conflict_id": conflict_id,
                "source_fact_id": conflict["source_fact_id"],
                "user_context_id": conflict["user_context_id"],
            }
        )
    return risks


def _diagnosis_follow_up_questions(
    evidence_result: dict[str, Any],
) -> list[dict[str, Any]]:
    questions = []
    for item in evidence_result.get("required_inputs", []):
        questions.append(
            {
                "id": f"question-{item['id']}",
                "ask_to": "애플리케이션 팀 또는 운영 담당자",
                "question": FOLLOW_UP_QUESTION_TEXT.get(
                    item["id"],
                    f"{_property_label(item['id'])} 값을 확인해 주세요.",
                ),
                "why_needed": _needed_for_label(item["needed_for"]),
                "source_required_input_id": item["id"],
            }
        )
    for conflict in evidence_result.get("conflicts", []):
        conflict_id = _diagnosis_conflict_id(conflict)
        questions.append(
            {
                "id": f"question-{conflict_id}",
                "ask_to": "애플리케이션 팀 또는 운영 담당자",
                "question": (
                    f"{_property_label(conflict['property'])} 값이 "
                    "소스와 입력에서 다릅니다. 운영 기준 값을 확인해 주세요."
                ),
                "why_needed": "이관 설계 전 입력-소스 충돌 해소",
                "source_conflict_id": conflict_id,
            }
        )
    return questions


def _diagnosis_evidence_appendix(evidence_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": dict(evidence_result.get("scope", {})),
        "source_confirmed_facts": list(
            evidence_result.get("source_confirmed_facts", [])
        ),
        "user_input_context": list(evidence_result.get("user_input_context", [])),
        "required_inputs": list(evidence_result.get("required_inputs", [])),
        "conflicts": list(evidence_result.get("conflicts", [])),
        "secret_masking_events": list(
            evidence_result.get("secret_masking_events", [])
        ),
        "no_invention_rules": list(evidence_result.get("no_invention_rules", [])),
    }


def _diagnosis_conflict_id(conflict: dict[str, Any]) -> str:
    return (
        f"conflict-{conflict['source_fact_id']}-{conflict['user_context_id']}"
    )


def _property_label(property_name: str) -> str:
    return DIAGNOSIS_PROPERTY_LABELS.get(property_name, _humanize_identifier(property_name))


def _topic_label(topic: str) -> str:
    return DIAGNOSIS_TOPIC_LABELS.get(topic, topic)


def _reason_label(reason: str) -> str:
    return DIAGNOSIS_REASON_LABELS.get(reason, reason)


def _needed_for_label(needed_for: str) -> str:
    return DIAGNOSIS_NEEDED_FOR_LABELS.get(needed_for, needed_for)


def _humanize_identifier(value: str) -> str:
    return value.replace("_", " ").replace("-", " ")


def _has_reference(item: dict[str, Any], fields: tuple[str, ...]) -> bool:
    return any(item.get(field) is not None for field in fields)


def _has_all_references(item: dict[str, Any], fields: tuple[str, ...]) -> bool:
    return all(item.get(field) is not None for field in fields)


def _diagnosis_evidence_index(
    evidence_appendix: dict[str, Any],
) -> dict[str, set[Any]]:
    source_facts = evidence_appendix.get("source_confirmed_facts", [])
    user_context = evidence_appendix.get("user_input_context", [])
    required_inputs = evidence_appendix.get("required_inputs", [])
    conflicts = evidence_appendix.get("conflicts", [])
    return {
        "scope_paths": _scope_paths(evidence_appendix.get("scope", {})),
        "source_fact_ids": {
            fact.get("id") for fact in source_facts if isinstance(fact, dict)
        },
        "evidence_refs": {
            fact.get("evidence_ref") for fact in source_facts if isinstance(fact, dict)
        },
        "user_context_ids": {
            item.get("id") for item in user_context if isinstance(item, dict)
        },
        "required_input_ids": {
            item.get("id") for item in required_inputs if isinstance(item, dict)
        },
        "conflict_ids": {
            _diagnosis_conflict_id(conflict)
            for conflict in conflicts
            if isinstance(conflict, dict)
            and "source_fact_id" in conflict
            and "user_context_id" in conflict
        },
    }


def _scope_paths(scope: dict[str, Any]) -> set[str]:
    return {
        f"scope.{key}"
        for key, value in scope.items()
        if value is not None
    }


def _analysis_target_reference_exists(
    analysis_target: dict[str, Any],
    evidence_index: dict[str, set[Any]],
) -> bool:
    evidence_result_ref = analysis_target.get("evidence_result_ref")
    if evidence_result_ref is not None:
        return evidence_result_ref in evidence_index["scope_paths"]
    source_fact_id = analysis_target.get("source_fact_id")
    if source_fact_id is not None:
        return source_fact_id in evidence_index["source_fact_ids"]
    evidence_ref = analysis_target.get("evidence_ref")
    if evidence_ref is not None:
        return evidence_ref in evidence_index["evidence_refs"]
    return False


def _validate_optional_reference(
    errors: list[str],
    item: dict[str, Any],
    field: str,
    allowed_values: set[Any],
    path: str,
) -> None:
    value = item.get(field)
    if value is not None and value not in allowed_values:
        errors.append(f"{path} {field} is missing from evidence appendix")


def _normalize_source_facts(
    facts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return _normalize_records(
        facts,
        section="source_confirmed_facts",
        origin="repository_source",
        retained_fields=("evidence_ref",),
        mask_retained_fields=(),
    )


def _normalize_user_context(
    contexts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return _normalize_records(
        contexts,
        section="user_input_context",
        origin="user_input",
        retained_fields=("raw_text",),
        mask_retained_fields=("raw_text",),
    )


def _normalize_records(
    records: list[dict[str, Any]],
    *,
    section: str,
    origin: str,
    retained_fields: tuple[str, ...],
    mask_retained_fields: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = []
    secret_events = []
    for record in records:
        value, event = _mask_if_secret(
            section,
            str(record["id"]),
            str(record["property"]),
            record.get("value"),
        )
        item = {
            "id": record["id"],
            "property": record["property"],
            "value": value,
            "origin": origin,
        }
        for field in retained_fields:
            if field in mask_retained_fields:
                retained_value, retained_event = _mask_if_secret(
                    section,
                    str(record["id"]),
                    field,
                    record[field],
                )
                item[field] = retained_value
                if retained_event:
                    secret_events.append(retained_event)
            else:
                item[field] = record[field]
        normalized.append(item)
        if event:
            secret_events.append(event)
    return normalized, secret_events


def _mask_if_secret(
    section: str,
    item_id: str,
    property_name: str,
    value: Any,
) -> tuple[Any, dict[str, Any] | None]:
    if not _is_secret_like(property_name, value):
        return value, None
    return MASKED_SECRET_VALUE, {
        "section": section,
        "id": item_id,
        "property": property_name,
        "masked_value": MASKED_SECRET_VALUE,
    }


def _is_secret_property(property_name: str) -> bool:
    normalized = property_name.lower()
    return any(pattern in normalized for pattern in SECRET_PROPERTY_PATTERNS)


def _is_secret_like(property_name: str, value: Any) -> bool:
    return _is_secret_property(property_name) or _is_secret_value(value)


def _is_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.lower()
    return any(pattern in normalized for pattern in SECRET_VALUE_PATTERNS)


def _required_inputs(
    contract: dict[str, Any],
    source_confirmed_facts: list[dict[str, Any]],
    user_input_context: list[dict[str, Any]],
    repository_unknowns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_properties = {fact["property"] for fact in source_confirmed_facts}
    user_properties = {context["property"] for context in user_input_context}
    required_inputs = []
    for item in contract["no_invention_required_inputs"]:
        if item["id"] in source_properties:
            continue
        required_inputs.append(
            _required_input_item(
                item["id"],
                item["needed_for"],
                "repository_cannot_determine",
                user_properties,
            )
        )
    for unknown in repository_unknowns:
        if unknown["id"] in source_properties:
            continue
        required_inputs.append(
            _required_input_item(
                unknown["id"],
                unknown["needed_for"],
                unknown.get("reason", "repository_cannot_determine"),
                user_properties,
            )
        )
    return required_inputs


def _required_input_item(
    item_id: str,
    needed_for: str,
    reason: str,
    user_properties: set[str],
) -> dict[str, Any]:
    return {
        "id": item_id,
        "reason": reason,
        "needed_for": needed_for,
        "value": None,
        "user_context_available": item_id in user_properties,
    }


def _conflicts(
    source_facts: list[dict[str, Any]],
    user_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conflicts = []
    contexts_by_property = {
        context["property"]: context for context in user_context
    }
    for fact in source_facts:
        context = contexts_by_property.get(fact["property"])
        if context is None or context.get("value") == fact.get("value"):
            continue
        conflicts.append(
            {
                "property": fact["property"],
                "source_fact_id": fact["id"],
                "user_context_id": context["id"],
                "source_value": _conflict_value(fact["property"], fact.get("value")),
                "user_value": _conflict_value(
                    context["property"],
                    context.get("value"),
                ),
                "resolution_required": True,
            }
        )
    return conflicts


def _conflict_value(property_name: str, value: Any) -> Any:
    if _is_secret_like(property_name, value):
        return MASKED_SECRET_VALUE
    return value


def _recommended_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    recommended = [
        candidate for candidate in candidates if candidate.get("recommended") is True
    ]
    if len(recommended) != 1:
        raise ValueError(
            "candidate list must contain exactly one recommended candidate"
        )
    return recommended[0]


def _validate_scan_fact(
    fact: dict[str, Any],
    allowed_inputs: set[str],
    forbidden_inputs: set[str],
) -> None:
    if not isinstance(fact, dict):
        raise ValueError("scan fact must be an object")
    forbidden = sorted(set(fact) & forbidden_inputs)
    if forbidden:
        raise ValueError(f"forbidden scan input: {', '.join(forbidden)}")
    unsupported = sorted(set(fact) - allowed_inputs)
    if unsupported:
        raise ValueError(f"unsupported scan input: {', '.join(unsupported)}")


def _candidate_root(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "."
    if len(parts) >= 2 and parts[0] in {"apps", "services", "packages", "modules"}:
        return "/".join(parts[:2])
    return parts[0]


def _score_scan_fact(
    path: str,
    file_kind: str,
    source_context: str,
) -> tuple[int, dict[str, int]]:
    text = f"{path} {file_kind} {source_context}".lower()
    score = 1
    kind_scores: dict[str, int] = {}

    if _has_any(text, ("pom.xml", "build.gradle", "package.json", "pyproject.toml")):
        score += 2
    if _has_any(text, ("dockerfile", "containerfile", "container_manifest")):
        score += 3
    for kind, metadata in CANDIDATE_KIND_METADATA.items():
        if _has_any(text, metadata["keywords"]):
            _add_kind_score(kind_scores, kind, 4)
            score += 2

    if not kind_scores:
        _add_kind_score(kind_scores, "unknown", 1)
    return score, kind_scores


def _candidate_from_group(group: dict[str, Any], *, recommended: bool) -> dict[str, Any]:
    root = group["root"]
    kind = _dominant_candidate_kind(group["kind_scores"])
    paths = group["paths"]
    return {
        "id": _slug(root),
        "display_name": _candidate_display_name(root, kind),
        "candidate_kind": kind,
        "source_paths": paths,
        "evidence_summary": _evidence_summary(paths),
        "recommendation_reason": _recommendation_reason(kind),
        "confidence": _confidence(group["score"]),
        "recommended": recommended,
    }


def _recommended_group_index(groups: list[dict[str, Any]]) -> int | None:
    if not groups:
        return None
    top_score = groups[0]["score"]
    if _confidence(top_score) != "high":
        return None
    if len(groups) > 1 and groups[1]["score"] == top_score:
        return None
    return 0


def _dominant_candidate_kind(kind_scores: dict[str, int]) -> str:
    return max(
        CANDIDATE_KIND_METADATA,
        key=lambda kind: (
            kind_scores.get(kind, 0),
            -CANDIDATE_KIND_METADATA[kind]["priority"],
        ),
    )


def _candidate_display_name(root: str, kind: str) -> str:
    name = root.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ")
    if name.lower() == "api":
        name = "API"
    return f"{name} {CANDIDATE_KIND_METADATA[kind]['label']}"


def _evidence_summary(paths: list[str]) -> str:
    if len(paths) == 1:
        return f"{paths[0]}에서 실행 후보 신호 발견"
    return f"{paths[0]} 등 {len(paths)}개 저비용 신호 발견"


def _recommendation_reason(kind: str) -> str:
    return CANDIDATE_KIND_METADATA[kind]["reason"]


def _confidence(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _add_kind_score(kind_scores: dict[str, int], kind: str, score: int) -> None:
    kind_scores[kind] = kind_scores.get(kind, 0) + score


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "application"


def _manifest_paths(package_root: Path) -> tuple[list[str], list[str], list[str]]:
    path = package_root / REQUIRED_MANIFEST_FILE
    if not path.is_file():
        return list(REQUIRED_CANONICAL_FILES), list(REQUIRED_ADAPTER_FILES), [
            f"missing manifest file: {REQUIRED_MANIFEST_FILE}"
        ]

    canonical: list[str] = []
    adapters: list[str] = []
    section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "canonical:":
            section = "canonical"
            continue
        if stripped == "adapters:":
            section = "adapters"
            continue
        if section == "canonical" and stripped.startswith("- "):
            canonical.append(stripped[2:].strip())
            continue
        if section == "adapters" and ":" in stripped:
            _, value = stripped.split(":", 1)
            adapters.append(value.strip())

    errors = []
    if not canonical:
        errors.append("manifest has no canonical file entries")
    if not adapters:
        errors.append("manifest has no adapter file entries")
    return canonical, adapters, errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    package_root = Path(args[0]) if args else Path("skills/kubernetes-field-assessment")
    errors = validate_package(package_root)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
