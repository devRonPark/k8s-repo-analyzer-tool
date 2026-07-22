from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from repository_assessment.contracts import (
    AnalysisPlan,
    ArtifactPaths,
    AssessmentRequest,
    PlanTarget,
    RunLimits,
    SearchTarget,
    TopicResult,
)


def test_run_limits_match_v1_defaults() -> None:
    limits = RunLimits()

    assert limits.model_dump() == {
        "tree_entries": 20_000,
        "selected_targets": 40,
        "single_file_bytes": 512 * 1024,
        "lines_per_read": 200,
        "search_calls": 20,
        "matches_per_search": 100,
        "plan_rounds": 2,
        "model_calls": 10,
        "schema_repairs": 1,
        "total_seconds": 300,
    }


def test_plan_accepts_bounded_reads_and_searches() -> None:
    target = PlanTarget(
        path="package.json",
        line_start=1,
        line_end=160,
        topics=["build_profile", "runtime_profile"],
        purpose="Find build and start scripts.",
        method="parse_structured",
        priority="high",
    )
    search = SearchTarget(
        pattern="listen(",
        paths=["src"],
        topics=["networking"],
        purpose="Find runtime listeners.",
        priority="medium",
    )

    plan = AnalysisPlan(round=1, targets=[target], searches=[search])

    assert plan.targets == [target]
    assert plan.searches == [search]


def test_topic_contract_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        TopicResult(topic="build_profile", workload="app", status="not_detected")


def test_request_rejects_credential_bearing_repository_urls(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="credentials"):
        AssessmentRequest(
            repository="https://token@github.com/acme/app.git",
            output_directory=str(tmp_path),
        )


def test_contracts_are_frozen_and_reject_unknown_fields(tmp_path: Path) -> None:
    request = AssessmentRequest(repository=".", output_directory=str(tmp_path))

    with pytest.raises(ValidationError):
        request.repository = "elsewhere"
    with pytest.raises(ValidationError):
        AssessmentRequest(
            repository=".", output_directory=str(tmp_path), unknown_setting=True
        )


def test_artifact_paths_serialize_as_json_strings(tmp_path: Path) -> None:
    paths = ArtifactPaths(
        migration_inputs=tmp_path / "migration-inputs.yaml",
        migration_report=tmp_path / "migration-report.md",
        assessment_details=tmp_path / "assessment-details.json",
        run_log=tmp_path / "run-log.json",
    )

    dumped = paths.model_dump(mode="json")

    assert dumped["migration_inputs"].endswith("migration-inputs.yaml")
