from __future__ import annotations

import io
from pathlib import Path

from ruamel.yaml import YAML

from integrations import openshell_assessment
from repository_assessment.contracts import RunEvent


def test_openshell_adapter_streams_events_and_never_returns_full_details(
    monkeypatch, tmp_path: Path
) -> None:
    def fake_execute(config, event_sink):
        event_sink.emit(
            RunEvent(
                sequence=1,
                stage="repository_scan",
                kind="completed",
                detail={"entry_count": 3},
            )
        )
        return {
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
        }

    monkeypatch.setattr(openshell_assessment, "execute_assessment", fake_execute)
    output = io.StringIO()

    result = openshell_assessment.run_openshell_assessment(
        openshell_assessment.OpenShellAssessmentRequest(
            run_id="run-1",
            repository_path="/sandbox/repository",
            output_directory="/sandbox/output",
            base_url="https://inference.local/v1",
            model="qwen3-coder",
        ),
        output=output,
    )

    assert '"stage":"repository_scan"' in output.getvalue()
    assert result["schema_version"] == "openshell-assessment-result/v1"
    assert "workloads" not in result
    assert "result" not in result


def test_openshell_policy_is_read_only_for_repository_and_has_no_egress() -> None:
    policy = YAML(typ="safe").load(Path("openshell/policy.yaml").read_text())

    assert policy["version"] == 1
    filesystem = policy["filesystem_policy"]
    assert filesystem["include_workdir"] is False
    assert "/sandbox/repository" in filesystem["read_only"]
    assert filesystem["read_write"] == ["/sandbox/output", "/tmp"]
    assert policy["landlock"]["compatibility"] == "hard_requirement"
    assert policy.get("network_policies", {}) == {}
