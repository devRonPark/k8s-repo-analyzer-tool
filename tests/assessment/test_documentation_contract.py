from pathlib import Path


def test_assessment_docs_match_public_contract() -> None:
    text = Path("docs/ASSESSMENT.md").read_text()

    assert "repository-assessment assess" in text
    assert "migration-inputs.yaml" in text
    assert "migration-report.md" in text
    assert "assessment-details.json" in text
    assert "run-log.json" in text
    assert "completed_with_gaps" in text
    assert "https://inference.local/v1" in text
    assert "agent.yaml" not in text
    assert "readiness score" not in text.lower()


def test_legacy_cli_remains_documented_as_compatibility_path() -> None:
    readme = Path("README.md").read_text()

    assert "repo-analyzer analyze" in readme
    assert "compatibility" in readme.lower()


def test_existing_analyzer_skill_is_explicitly_compatibility_only() -> None:
    skill = Path("skills/kubernetes-repository-analyzer/SKILL.md").read_text()

    assert "repo-analyzer analyze" in skill
    assert "compatibility" in skill.lower()
