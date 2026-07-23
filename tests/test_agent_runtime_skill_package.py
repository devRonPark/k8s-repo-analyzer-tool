import importlib.util
import json
from pathlib import Path


def _load_validator():
    path = Path("scripts/validate_agent_runtime_skill_package.py")
    spec = importlib.util.spec_from_file_location(
        "validate_agent_runtime_skill_package", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_field_assessment_package_has_runtime_neutral_foundation() -> None:
    validator = _load_validator()

    errors = validator.validate_package(Path("skills/kubernetes-field-assessment"))

    assert errors == []


def test_validator_rejects_adapter_that_does_not_reference_canonical_package(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    package = tmp_path / "package"
    _write_manifest(package, validator.REQUIRED_CANONICAL_FILES, validator.REQUIRED_ADAPTER_FILES)
    for relative in validator.REQUIRED_CANONICAL_FILES:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == validator.REQUIRED_INTAKE_CARD_FILE:
            _write_intake_card(path)
        else:
            path.write_text("Evidence Result\nMigration Diagnosis Package\n", encoding="utf-8")
    for relative in validator.REQUIRED_ADAPTER_FILES:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("standalone runtime instructions\n", encoding="utf-8")

    errors = validator.validate_package(package)

    assert any("does not reference canonical/" in error for error in errors)


def test_validator_rejects_manifest_that_does_not_list_required_adapter(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    package = tmp_path / "package"
    listed_adapters = validator.REQUIRED_ADAPTER_FILES[:-1]
    _write_manifest(package, validator.REQUIRED_CANONICAL_FILES, listed_adapters)
    for relative in validator.REQUIRED_CANONICAL_FILES:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == validator.REQUIRED_INTAKE_CARD_FILE:
            _write_intake_card(path)
        else:
            path.write_text(
                "Agent Runtime Skill Package\n"
                "Kubernetes Migration Field Assessment\n"
                "Evidence Result\n"
                "Migration Diagnosis Package\n"
                "Secret masking\n"
                "no-invention\n",
                encoding="utf-8",
            )
    for relative in listed_adapters:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "See canonical/. Preserve Evidence Result semantics.\n",
            encoding="utf-8",
        )

    errors = validator.validate_package(package)

    assert any("manifest does not list adapter file" in error for error in errors)


def test_analysis_start_card_declares_choice_defaults_and_direct_input() -> None:
    validator = _load_validator()

    card = validator.load_intake_card(Path("skills/kubernetes-field-assessment"))

    assert card["schema_version"] == "analysis-start-card/v1"
    assert [question["id"] for question in card["questions"]] == [
        "application_shape",
        "current_execution_shape",
        "analysis_purpose",
    ]
    forbidden = set(card["forbidden_user_phrases"])
    assert {
        "고객이 선정한",
        "customer selected",
        "Runnable Unit",
        "Evidence Result",
    } <= forbidden
    assert card["direct_input"]["allowed"] is True
    assert card["direct_input"]["normalization_required"] is True
    assert card["direct_input"]["confirmation_required"] is True
    assert card["direct_input"]["structured_interpretation_fields"] == [
        "raw_text",
        "normalized_meaning",
        "assumptions",
        "follow_up_checks",
    ]
    assert card["direct_input"]["confirmation_options"] == ["proceed", "edit"]
    for question in card["questions"]:
        assert question["allow_direct_input"] is True
        option_ids = {option["id"] for option in question["options"]}
        assert question["recommended_option_id"] in option_ids
        user_facing_text = [question["prompt"]]
        user_facing_text.extend(option["label"] for option in question["options"])
        for phrase in forbidden:
            assert all(phrase not in text for text in user_facing_text)


def test_blank_intake_answer_selects_recommended_option_and_advances() -> None:
    validator = _load_validator()
    card = validator.load_intake_card(Path("skills/kubernetes-field-assessment"))

    resolved = [
        validator.resolve_intake_answer(card, question, "")
        for question in card["questions"]
    ]

    assert [item["mode"] for item in resolved] == ["selected_option"] * 3
    assert [item["advance"] for item in resolved] == [True, True, True]
    assert [item["option_id"] for item in resolved] == [
        question["recommended_option_id"] for question in card["questions"]
    ]


def test_direct_intake_answer_requires_structured_confirmation() -> None:
    validator = _load_validator()
    card = validator.load_intake_card(Path("skills/kubernetes-field-assessment"))

    resolved = validator.resolve_intake_answer(
        card,
        card["questions"][0],
        "WebLogic에서 도는 오래된 JSP 업무 시스템",
    )

    assert resolved == {
        "mode": "direct_input",
        "advance": False,
        "raw_text": "WebLogic에서 도는 오래된 JSP 업무 시스템",
        "requires_normalization": True,
        "requires_confirmation": True,
        "structured_interpretation_fields": [
            "raw_text",
            "normalized_meaning",
            "assumptions",
            "follow_up_checks",
        ],
        "confirmation_options": ["proceed", "edit"],
    }


def test_validator_reports_non_object_intake_card_without_crashing(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    package = tmp_path / "package"
    _write_manifest(
        package,
        validator.REQUIRED_CANONICAL_FILES,
        validator.REQUIRED_ADAPTER_FILES,
    )
    for relative in validator.REQUIRED_CANONICAL_FILES:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == validator.REQUIRED_INTAKE_CARD_FILE:
            path.write_text("[]", encoding="utf-8")
        else:
            path.write_text(
                "Agent Runtime Skill Package\n"
                "Kubernetes Migration Field Assessment\n"
                "Evidence Result\n"
                "Migration Diagnosis Package\n"
                "Secret masking\n"
                "no-invention\n",
                encoding="utf-8",
            )
    for relative in validator.REQUIRED_ADAPTER_FILES:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "See canonical/. Preserve Evidence Result semantics.\n",
            encoding="utf-8",
        )

    errors = validator.validate_package(package)

    assert "intake card root must be an object" in errors


def _write_manifest(
    package: Path,
    canonical_files: tuple[str, ...],
    adapter_files: tuple[str, ...],
) -> None:
    package.mkdir(parents=True, exist_ok=True)
    lines = ["canonical:"]
    lines.extend(f"  - {relative}" for relative in canonical_files)
    lines.append("adapters:")
    lines.extend(
        f"  adapter_{index}: {relative}"
        for index, relative in enumerate(adapter_files)
    )
    (package / "package.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_intake_card(path: Path) -> None:
    payload = {
        "direct_input": {
            "allowed": True,
            "normalization_required": True,
            "confirmation_required": True,
            "structured_interpretation_fields": [
                "raw_text",
                "normalized_meaning",
                "assumptions",
                "follow_up_checks",
            ],
            "confirmation_options": ["proceed", "edit"],
        },
        "forbidden_user_phrases": [
            "고객이 선정한",
            "customer selected",
            "Runnable Unit",
            "Evidence Result",
        ],
        "questions": [
            {
                "id": "application_shape",
                "prompt": "앱 형태는?",
                "recommended_option_id": "web_api",
                "allow_direct_input": True,
                "options": [{"id": "web_api"}],
            }
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
