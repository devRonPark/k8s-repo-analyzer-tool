from __future__ import annotations

from repo_analyzer.parsers.dotenv import parse_dotenv


def test_values_empty_and_quotes():
    env = parse_dotenv('A=1\nB=\n# comment\nexport C="x"\nD=\'y\'\n', ".env")
    assert env.get("A").value == "1" and env.get("A").is_empty is False
    assert env.get("B").is_empty is True
    assert env.get("C").value == "x"
    assert env.get("D").value == "y"


def test_line_numbers_are_recorded(golden_repo):
    env = parse_dotenv((golden_repo / ".env").read_text(), ".env")
    entry = env.get("POSTGRES_PORT")
    assert entry.value == "5432"
    assert entry.line == 36


def test_golden_empty_values(golden_repo):
    env = parse_dotenv((golden_repo / ".env").read_text(), ".env")
    empties = {e.name for e in env.entries if e.is_empty}
    assert {"SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SENTRY_DSN"} <= empties


def test_malformed_line_reported():
    env = parse_dotenv("GOOD=1\nNO_EQUALS_HERE\n=missingkey\n", ".env")
    codes = {i.construct for i in env.issues}
    assert "dotenv_line" in codes
    assert env.get("GOOD").value == "1"
