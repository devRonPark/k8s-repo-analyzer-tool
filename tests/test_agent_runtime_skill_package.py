import importlib.util
import json
from pathlib import Path

import pytest


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
    _write_manifest(
        package,
        validator.REQUIRED_CANONICAL_FILES,
        validator.REQUIRED_ADAPTER_FILES,
    )
    for relative in validator.REQUIRED_CANONICAL_FILES:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_required_canonical_file(path, relative, validator)
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
        _write_required_canonical_file(path, relative, validator)
    for relative in listed_adapters:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "See canonical/. Preserve Evidence Result semantics.\n",
            encoding="utf-8",
        )

    errors = validator.validate_package(package)

    assert any("manifest does not list adapter file" in error for error in errors)


def test_adapters_reference_every_manifest_canonical_file() -> None:
    validator = _load_validator()
    package = Path("skills/kubernetes-field-assessment")
    canonical_files, adapter_files, errors = validator._manifest_paths(package)

    assert errors == []
    for adapter in adapter_files:
        text = (package / adapter).read_text(encoding="utf-8")
        for canonical_file in canonical_files:
            assert canonical_file.replace("canonical/", "../../canonical/") in text


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
        _write_required_canonical_file(
            path,
            relative,
            validator,
            malformed_intake=True,
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


def test_candidate_recommendation_contract_uses_low_cost_scan_and_friendly_choices() -> None:
    validator = _load_validator()

    contract = validator.load_candidate_recommendation(
        Path("skills/kubernetes-field-assessment")
    )

    assert contract["schema_version"] == "application-candidate-recommendation/v1"
    scan_policy = contract["scan_policy"]
    assert scan_policy["stage"] == "cheap_repository_scan"
    assert scan_policy["model_repository_text"] is False
    assert {"path", "file_kind", "source_context"} <= set(
        scan_policy["allowed_inputs"]
    )
    assert "file_contents" not in scan_policy["allowed_inputs"]
    assert {"full_repository_text", "file_contents", "secrets"} <= set(
        scan_policy["forbidden_inputs"]
    )
    assert {"display_name", "evidence_summary", "recommendation_reason"} <= set(
        contract["presentation"]["required_choice_fields"]
    )
    assert {"display_name", "evidence_summary", "recommended"} <= set(
        contract["candidate_fields"]
    )
    selection = contract["selection_behavior"]
    assert selection["enter_selects_recommended"] is True
    assert selection["number_selects_candidate"] is True
    assert selection["multiple_candidates_supported"] is True
    assert selection["direct_input_allowed"] is True
    assert selection["direct_input_requires_normalization"] is True


def test_candidate_recommendation_detects_candidates_from_low_cost_scan_facts() -> None:
    validator = _load_validator()
    contract = validator.load_candidate_recommendation(
        Path("skills/kubernetes-field-assessment")
    )

    candidates = validator.recommend_application_candidates(
        contract,
        [
            {
                "path": "apps/api/pom.xml",
                "file_kind": "build_manifest",
                "source_context": "spring-boot-starter-web",
            },
            {
                "path": "apps/api/Dockerfile",
                "file_kind": "container_manifest",
                "source_context": "EXPOSE 8080",
            },
            {
                "path": "batch/build.gradle",
                "file_kind": "build_manifest",
                "source_context": "spring-boot-starter-batch",
            },
            {
                "path": "batch/jobs/settlement.yaml",
                "file_kind": "scheduler_declaration",
                "source_context": "cron: 0 2 * * *",
            },
        ],
    )

    assert [candidate["id"] for candidate in candidates] == ["apps-api", "batch"]
    assert candidates[0]["display_name"] == "API 웹/API 서버"
    assert candidates[0]["candidate_kind"] == "web_api"
    assert candidates[0]["recommended"] is True
    assert candidates[0]["confidence"] == "high"
    assert "apps/api/pom.xml" in candidates[0]["evidence_summary"]
    assert candidates[1]["display_name"] == "batch 배치"
    assert candidates[1]["recommended"] is False


def test_candidate_recommendation_does_not_mark_low_signal_or_tied_default() -> None:
    validator = _load_validator()
    contract = validator.load_candidate_recommendation(
        Path("skills/kubernetes-field-assessment")
    )

    low_signal = validator.recommend_application_candidates(
        contract,
        [
            {
                "path": "docs/readme.md",
                "file_kind": "documentation",
                "source_context": "project notes",
            }
        ],
    )
    tied = validator.recommend_application_candidates(
        contract,
        [
            {
                "path": "apps/order/pom.xml",
                "file_kind": "build_manifest",
                "source_context": "spring-boot-starter-web",
            },
            {
                "path": "apps/order/Dockerfile",
                "file_kind": "container_manifest",
                "source_context": "EXPOSE 8080",
            },
            {
                "path": "apps/payment/pom.xml",
                "file_kind": "build_manifest",
                "source_context": "spring-boot-starter-web",
            },
            {
                "path": "apps/payment/Dockerfile",
                "file_kind": "container_manifest",
                "source_context": "EXPOSE 8080",
            },
        ],
    )

    assert [candidate["recommended"] for candidate in low_signal] == [False]
    assert [candidate["recommended"] for candidate in tied] == [False, False]


def test_candidate_recommendation_rejects_full_file_content_scan_facts() -> None:
    validator = _load_validator()
    contract = validator.load_candidate_recommendation(
        Path("skills/kubernetes-field-assessment")
    )

    with pytest.raises(ValueError, match="forbidden scan input"):
        validator.recommend_application_candidates(
            contract,
            [
                {
                    "path": "apps/api/pom.xml",
                    "file_kind": "build_manifest",
                    "source_context": "pom metadata",
                    "file_contents": "<project>...</project>",
                }
            ],
        )


def test_blank_candidate_selection_accepts_recommended_candidate() -> None:
    validator = _load_validator()

    resolved = validator.resolve_candidate_selection(_sample_candidates(), "")

    assert resolved == {
        "mode": "selected_candidate",
        "advance": True,
        "candidate_id": "api-server",
        "selection_source": "recommended_default",
    }


def test_number_candidate_selection_selects_requested_candidate() -> None:
    validator = _load_validator()

    resolved = validator.resolve_candidate_selection(_sample_candidates(), "2")

    assert resolved == {
        "mode": "selected_candidate",
        "advance": True,
        "candidate_id": "nightly-batch",
        "selection_source": "numbered_choice",
    }


def test_blank_candidate_selection_requires_marked_recommendation() -> None:
    validator = _load_validator()
    candidates = [
        {**candidate, "recommended": False}
        for candidate in _sample_candidates()
    ]

    with pytest.raises(ValueError, match="exactly one recommended candidate"):
        validator.resolve_candidate_selection(candidates, "")


def test_direct_candidate_input_requires_structured_confirmation() -> None:
    validator = _load_validator()

    resolved = validator.resolve_candidate_selection(
        _sample_candidates(),
        "루트의 legacy-war 모듈",
    )

    assert resolved == {
        "mode": "direct_input",
        "advance": False,
        "raw_text": "루트의 legacy-war 모듈",
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


def test_candidate_choices_render_user_friendly_names_and_evidence_summary() -> None:
    validator = _load_validator()
    contract = validator.load_candidate_recommendation(
        Path("skills/kubernetes-field-assessment")
    )

    choices = validator.render_candidate_choices(contract, _sample_candidates())

    assert choices == [
        {
            "number": 1,
            "candidate_id": "api-server",
            "label": "주문 API 서버",
            "recommended": True,
            "evidence_summary": "apps/api/pom.xml과 Dockerfile이 함께 발견됨",
            "recommendation_reason": "HTTP 진입점과 컨테이너 빌드 파일이 확인됨",
        },
        {
            "number": 2,
            "candidate_id": "nightly-batch",
            "label": "야간 정산 배치",
            "recommended": False,
            "evidence_summary": "batch/build.gradle과 cron 표현식이 발견됨",
            "recommendation_reason": "스케줄 실행 흔적이 있어 별도 Job 후보임",
        },
    ]


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


def _write_required_canonical_file(
    path: Path,
    relative: str,
    validator,
    *,
    malformed_intake: bool = False,
) -> None:
    if relative == validator.REQUIRED_INTAKE_CARD_FILE:
        if malformed_intake:
            path.write_text("[]", encoding="utf-8")
        else:
            _write_intake_card(path)
    elif relative == validator.REQUIRED_CANDIDATE_RECOMMENDATION_FILE:
        _write_candidate_recommendation(path, validator)
    else:
        _write_required_terms_doc(path)


def _write_required_terms_doc(path: Path) -> None:
    path.write_text(
        "Agent Runtime Skill Package\n"
        "Kubernetes Migration Field Assessment\n"
        "Evidence Result\n"
        "Migration Diagnosis Package\n"
        "Secret masking\n"
        "no-invention\n",
        encoding="utf-8",
    )


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


def _write_candidate_recommendation(path: Path, validator) -> None:
    payload = {
        "schema_version": "application-candidate-recommendation/v1",
        "scan_policy": {
            "stage": "cheap_repository_scan",
            "model_repository_text": False,
            "allowed_inputs": list(validator.REQUIRED_SCAN_ALLOWED_INPUTS),
            "forbidden_inputs": list(validator.REQUIRED_SCAN_FORBIDDEN_INPUTS),
        },
        "candidate_fields": list(validator.REQUIRED_CANDIDATE_FIELDS),
        "presentation": {
            "required_choice_fields": list(
                validator.REQUIRED_CANDIDATE_CHOICE_FIELDS
            )
        },
        "selection_behavior": {
            flag: True
            for flag in validator.REQUIRED_CANDIDATE_SELECTION_FLAGS
        },
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _sample_candidates() -> list[dict[str, object]]:
    return [
        {
            "id": "api-server",
            "display_name": "주문 API 서버",
            "candidate_kind": "web_api",
            "source_paths": ["apps/api/pom.xml", "apps/api/Dockerfile"],
            "evidence_summary": "apps/api/pom.xml과 Dockerfile이 함께 발견됨",
            "recommendation_reason": "HTTP 진입점과 컨테이너 빌드 파일이 확인됨",
            "confidence": "high",
            "recommended": True,
        },
        {
            "id": "nightly-batch",
            "display_name": "야간 정산 배치",
            "candidate_kind": "batch",
            "source_paths": ["batch/build.gradle", "batch/jobs/settlement.yaml"],
            "evidence_summary": "batch/build.gradle과 cron 표현식이 발견됨",
            "recommendation_reason": "스케줄 실행 흔적이 있어 별도 Job 후보임",
            "confidence": "medium",
            "recommended": False,
        },
    ]
