from __future__ import annotations

import ast
from pathlib import Path

from repository_assessment.contracts import (
    AnalysisPlan,
    AssessmentRequest,
    Claim,
    PlanTarget,
    RunLimits,
    TopicAnalysisBatch,
    TopicResult,
)
from repository_assessment.engine import assess
from repository_assessment.openai_compatible import ModelUnavailableError
from repository_assessment.recorded import RecordedModelClient
from repository_assessment.repository import LocalRepositoryTools
from tests.assessment.fakes import (
    MemoryEventSink,
    SequenceModelClient,
    SpyRepositoryTools,
    write_node_repository,
)


RECORDED = Path("tests/fixtures/assessment/recorded/node-basic.json")


def test_engine_imports_only_provider_neutral_model_contracts() -> None:
    source = Path("src/repository_assessment/engine.py").read_text(encoding="utf-8")
    imported_modules = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not imported_modules.intersection(
        {"openai_compatible", "recorded", "repository"}
    )


def test_assess_runs_stages_and_reads_only_selected_targets(tmp_path: Path) -> None:
    repository = write_node_repository(tmp_path / "node-basic")
    model = RecordedModelClient.from_file(RECORDED)
    tools = SpyRepositoryTools(LocalRepositoryTools(repository, RunLimits()))
    events = MemoryEventSink()

    run = assess(
        AssessmentRequest(
            run_id="node-test",
            repository=str(repository),
            output_directory=str(tmp_path / "output"),
        ),
        model,
        tools,
        events,
    )

    assert run.status == "completed_with_gaps"
    assert [event.stage for event in events.completed_events] == [
        "repository_scan",
        "analysis_plan",
        "evidence_extraction",
        "topic_analysis",
        "evidence_check",
        "report_building",
    ]
    assert set(path for path, _, _, _ in tools.content_reads) == {
        "package.json",
        "src/server.js",
    }
    assert "README.md" not in {path for path, _, _, _ in tools.content_reads}
    network = run.result.workloads["api"]["network"]
    assert network.facts["listeners"][0]["port"] == 3000
    assert run.limits_used["model_calls"] == 2
    assert len(run.plans) == 1
    assert len(run.checked_topics) == 5


def test_assessment_replay_is_deterministic(tmp_path: Path) -> None:
    repository = write_node_repository(tmp_path / "node-basic")
    request = AssessmentRequest(
        run_id="stable-run",
        repository=str(repository),
        output_directory="ignored-for-run-identity",
    )

    first = assess(
        request,
        RecordedModelClient.from_file(RECORDED),
        LocalRepositoryTools(repository, RunLimits()),
        MemoryEventSink(),
    )
    second = assess(
        request,
        RecordedModelClient.from_file(RECORDED),
        LocalRepositoryTools(repository, RunLimits()),
        MemoryEventSink(),
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_cancelled_run_fails_before_repository_access(tmp_path: Path) -> None:
    repository = write_node_repository(tmp_path / "node-basic")
    tools = SpyRepositoryTools(LocalRepositoryTools(repository, RunLimits()))

    run = assess(
        AssessmentRequest(repository=str(repository), output_directory=str(tmp_path)),
        RecordedModelClient.from_file(RECORDED),
        tools,
        MemoryEventSink(cancelled=True),
    )

    assert run.status == "failed"
    assert run.errors[0]["type"] == "cancelled"
    assert tools.content_reads == []


def test_target_and_model_call_limits_preserve_a_completed_with_gaps_result(
    tmp_path: Path,
) -> None:
    repository = write_node_repository(tmp_path / "node-basic")
    limits = RunLimits(selected_targets=1, model_calls=1)

    run = assess(
        AssessmentRequest(
            repository=str(repository),
            output_directory=str(tmp_path / "output"),
            limits=limits,
        ),
        RecordedModelClient.from_file(RECORDED),
        LocalRepositoryTools(repository, limits),
        MemoryEventSink(),
    )

    assert run.status == "completed_with_gaps"
    assert run.result is not None
    assert {error["type"] for error in run.errors} >= {
        "target_limit_exhausted",
        "model_calls_limit_exhausted",
    }


def test_model_outage_fails_the_full_run_after_scan(tmp_path: Path) -> None:
    repository = write_node_repository(tmp_path / "node-basic")
    model = SequenceModelClient([ModelUnavailableError("offline")])

    run = assess(
        AssessmentRequest(repository=str(repository), output_directory=str(tmp_path)),
        model,
        LocalRepositoryTools(repository, RunLimits()),
        MemoryEventSink(),
    )

    assert run.status == "failed"
    assert run.errors[-1]["type"] == "model_unavailable"
    assert run.scan is not None


def test_second_plan_round_closes_an_explicit_gap(tmp_path: Path) -> None:
    repository = write_node_repository(tmp_path / "node-basic")
    first_plan = AnalysisPlan(
        round=1,
        targets=[
            PlanTarget(
                path="package.json",
                line_start=1,
                line_end=80,
                topics=["application_identity"],
                purpose="Find the package name.",
                method="parse_structured",
                priority="high",
            )
        ],
    )
    first_topics = TopicAnalysisBatch(
        topics=[
            TopicResult(
                topic="networking",
                workload="api",
                status="partial",
                required_inputs={},
            )
        ],
        needs_more_evidence=True,
        gap_topics=["networking"],
    )
    second_plan = AnalysisPlan(
        round=2,
        targets=[
            PlanTarget(
                path="src/server.js",
                line_start=1,
                line_end=120,
                topics=["networking"],
                purpose="Find the listener.",
                method="read_lines",
                priority="high",
            )
        ],
    )
    second_topics = TopicAnalysisBatch(
        topics=[
            TopicResult(
                topic="networking",
                workload="api",
                status="answered",
                claims=[
                    Claim(
                        property_path="listeners",
                        value=[{"port": 3000}],
                        evidence_refs=["E002"],
                    )
                ],
            )
        ]
    )
    model = SequenceModelClient(
        [first_plan, first_topics, second_plan, second_topics]
    )

    run = assess(
        AssessmentRequest(repository=str(repository), output_directory=str(tmp_path)),
        model,
        LocalRepositoryTools(repository, RunLimits()),
        MemoryEventSink(),
    )

    assert len(run.plans) == 2
    assert run.limits_used["model_calls"] == 4
    assert run.result.workloads["api"]["network"].facts["listeners"] == [
        {"port": 3000}
    ]


def test_total_timeout_is_a_full_run_failure(monkeypatch, tmp_path: Path) -> None:
    repository = write_node_repository(tmp_path / "node-basic")
    ticks = iter([0.0, 2.0, 2.0])
    monkeypatch.setattr("repository_assessment.engine.time.monotonic", lambda: next(ticks))

    run = assess(
        AssessmentRequest(
            repository=str(repository),
            output_directory=str(tmp_path),
            limits=RunLimits(total_seconds=1),
        ),
        RecordedModelClient.from_file(RECORDED),
        LocalRepositoryTools(repository, RunLimits(total_seconds=1)),
        MemoryEventSink(),
    )

    assert run.status == "failed"
    assert run.errors[0]["type"] == "total_timeout"
