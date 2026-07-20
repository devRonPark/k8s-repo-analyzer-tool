"""Run live SGLang tool-call validation for the required Java repositories."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from time import monotonic
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from scripts import llm_tool_call_demo as live_demo  # noqa: E402
from scripts.validate_external_repos import REQUIRED_REPOSITORIES  # noqa: E402

DEFAULT_QUESTION = (
    "Summarize this Java repository for a Kubernetes migration review using the "
    "seven migration questions. Do not infer values that are absent from the "
    "tool output."
)
DEFAULT_WORKDIR = "/tmp/repo-analyzer-validation"
DEFAULT_OUTPUT = "/tmp/required-java-repos-sglang-live-validation.json"

TranscriptRunner = Callable[..., list[dict[str, Any]]]


def result_from_transcript(
    repo: str,
    transcript: list[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Convert one live transcript into a persisted validation row."""

    tool_summary = _first_stage_value(transcript, "tool_output", "summary") or {}
    final_answer = _first_stage_value(transcript, "final_answer", "content") or ""
    return {
        "repo": repo,
        "ok": bool(tool_summary.get("ok")) and bool(final_answer),
        "tool_ok": tool_summary.get("ok"),
        "question_statuses": tool_summary.get("question_statuses"),
        "warnings": tool_summary.get("warnings"),
        "final_answer": final_answer,
        "final_answer_chars": len(final_answer),
        "elapsed_seconds": round(elapsed_seconds, 2),
    }


def run_validation(
    repositories: list[str],
    workdir: Path,
    output: Path,
    base_url: str,
    model: str,
    api_key: str | None,
    question: str,
    runner: TranscriptRunner = live_demo.run_live_transcript,
    build_system: str = "auto",
) -> int:
    """Run live validation and write JSON results, including final answers."""

    results: list[dict[str, Any]] = []
    failures = 0
    for repo in repositories:
        repo_dir = workdir / repo.replace("/", "__")
        started = monotonic()
        print(f"RUN {repo} {repo_dir}", flush=True)
        try:
            transcript = runner(
                repository_path=str(repo_dir),
                question=question,
                build_system=build_system,
                git_ref=None,
                model=model,
                base_url=base_url,
                api_key=api_key,
            )
            result = result_from_transcript(repo, transcript, monotonic() - started)
        except Exception as exc:
            result = {
                "repo": repo,
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
                "final_answer": "",
                "final_answer_chars": 0,
                "elapsed_seconds": round(monotonic() - started, 2),
            }
        if not result.get("ok"):
            failures += 1
        results.append(result)
        print(_progress_line(result), flush=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote={output}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default=DEFAULT_WORKDIR)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--env-file", default=str(_ROOT / ".env"))
    parser.add_argument("--repo", action="append", dest="repositories")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--use-process-env", action="store_true")
    args = parser.parse_args(argv)

    environ = dict(os.environ) if args.use_process_env else {}
    settings = live_demo.resolve_openai_settings(
        env_file=Path(args.env_file),
        environ=environ,
        cli_model=args.model,
        cli_base_url=args.base_url,
    )
    base_url = settings["base_url"]
    model = settings["model"]
    if not base_url or not model:
        print("error: OPENAI_BASE_URL and OPENAI_MODEL are required", file=sys.stderr)
        return 2

    print(f"base_url={base_url}")
    print(f"model={model}")
    return run_validation(
        repositories=args.repositories or REQUIRED_REPOSITORIES,
        workdir=Path(args.workdir),
        output=Path(args.output),
        base_url=base_url,
        model=model,
        api_key=settings["api_key"],
        question=args.question,
    )


def _first_stage_value(
    transcript: list[dict[str, Any]],
    stage: str,
    key: str,
) -> Any:
    for item in transcript:
        if item.get("stage") == stage:
            return item.get(key)
    return None


def _progress_line(result: dict[str, Any]) -> str:
    status = "PASS" if result.get("ok") else "FAIL"
    compact = {
        key: value
        for key, value in result.items()
        if key not in {"final_answer"}
    }
    return f"{status} {json.dumps(compact, ensure_ascii=False)}"


if __name__ == "__main__":
    raise SystemExit(main())
