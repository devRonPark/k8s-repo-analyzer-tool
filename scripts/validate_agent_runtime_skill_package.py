"""Validate runtime-neutral agent skill package structure."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_MANIFEST_FILE = "package.yaml"
REQUIRED_INTAKE_CARD_FILE = "canonical/intake-card.json"
REQUIRED_CANDIDATE_RECOMMENDATION_FILE = "canonical/candidate-recommendation.json"
REQUIRED_CANONICAL_FILES = (
    "canonical/workflow.md",
    "canonical/evidence-rules.md",
    "canonical/intake.md",
    REQUIRED_INTAKE_CARD_FILE,
    "canonical/candidate-recommendation.md",
    REQUIRED_CANDIDATE_RECOMMENDATION_FILE,
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
