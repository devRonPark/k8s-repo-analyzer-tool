from __future__ import annotations

from pathlib import Path

from repository_assessment.contracts import (
    AnalysisPlan,
    PlanTarget,
    RunLimits,
    SearchTarget,
)
from repository_assessment.evidence import validate_plan
from repository_assessment.repository import LocalRepositoryTools


def _target(path: str, line_start: int = 1, line_end: int = 20) -> PlanTarget:
    return PlanTarget(
        path=path,
        line_start=line_start,
        line_end=line_end,
        topics=["runtime_profile"],
        purpose="Find runtime facts.",
        method="read_lines",
        priority="high",
    )


def test_plan_rejects_duplicate_invalid_and_over_budget_targets(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("run\n", encoding="utf-8")
    scan = LocalRepositoryTools(tmp_path, RunLimits()).scan()
    plan = AnalysisPlan(
        round=1,
        targets=[
            _target("package.json"),
            _target("package.json"),
            _target("missing.json"),
            _target("README.md", 20, 1),
        ],
    )

    checked = validate_plan(plan, scan, RunLimits(selected_targets=2))

    assert [item.path for item in checked.targets] == ["package.json"]
    assert [item.reason for item in checked.rejected] == [
        "duplicate_target",
        "path_not_in_scan",
        "invalid_line_range",
    ]


def test_plan_validates_structured_methods_searches_and_prior_operations(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("PORT=8080\n", encoding="utf-8")
    scan = LocalRepositoryTools(tmp_path, RunLimits()).scan()
    prior = _target("notes.txt", 1, 1)
    search = SearchTarget(
        pattern="PORT",
        paths=["."],
        topics=["networking"],
        purpose="Find a listener.",
        priority="medium",
    )
    invalid_parse = PlanTarget(
        path="notes.txt",
        line_start=1,
        line_end=1,
        topics=["configuration"],
        purpose="Parse configuration.",
        method="parse_structured",
        priority="low",
    )
    plan = AnalysisPlan(
        round=2,
        targets=[prior, invalid_parse],
        searches=[search, search],
    )

    checked = validate_plan(
        plan,
        scan,
        RunLimits(selected_targets=2, search_calls=1),
        prior_targets=[prior],
        prior_searches=[],
    )

    assert checked.targets == []
    assert checked.searches == [search]
    assert [item.reason for item in checked.rejected] == [
        "duplicate_target",
        "unsupported_method",
        "duplicate_search",
    ]
