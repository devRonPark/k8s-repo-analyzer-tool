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


def test_confirmed_scope_contract_defines_evidence_result_boundaries() -> None:
    validator = _load_validator()

    contract = validator.load_confirmed_scope_evidence_result(
        Path("skills/kubernetes-field-assessment")
    )

    assert contract["schema_version"] == "confirmed-scope-evidence-result/v1"
    request_contract = contract["evidence_core_request"]
    assert request_contract["operation"] == "run_evidence_core"
    assert {
        "target_candidate_id",
        "repository_root",
        "source_path_filters",
        "analysis_topics",
    } <= set(request_contract["required_fields"])
    assert request_contract["result_policy"] == {
        "keep_user_context_separate": True,
        "mask_secrets": True,
        "no_invention": True,
        "report_conflicts": True,
    }
    result_contract = contract["evidence_result"]
    assert {
        "scope",
        "source_confirmed_facts",
        "user_input_context",
        "required_inputs",
        "conflicts",
        "secret_masking_events",
        "no_invention_rules",
    } <= set(result_contract["required_sections"])


def test_evidence_core_request_reflects_confirmed_target_and_scope() -> None:
    validator = _load_validator()
    contract = validator.load_confirmed_scope_evidence_result(
        Path("skills/kubernetes-field-assessment")
    )

    request = validator.build_evidence_core_request(
        contract,
        {
            "target_candidate_id": "api-server",
            "repository_root": ".",
            "confirmed_scope": {
                "include_paths": ["apps/api"],
                "exclude_paths": ["batch"],
                "analysis_topics": ["build", "runtime", "networking"],
            },
            "user_input_context": [
                {
                    "id": "ctx-1",
                    "property": "current_runtime",
                    "value": "Tomcat",
                    "raw_text": "현재 Tomcat에서 실행",
                }
            ],
        },
    )

    assert request == {
        "operation": "run_evidence_core",
        "target_candidate_id": "api-server",
        "repository_root": ".",
        "source_path_filters": {
            "include_paths": ["apps/api"],
            "exclude_paths": ["batch"],
        },
        "analysis_topics": ["build", "runtime", "networking"],
        "user_input_context": [
            {
                "id": "ctx-1",
                "property": "current_runtime",
                "value": "Tomcat",
                "raw_text": "현재 Tomcat에서 실행",
            }
        ],
        "result_policy": {
            "keep_user_context_separate": True,
            "mask_secrets": True,
            "no_invention": True,
            "report_conflicts": True,
        },
    }


def test_confirmed_scope_run_returns_evidence_core_request_and_evidence_result() -> None:
    validator = _load_validator()
    contract = validator.load_confirmed_scope_evidence_result(
        Path("skills/kubernetes-field-assessment")
    )

    evidence_core_requests = []

    def evidence_core(request):
        evidence_core_requests.append(request)
        return {
            "source_facts": [
                {
                    "id": "src-1",
                    "property": "container_port",
                    "value": 8080,
                    "evidence_ref": "apps/api/Dockerfile:12",
                }
            ],
            "repository_unknowns": [],
        }

    run = validator.run_confirmed_scope_evidence_core(
        contract,
        {
            "target_candidate_id": "api-server",
            "repository_root": ".",
            "confirmed_scope": {
                "include_paths": ["apps/api"],
                "exclude_paths": [],
                "analysis_topics": ["runtime"],
            },
            "user_input_context": [
                {
                    "id": "ctx-1",
                    "property": "current_runtime",
                    "value": "Tomcat",
                    "raw_text": "현재 Tomcat에서 실행",
                }
            ],
        },
        evidence_core=evidence_core,
    )

    assert evidence_core_requests == [run["evidence_core_request"]]
    assert run["evidence_core_request"]["operation"] == "run_evidence_core"
    assert run["evidence_core_request"]["target_candidate_id"] == "api-server"
    assert run["evidence_result"]["scope"]["target_candidate_id"] == "api-server"
    assert run["evidence_result"]["user_input_context"] == [
        {
            "id": "ctx-1",
            "property": "current_runtime",
            "value": "Tomcat",
            "raw_text": "현재 Tomcat에서 실행",
            "origin": "user_input",
        }
    ]
    assert run["evidence_result"]["source_confirmed_facts"][0]["origin"] == (
        "repository_source"
    )


