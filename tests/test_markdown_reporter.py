from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.reporters.markdown_reporter import to_markdown


def test_markdown_reporter_uses_workload_profiles(golden_repo):
    result = analyze_repository(str(golden_repo))

    markdown = to_markdown(result)

    assert "## 1. Workload profiles" in markdown
    assert "Image build profile" in markdown
    assert "Runtime deployment profile" in markdown
    assert "Workload relationships" in markdown
    assert "Deployment candidate" in markdown
    assert "Service candidate" in markdown
