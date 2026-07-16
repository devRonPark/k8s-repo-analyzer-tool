from __future__ import annotations

from repo_analyzer.parsers.python_settings import parse_python_settings


def test_settings_fields(golden_repo):
    ps = parse_python_settings(
        (golden_repo / "backend/app/core/config.py").read_text(), "config.py"
    )
    assert ps.class_name == "Settings"
    assert ps.get("POSTGRES_PORT").default_repr == "5432"
    assert ps.get("POSTGRES_PORT").has_default is True
    # Required field (no default) is distinguished.
    assert ps.get("PROJECT_NAME").has_default is False
    assert ps.get("POSTGRES_USER").has_default is False


def test_field_line_numbers_from_ast(golden_repo):
    ps = parse_python_settings(
        (golden_repo / "backend/app/core/config.py").read_text(), "config.py"
    )
    field = ps.get("POSTGRES_PORT")
    assert field.start_line == 53


def test_syntax_error_reported():
    ps = parse_python_settings("class : bad syntax", "config.py")
    assert any(i.construct == "python_syntax" for i in ps.issues)


def test_no_basesettings_reported():
    ps = parse_python_settings("class Plain:\n    x: int = 1\n", "config.py")
    assert ps.class_name is None
    assert any(i.construct == "python_settings" for i in ps.issues)