def test_evidence_result_separates_source_facts_masks_secrets_and_reports_conflicts() -> None:
    validator = _load_validator()
    contract = validator.load_confirmed_scope_evidence_result(
        Path("skills/kubernetes-field-assessment")
    )
    request = validator.build_evidence_core_request(
        contract,
        {
            "target_candidate_id": "api-server",
            "repository_root": ".",
            "confirmed_scope": {
                "include_paths": ["apps/api"],
                "exclude_paths": [],
                "analysis_topics": ["runtime", "networking"],
            },
            "user_input_context": [],
        },
    )

    result = validator.build_evidence_result(
        contract,
        request,
        source_facts=[
            {
                "id": "src-1",
                "property": "container_port",
                "value": 8080,
                "evidence_ref": "apps/api/Dockerfile:12",
            },
            {
                "id": "src-2",
                "property": "database_password",
                "value": "prod-password",
                "evidence_ref": "apps/api/application.yaml:9",
            },
        ],
        user_context=[
            {
                "id": "ctx-1",
                "property": "container_port",
                "value": 8081,
                "raw_text": "운영 포트는 8081로 들었습니다",
            }
        ],
    )

    assert result["scope"]["target_candidate_id"] == "api-server"
    assert result["source_confirmed_facts"] == [
        {
            "id": "src-1",
            "property": "container_port",
            "value": 8080,
            "evidence_ref": "apps/api/Dockerfile:12",
            "origin": "repository_source",
        },
        {
            "id": "src-2",
            "property": "database_password",
            "value": "[MASKED_SECRET]",
            "evidence_ref": "apps/api/application.yaml:9",
            "origin": "repository_source",
        },
    ]
    assert result["user_input_context"] == [
        {
            "id": "ctx-1",
            "property": "container_port",
            "value": 8081,
            "raw_text": "운영 포트는 8081로 들었습니다",
            "origin": "user_input",
        }
    ]
    assert result["secret_masking_events"] == [
        {
            "section": "source_confirmed_facts",
            "id": "src-2",
            "property": "database_password",
            "masked_value": "[MASKED_SECRET]",
        }
    ]
    assert result["conflicts"] == [
        {
            "property": "container_port",
            "source_fact_id": "src-1",
            "user_context_id": "ctx-1",
            "source_value": 8080,
            "user_value": 8081,
            "resolution_required": True,
        }
    ]


def test_evidence_result_masks_secret_like_values_even_when_property_is_generic() -> None:
    validator = _load_validator()
    contract = validator.load_confirmed_scope_evidence_result(
        Path("skills/kubernetes-field-assessment")
    )
    request = validator.build_evidence_core_request(
        contract,
        {
            "target_candidate_id": "api-server",
            "repository_root": ".",
            "confirmed_scope": {
                "include_paths": ["apps/api"],
                "exclude_paths": [],
                "analysis_topics": ["runtime"],
            },
            "user_input_context": [],
        },
    )

    result = validator.build_evidence_result(
        contract,
        request,
        source_facts=[
            {
                "id": "src-1",
                "property": "database_url",
                "value": "postgres://user:password@db/prod",
                "evidence_ref": "apps/api/application.yaml:13",
            }
        ],
        user_context=[],
    )

    assert result["source_confirmed_facts"][0]["value"] == "[MASKED_SECRET]"
    assert result["secret_masking_events"] == [
        {
            "section": "source_confirmed_facts",
            "id": "src-1",
            "property": "database_url",
            "masked_value": "[MASKED_SECRET]",
        }
    ]


def test_evidence_result_reports_secret_conflict_without_revealing_values() -> None:
    validator = _load_validator()
    contract = validator.load_confirmed_scope_evidence_result(
        Path("skills/kubernetes-field-assessment")
    )
    request = validator.build_evidence_core_request(
        contract,
        {
            "target_candidate_id": "api-server",
            "repository_root": ".",
            "confirmed_scope": {
                "include_paths": ["apps/api"],
                "exclude_paths": [],
                "analysis_topics": ["runtime"],
            },
            "user_input_context": [],
        },
    )

    result = validator.build_evidence_result(
        contract,
        request,
        source_facts=[
            {
                "id": "src-1",
                "property": "database_password",
                "value": "repo-password",
                "evidence_ref": "apps/api/application.yaml:9",
            }
        ],
        user_context=[
            {
                "id": "ctx-1",
                "property": "database_password",
                "value": "interview-password",
                "raw_text": "운영 DB 비밀번호는 별도로 들었습니다",
            }
        ],
    )

    assert result["conflicts"] == [
        {
            "property": "database_password",
            "source_fact_id": "src-1",
            "user_context_id": "ctx-1",
            "source_value": "[MASKED_SECRET]",
            "user_value": "[MASKED_SECRET]",
            "resolution_required": True,
        }
    ]


