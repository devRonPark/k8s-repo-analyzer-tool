from __future__ import annotations

from repo_analyzer.parsers.dockerfile import exec_form, parse_dockerfile


def test_cmd_exec_form_and_line(golden_repo):
    df = parse_dockerfile((golden_repo / "backend/Dockerfile").read_text(), "backend/Dockerfile")
    cmd = df.last("CMD")
    assert exec_form(cmd.argument) == ["fastapi", "run", "--workers", "4"]
    assert cmd.start_line == 45


def test_multistage_stages(golden_repo):
    df = parse_dockerfile((golden_repo / "frontend/Dockerfile").read_text(), "frontend/Dockerfile")
    assert [s.image for s in df.stages] == ["oven/bun:1", "nginx:1"]
    assert df.stages[0].alias == "build-stage"
    assert df.final_base_image.image == "nginx:1"


def test_arg_detected(golden_repo):
    df = parse_dockerfile((golden_repo / "frontend/Dockerfile").read_text(), "frontend/Dockerfile")
    args = [a.argument for a in df.find("ARG")]
    assert "VITE_API_URL" in args


def test_line_continuation_joins_into_one_instruction():
    df = parse_dockerfile("FROM x\nRUN a \\\n  b \\\n  c\n", "Dockerfile")
    run = df.last("RUN")
    assert run.argument == "a b c"
    assert run.start_line == 2
    assert run.end_line == 4


def test_shell_form_cmd_is_not_exec_form():
    df = parse_dockerfile("FROM x\nCMD echo hi\n", "Dockerfile")
    assert exec_form(df.last("CMD").argument) is None


def test_missing_from_is_reported():
    df = parse_dockerfile("RUN echo hi\n", "Dockerfile")
    assert any(i.construct == "dockerfile_from" for i in df.issues)
