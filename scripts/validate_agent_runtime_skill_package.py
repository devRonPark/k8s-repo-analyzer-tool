"""Validate runtime-neutral agent skill package structure."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_MANIFEST_FILE = "package.yaml"
REQUIRED_INTAKE_CARD_FILE = "canonical/intake-card.json"
REQUIRED_CANONICAL_FILES = (
    "canonical/workflow.md",
    "canonical/evidence-rules.md",
    "canonical/intake.md",
    REQUIRED_INTAKE_CARD_FILE,
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

    for relative in adapter_files:
        path = package_root / relative
        if not path.is_file():
            errors.append(f"missing adapter file: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        if "canonical/" not in text:
            errors.append(f"{relative} does not reference canonical/")
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
