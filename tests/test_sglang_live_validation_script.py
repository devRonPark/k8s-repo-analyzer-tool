import importlib.util
import json
from pathlib import Path


def _load_script():
    path = Path("scripts/validate_sglang_live_repos.py")
    spec = importlib.util.spec_from_file_location("validate_sglang_live_repos", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_result_from_transcript_preserves_final_answer_body():
    module = _load_script()
    transcript = [
        {"stage": "request", "content": "question"},
        {
            "stage": "tool_output",
            "summary": {
                "ok": True,
                "question_statuses": {"application_identity": "answered"},
                "warnings": ["warning_code"],
            },
        },
        {"stage": "final_answer", "content": "model response body"},
    ]

    result = module.result_from_transcript("owner/repo", transcript, elapsed_seconds=1.23)

    assert result["ok"] is True
    assert result["tool_ok"] is True
    assert result["final_answer"] == "model response body"
    assert result["final_answer_chars"] == len("model response body")
    assert result["question_statuses"] == {"application_identity": "answered"}
    assert result["warnings"] == ["warning_code"]


def test_run_validation_writes_final_answer_to_output(tmp_path):
    module = _load_script()
    output = tmp_path / "live-results.json"
    workdir = tmp_path / "repos"
    (workdir / "owner__repo").mkdir(parents=True)

    def fake_runner(**kwargs):
        return [
            {
                "stage": "tool_output",
                "summary": {
                    "ok": True,
                    "question_statuses": {"build_and_run": "answered"},
                    "warnings": [],
                },
            },
            {"stage": "final_answer", "content": "full final answer"},
        ]

    exit_code = module.run_validation(
        repositories=["owner/repo"],
        workdir=workdir,
        output=output,
        base_url="http://sglang:30000/v1",
        model="qwen",
        api_key="dummy",
        question="question",
        runner=fake_runner,
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == [
        {
            "repo": "owner/repo",
            "ok": True,
            "tool_ok": True,
            "question_statuses": {"build_and_run": "answered"},
            "warnings": [],
            "final_answer": "full final answer",
            "final_answer_chars": len("full final answer"),
            "elapsed_seconds": payload[0]["elapsed_seconds"],
        }
    ]
