"""CLI composition root for repository assessment."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence, TextIO

from .contracts import AssessmentRequest, RunEvent, RunLimits
from .engine import assess
from .openai_compatible import OpenAICompatibleModelClient
from .recorded import RecordedModelClient
from .repository import LocalRepositoryTools
from .writers import write_artifacts


@dataclass(frozen=True)
class RuntimeConfig:
    repository: str
    output_directory: str
    run_id: str | None
    revision: str | None
    base_url: str | None
    model: str | None
    api_key: str | None
    recorded_responses: str | None
    timeout_seconds: float
    limits: RunLimits


class JsonLineEventSink:
    def __init__(
        self,
        output: TextIO,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self._output = output
        self._cancelled = cancelled or (lambda: False)

    def emit(self, event: RunEvent) -> None:
        self._output.write(
            json.dumps(
                event.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        self._output.flush()

    def is_cancelled(self) -> bool:
        return self._cancelled()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repository-assessment",
        description="Run a bounded, evidence-checked Kubernetes migration assessment.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    assess_parser = commands.add_parser("assess", help="assess a sandbox-visible repository")
    assess_parser.add_argument("--repo", required=True)
    assess_parser.add_argument("--output-dir", required=True)
    assess_parser.add_argument("--run-id", default=None)
    assess_parser.add_argument("--revision", default=None)
    assess_parser.add_argument("--base-url", default=None)
    assess_parser.add_argument("--model", default=None)
    assess_parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    assess_parser.add_argument("--recorded-responses", default=None)
    assess_parser.add_argument("--timeout-seconds", type=float, default=60)
    assess_parser.add_argument("--tree-entries", type=int, default=None)
    assess_parser.add_argument("--selected-targets", type=int, default=None)
    assess_parser.add_argument("--single-file-bytes", type=int, default=None)
    assess_parser.add_argument("--lines-per-read", type=int, default=None)
    assess_parser.add_argument("--search-calls", type=int, default=None)
    assess_parser.add_argument("--matches-per-search", type=int, default=None)
    assess_parser.add_argument("--plan-rounds", type=int, default=None)
    assess_parser.add_argument("--model-calls", type=int, default=None)
    assess_parser.add_argument("--schema-repairs", type=int, default=None)
    assess_parser.add_argument("--total-seconds", type=int, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    validation_error = _configuration_error(args)
    if validation_error:
        print(f"error: {validation_error}", file=sys.stderr)
        return 2
    try:
        payload = compose_and_run(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return {"completed": 0, "completed_with_gaps": 1, "failed": 3}[
        payload["run_status"]
    ]


def compose_and_run(args: argparse.Namespace) -> dict:
    limits = _limits_from_args(args)
    config = RuntimeConfig(
        repository=args.repo,
        output_directory=args.output_dir,
        run_id=args.run_id,
        revision=args.revision,
        base_url=args.base_url,
        model=args.model,
        api_key=os.environ.get(args.api_key_env),
        recorded_responses=args.recorded_responses,
        timeout_seconds=args.timeout_seconds,
        limits=limits,
    )
    return execute_assessment(config, JsonLineEventSink(sys.stderr))


def execute_assessment(config: RuntimeConfig, event_sink: JsonLineEventSink) -> dict:
    model_client = (
        RecordedModelClient.from_file(config.recorded_responses)
        if config.recorded_responses
        else OpenAICompatibleModelClient(
            base_url=config.base_url or "",
            model=config.model or "",
            api_key=config.api_key,
            timeout_seconds=config.timeout_seconds,
            schema_repairs=config.limits.schema_repairs,
        )
    )
    repository_tools = LocalRepositoryTools(
        config.repository, config.limits, revision=config.revision
    )
    run = assess(
        AssessmentRequest(
            run_id=config.run_id,
            repository=config.repository,
            revision=config.revision,
            output_directory=config.output_directory,
            limits=config.limits,
        ),
        model_client,
        repository_tools,
        event_sink,
    )
    artifact_payload: dict[str, str] = {}
    if run.result is not None:
        artifact_payload = write_artifacts(
            run, Path(config.output_directory)
        ).model_dump(mode="json")
    return {
        "run_id": run.run_id,
        "run_status": run.status,
        "workload_count": len(run.result.workloads) if run.result else 0,
        "gap_count": count_gaps(run),
        "artifacts": artifact_payload,
    }


def count_gaps(run) -> int:
    topic_gaps = sum(1 for item in run.checked_topics if item.status != "answered")
    return topic_gaps + len(run.errors)


def _configuration_error(args: argparse.Namespace) -> str | None:
    if args.recorded_responses and (args.base_url or args.model):
        return "--recorded-responses cannot be combined with --base-url or --model"
    if not args.recorded_responses and (not args.base_url or not args.model):
        return "live mode requires both --base-url and --model"
    return None


def _limits_from_args(args: argparse.Namespace) -> RunLimits:
    defaults = RunLimits().model_dump()
    for field in defaults:
        value = getattr(args, field, None)
        if value is not None:
            defaults[field] = value
    return RunLimits(**defaults)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
