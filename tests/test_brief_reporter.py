from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.reporters.brief_reporter import to_brief


def test_brief_reporter_groups_build_and_runtime_by_workload(golden_repo):
    result = analyze_repository(str(golden_repo))

    brief = to_brief(result)

    assert "backend" in brief
    assert "Image build" in brief
    assert "Runtime deployment" in brief
    assert "backend -> db" in brief
