from __future__ import annotations

from pathlib import Path

from repository_assessment.contracts import Claim, RequiredInput, RunLimits, TopicResult
from repository_assessment.evidence import check_topics
from repository_assessment.repository import LocalRepositoryTools


def test_primary_runtime_conflict_is_preserved_as_contradicted(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text('CMD ["node", "a.js"]\n', encoding="utf-8")
    (tmp_path / "compose.yml").write_text(
        'command: ["node", "b.js"]\n', encoding="utf-8"
    )
    tools = LocalRepositoryTools(tmp_path, RunLimits())
    first = tools.read_lines("Dockerfile", 1, 1).evidence[0]
    second = tools.read_lines("compose.yml", 1, 1).evidence[0]
    topic = TopicResult(
        topic="entrypoint",
        workload="app",
        status="answered",
        claims=[
            Claim(
                property_path="command",
                value=["node", "a.js"],
                evidence_refs=[first.id],
            ),
            Claim(
                property_path="command",
                value=["node", "b.js"],
                evidence_refs=[second.id],
            ),
        ],
    )

    result = check_topics([topic], [first, second], tools)

    assert result.topics[0].status == "contradicted"
    assert result.conflicts[0].candidates == [
        ["node", "a.js"],
        ["node", "b.js"],
    ]


def test_readme_cannot_override_primary_runtime_value(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("PORT=8080\n", encoding="utf-8")
    (tmp_path / "runtime.properties").write_text("PORT=9090\n", encoding="utf-8")
    tools = LocalRepositoryTools(tmp_path, RunLimits())
    readme = tools.read_lines("README.md", 1, 1).evidence[0]
    runtime = tools.read_lines("runtime.properties", 1, 1).evidence[0]
    topic = TopicResult(
        topic="networking",
        workload="app",
        status="answered",
        claims=[
            Claim(property_path="port", value=8080, evidence_refs=[readme.id]),
            Claim(property_path="port", value=9090, evidence_refs=[runtime.id]),
        ],
    )

    result = check_topics([topic], [readme, runtime], tools)

    checked = result.topics[0]
    assert checked.status == "answered"
    assert checked.facts["port"] == 9090
    assert result.conflicts[0].candidates == [8080, 9090]


def test_changed_digest_and_missing_evidence_are_rejected_narrowly(tmp_path: Path) -> None:
    source = tmp_path / "app.txt"
    source.write_text("PORT=8080\n", encoding="utf-8")
    extraction_tools = LocalRepositoryTools(tmp_path, RunLimits())
    evidence = extraction_tools.read_lines("app.txt", 1, 1).evidence[0]
    source.write_text("PORT=9090\n", encoding="utf-8")
    checking_tools = LocalRepositoryTools(tmp_path, RunLimits())
    topic = TopicResult(
        topic="networking",
        workload="app",
        status="answered",
        claims=[
            Claim(property_path="port", value=8080, evidence_refs=[evidence.id]),
            Claim(property_path="protocol", value="http", evidence_refs=["E999"]),
        ],
    )

    result = check_topics([topic], [evidence], checking_tools)

    assert result.topics[0].status == "partial"
    assert result.topics[0].facts == {}
    assert [item["reason"] for item in result.rejected_claims] == [
        "digest_mismatch",
        "missing_evidence",
    ]


def test_unresolved_and_unsupported_topics_keep_narrow_statuses(tmp_path: Path) -> None:
    tools = LocalRepositoryTools(tmp_path, RunLimits())
    unresolved = TopicResult(
        topic="resources_and_scaling",
        workload="app",
        status="unresolved",
        required_inputs={
            "resources.cpu_request": RequiredInput(
                reason="runtime_measurement_required",
                needed_for="pod_resources",
            )
        },
    )
    unsupported = TopicResult(
        topic="storage",
        workload="app",
        status="unsupported",
        unsupported_reason="proprietary binary configuration",
    )

    result = check_topics([unresolved, unsupported], [], tools)

    assert [topic.status for topic in result.topics] == ["unresolved", "unsupported"]


def test_checked_primary_claim_records_repeatable_confidence_factors(
    tmp_path: Path,
) -> None:
    (tmp_path / "application.properties").write_text(
        "server.port=8080\n", encoding="utf-8"
    )
    tools = LocalRepositoryTools(tmp_path, RunLimits())
    evidence = tools.read_lines("application.properties", 1, 1).evidence[0]
    topic = TopicResult(
        topic="networking",
        workload="app",
        status="answered",
        claims=[Claim(property_path="port", value=8080, evidence_refs=[evidence.id])],
    )

    result = check_topics([topic], [evidence], tools)

    confidence = result.topics[0].checked_claims[0].confidence
    assert confidence.level == "high"
    assert confidence.factors.direct_setting is True
    assert confidence.factors.source_context == "primary"
