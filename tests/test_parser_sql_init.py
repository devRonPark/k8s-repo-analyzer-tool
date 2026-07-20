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


def test_classifies_nonstandard_schema_filename_by_create_table():
    script = parse_sql_init("CREATE TABLE orders (id int);\n", "database/init-v1.sql")

    assert script.script_kind == "schema"
    assert [t.value for t in script.table_names] == ["orders"]


def test_classifies_seed_script_by_insert_statements():
    script = parse_sql_init(
        "INSERT INTO account VALUES (1);\n"
        "insert into orders values (10);\n",
        "db/load-demo.sql",
    )

    assert script.script_kind == "data"
    assert [t.value for t in script.insert_table_names] == ["account", "orders"]


def test_classifies_mixed_schema_and_seed_file():
    script = parse_sql_init(
        "CREATE TABLE account (id int);\n"
        "INSERT INTO account VALUES (1);\n",
        "db/bootstrap.sql",
    )

    assert script.script_kind == "mixed"