def test_evidence_result_masks_secret_like_user_raw_text() -> None:
    validator = _load_validator()
    contract = validator.load_confirmed_scope_evidence_result(
        Path("skills/kubernetes-field-assessment")
    )
    request = validator.build_evidence_core_request(
        contract,
        {
            "target_candidate_id": "api-server",
            "repository_root": ".",
            "confirmed_scope": {
                "include_paths": ["apps/api"],
                "exclude_paths": [],
                "analysis_topics": ["runtime"],
            },
            "user_input_context": [],
        },
    )

    result = validator.build_evidence_result(
        contract,
        request,
        source_facts=[],
        user_context=[
            {
                "id": "ctx-1",
                "property": "database_note",
                "value": "provided separately",
                "raw_text": "password is interview-password",
            }
        ],
    )

    assert result["user_input_context"] == [
        {
            "id": "ctx-1",
            "property": "database_note",
            "value": "provided separately",
            "raw_text": "[MASKED_SECRET]",
            "origin": "user_input",
        }
    ]
    assert result["secret_masking_events"] == [
        {
            "section": "user_input_context",
            "id": "ctx-1",
            "property": "raw_text",
            "masked_value": "[MASKED_SECRET]",
        }
    ]


def test_evidence_result_keeps_repository_unknowns_as_required_inputs_without_invention() -> None:
    validator = _load_validator()
    contract = validator.load_confirmed_scope_evidence_result(
        Path("skills/kubernetes-field-assessment")
    )
    request = validator.build_evidence_core_request(
        contract,
        {
            "target_candidate_id": "api-server",
            "repository_root": ".",
            "confirmed_scope": {
                "include_paths": ["apps/api"],
                "exclude_paths": [],
                "analysis_topics": ["runtime"],
            },
            "user_input_context": [],
        },
    )

    result = validator.build_evidence_result(
        contract,
        request,
        source_facts=[],
        user_context=[],
        repository_unknowns=[
            {
                "id": "startup_probe_path",
                "needed_for": "probe design",
                "reason": "repository_cannot_determine",
            }
        ],
    )

    required_input_ids = {item["id"] for item in result["required_inputs"]}
    assert {
        "replicas",
        "resource_requests",
        "ingress_host",
        "storage_class",
        "production_secret_values",
        "startup_probe_path",
    } <= required_input_ids
    assert all(item["value"] is None for item in result["required_inputs"])
    assert result["no_invention_rules"] == [
        "replicas",
        "resource_requests",
        "ingress_host",
        "storage_class",
        "production_secret_values",
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
    elif relative == validator.REQUIRED_CONFIRMED_SCOPE_EVIDENCE_RESULT_FILE:
        _write_confirmed_scope_evidence_result(path, validator)
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


def _write_confirmed_scope_evidence_result(path: Path, validator) -> None:
    payload = {
        "schema_version": "confirmed-scope-evidence-result/v1",
        "evidence_core_request": {
            "operation": "run_evidence_core",
            "required_fields": list(
                validator.REQUIRED_EVIDENCE_CORE_REQUEST_FIELDS
            ),
            "result_policy": dict(validator.REQUIRED_EVIDENCE_RESULT_POLICY),
        },
        "evidence_result": {
            "required_sections": list(validator.REQUIRED_EVIDENCE_RESULT_SECTIONS)
        },
        "no_invention_required_inputs": [
            {"id": item_id, "needed_for": "migration decision"}
            for item_id in validator.REQUIRED_NO_INVENTION_INPUTS
        ],
        "secret_masking": {
            "masked_value": validator.MASKED_SECRET_VALUE,
            "property_patterns": list(validator.SECRET_PROPERTY_PATTERNS),
            "value_patterns": list(validator.SECRET_VALUE_PATTERNS),
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
