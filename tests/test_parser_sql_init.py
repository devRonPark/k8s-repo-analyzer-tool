"""Unit tests for the SQL init idempotency scanner."""

from __future__ import annotations

from repo_analyzer.parsers.sql_init import parse_sql_init


def test_create_if_not_exists_is_idempotent():
    text = "CREATE TABLE IF NOT EXISTS vets (id INT);\nCREATE TABLE IF NOT EXISTS owners (id INT);\n"
    script = parse_sql_init(text, "db/mysql/schema.sql")
    assert script.has_create_tables
    assert script.is_idempotent
    assert script.idempotency_marker_line == 1


def test_drop_if_exists_then_create_is_idempotent():
    text = "DROP TABLE vets IF EXISTS;\nCREATE TABLE vets (id INT);\n"
    script = parse_sql_init(text, "db/h2/schema.sql")
    assert script.has_create_tables
    assert script.drop_if_exists_lines == [1]
    assert script.is_idempotent


def test_plain_create_without_guard_is_not_idempotent():
    text = "CREATE TABLE vets (id INT);\nCREATE TABLE owners (id INT);\n"
    script = parse_sql_init(text, "db/x/schema.sql")
    assert script.has_create_tables
    assert not script.is_idempotent


def test_data_only_script_has_no_create_tables():
    text = "INSERT INTO vets VALUES (1, 'James', 'Carter');\n"
    script = parse_sql_init(text, "db/h2/data.sql")
    assert not script.has_create_tables
    assert not script.is_idempotent
