from __future__ import annotations

import json
from pathlib import Path

from repository_assessment import cli


def test_cli_emits_compact_json_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "compose_and_run",
        lambda args: {
            "run_id": "run-1",
            "run_status": "completed_with_gaps",
            "workload_count": 1,
            "gap_count": 2,
            "artifacts": {
                "migration_inputs": str(tmp_path / "migration-inputs.yaml"),
                "migration_report": str(tmp_path / "migration-report.md"),
                "assessment_details": str(tmp_path / "assessment-details.json"),
                "run_log": str(tmp_path / "run-log.json"),
            },
        },
    )

    exit_code = cli.main(
        [
            "assess",
            "--repo",
            "tests/fixtures/assessment/node-basic",
            "--output-dir",
            str(tmp_path),
            "--base-url",
            "https://inference.local/v1",
            "--model",
            "qwen3-coder",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["run_status"] == "completed_with_gaps"
    assert set(payload["artifacts"]) == {
        "migration_inputs",
        "migration_report",
        "assessment_details",
        "run_log",
    }
    assert "result" not in payload


def test_cli_rejects_mixed_live_and_recorded_model_configuration(
    tmp_path: Path, capsys
) -> None:
    exit_code = cli.main(
        [
            "assess",
            "--repo",
            ".",
            "--output-dir",
            str(tmp_path),
            "--base-url",
            "http://model/v1",
            "--model",
            "model",
            "--recorded-responses",
            "responses.json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "cannot be combined" in captured.err


def test_cli_keeps_legacy_repo_analyzer_entry_point_in_project_metadata() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'repo-analyzer = "repo_analyzer.cli:main"' in pyproject
    assert 'repository-assessment = "repository_assessment.cli:main"' in pyproject
