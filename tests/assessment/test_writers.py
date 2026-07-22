from __future__ import annotations

import json
from pathlib import Path

from ruamel.yaml import YAML

from repository_assessment.contracts import AssessmentRequest, RunLimits
from repository_assessment.engine import assess
from repository_assessment.recorded import RecordedModelClient
from repository_assessment.repository import LocalRepositoryTools
from repository_assessment.writers import write_artifacts
from tests.assessment.fakes import MemoryEventSink, write_node_repository


RECORDED = Path("tests/fixtures/assessment/recorded/node-basic.json")


def _checked_run(tmp_path: Path):
    repository = write_node_repository(tmp_path / "node-basic")
    return assess(
        AssessmentRequest(
            run_id="writer-test",
            repository=str(repository),
            output_directory=str(tmp_path / "output"),
        ),
        RecordedModelClient.from_file(RECORDED),
        LocalRepositoryTools(repository, RunLimits()),
        MemoryEventSink(),
    )


def test_writers_create_exact_four_files_without_question_or_owner_fields(
    tmp_path: Path,
) -> None:
    paths = write_artifacts(_checked_run(tmp_path), tmp_path / "artifacts")

    assert sorted(path.name for path in (tmp_path / "artifacts").iterdir()) == [
        "assessment-details.json",
        "migration-inputs.yaml",
        "migration-report.md",
        "run-log.json",
    ]
    yaml_text = paths.migration_inputs.read_text(encoding="utf-8")
    payload = YAML(typ="safe").load(yaml_text)
    assert payload["summary"]["run_status"] == "completed_with_gaps"
    assert payload["workloads"]["api"]["network"]["facts"]["listeners"][0][
        "port"
    ] == 3000
    assert "kubernetes_candidates:" in yaml_text
    assert "required_inputs:" in yaml_text
    assert "owner:" not in yaml_text
    assert "question" not in yaml_text
    assert "null" not in yaml_text


def test_details_and_run_log_preserve_checked_audit_data(tmp_path: Path) -> None:
    paths = write_artifacts(_checked_run(tmp_path), tmp_path / "artifacts")

    details = json.loads(paths.assessment_details.read_text(encoding="utf-8"))
    run_log = json.loads(paths.run_log.read_text(encoding="utf-8"))

    assert details["schema_version"] == "assessment-details/v1"
    assert details["checked_topics"][0]["checked_claims"][0]["confidence"][
        "factors"
    ]
    assert details["evidence"][0]["digest"].startswith("sha256:")
    assert run_log["schema_version"] == "assessment-run-log/v1"
    assert run_log["prompt_version"] == "assessment-prompts/v1"
    assert run_log["limits"]["selected_targets"] == 40
    assert run_log["model_responses"][0]["response_digest"] == "sha256:plan-node-basic"
    assert "raw_response" not in paths.run_log.read_text(encoding="utf-8")


def test_markdown_uses_checked_workload_hierarchy_only(tmp_path: Path) -> None:
    paths = write_artifacts(_checked_run(tmp_path), tmp_path / "artifacts")

    markdown = paths.migration_report.read_text(encoding="utf-8")

    assert "# Kubernetes 이관 입력 보고서" in markdown
    assert "## 워크로드: api" in markdown
    assert "### 네트워크" in markdown
    assert "port: 3000" in markdown
    assert "Kubernetes 후보" in markdown
    assert "추가 입력" in markdown
    assert "질문" not in markdown
    assert "담당자" not in markdown


def test_replayed_writes_are_byte_identical(tmp_path: Path) -> None:
    run = _checked_run(tmp_path)
    first = write_artifacts(run, tmp_path / "first")
    second = write_artifacts(run, tmp_path / "second")

    for field in first.__class__.model_fields:
        assert getattr(first, field).read_bytes() == getattr(second, field).read_bytes()
