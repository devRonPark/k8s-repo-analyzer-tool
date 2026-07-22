from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from repository_assessment.contracts import AssessmentRequest, RunLimits
from repository_assessment.engine import assess
from repository_assessment.recorded import RecordedModelClient
from repository_assessment.repository import LocalRepositoryTools
from tests.assessment.fakes import MemoryEventSink


FIXTURES = Path("tests/fixtures/assessment")


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _assert_generic_node(run) -> None:
    identity = run.result.workloads["api"]["identity"].facts
    assert identity["language"] == "javascript"
    assert identity["runtime"] == "nodejs"
    assert run.result.workloads["api"]["network"].facts["listeners"][0]["port"] == 3000


def _assert_docker_free_java(run) -> None:
    workload = run.result.workloads["legacy-web"]
    assert workload["identity"].facts["language"] == "java"
    assert workload["build_and_image"].facts["tool"] == "maven"
    assert workload["build_and_image"].facts["artifact"]["type"] == "war"


def _assert_script_runtime(run) -> None:
    runtime = run.result.workloads["batch"]["runtime_and_lifecycle"].facts
    assert runtime["command"] == ["/opt/app/run.sh"]
    assert runtime["working_directory"] == "/opt/app"


def _assert_two_workloads(run) -> None:
    assert set(run.result.workloads) == {"api", "worker"}


def _assert_runtime_wins(run) -> None:
    assert run.result.workloads["app"]["network"].facts["port"] == 9090
    assert run.result.conflicts[0].candidates == [8080, 9090]


def _assert_required_inputs_without_secret_values(run) -> None:
    serialized = run.model_dump_json()
    assert "super-secret" not in serialized
    assert "app.configuration.database.endpoint" in run.result.required_inputs


def _assert_topic_not_repository_unsupported(run) -> None:
    workload = run.result.workloads["unknown-app"]
    assert workload["identity"].status == "answered"
    assert workload["configuration"].status == "unsupported"
    assert run.status == "completed_with_gaps"


def _assert_primary_context(run) -> None:
    configuration = run.result.workloads["app"]["configuration"]
    assert configuration.facts["mode"] == "production"
    assert all(claim.value != "test" for claim in configuration.checked_claims)


@pytest.mark.parametrize(
    ("fixture", "assertion"),
    [
        ("node-basic", _assert_generic_node),
        ("java-no-container", _assert_docker_free_java),
        ("script-only", _assert_script_runtime),
        ("monorepo", _assert_two_workloads),
        ("readme-conflict", _assert_runtime_wins),
        ("no-production-secrets", _assert_required_inputs_without_secret_values),
        ("unsupported-format", _assert_topic_not_repository_unsupported),
        ("source-context-conflict", _assert_primary_context),
    ],
)
def test_required_scenario(fixture: str, assertion, tmp_path: Path) -> None:
    repository = FIXTURES / fixture
    before = _tree_digest(repository)
    model = RecordedModelClient.from_file(FIXTURES / "recorded" / f"{fixture}.json")

    run = assess(
        AssessmentRequest(
            run_id=f"scenario-{fixture}",
            repository=str(repository),
            output_directory=str(tmp_path / fixture),
        ),
        model,
        LocalRepositoryTools(repository, RunLimits()),
        MemoryEventSink(),
    )

    assertion(run)
    assert _tree_digest(repository) == before
