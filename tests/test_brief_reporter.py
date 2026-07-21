from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.reporters.brief_reporter import to_brief


def _question_section(brief: str, result, question_id: str) -> str:
    index, question = next(
        (index, question)
        for index, question in enumerate(result.migration_questions, start=1)
        if question.id == question_id
    )
    heading = f"### {index}. {question.question}"
    start = brief.index(heading)
    next_heading = brief.find("\n### ", start + len(heading))
    return brief[start : next_heading if next_heading != -1 else None]


def test_brief_reporter_groups_build_and_runtime_by_workload(golden_repo):
    result = analyze_repository(str(golden_repo))

    brief = to_brief(result)

    assert "backend" in brief
    assert "Image build" in brief
    assert "Runtime deployment" in brief
    assert "backend -> db" in brief


def test_brief_reporter_enriches_relevant_question_answers_from_workload_profiles(golden_repo):
    result = analyze_repository(str(golden_repo))

    brief = to_brief(result)

    build_and_run = _question_section(brief, result, "build_and_run")
    ports_and_services = _question_section(brief, result, "ports_and_services")

    assert "backend: Image build:" in build_and_run
    assert "backend: Runtime deployment:" in build_and_run
    assert "Workload controller candidates:" in ports_and_services
    assert "Companion object candidates:" in ports_and_services
    assert "backend -> db" in ports_and_services
