from repo_analyzer.inventory import build_inventory


def test_discovers_sql_by_extension_not_filename(tmp_path):
    sql = tmp_path / "database" / "jpetstore-hsqldb-schema.sql"
    sql.parent.mkdir(parents=True)
    sql.write_text("create table account (id int);\n")

    inv = build_inventory(tmp_path)

    assert inv.sql_init_files == ["database/jpetstore-hsqldb-schema.sql"]
    detected = {(d.path, d.kind) for d in inv.detected}
    assert ("database/jpetstore-hsqldb-schema.sql", "sql-candidate") in detected


def test_discovers_kubernetes_yaml_by_content_not_path(tmp_path):
    manifest = tmp_path / "deploy" / "prod" / "app.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: api\n"
    )

    inv = build_inventory(tmp_path)

    assert inv.kubernetes_yaml_files == ["deploy/prod/app.yaml"]
    detected = {(d.path, d.kind) for d in inv.detected}
    assert ("deploy/prod/app.yaml", "kubernetes-yaml-candidate") in detected


def test_does_not_mark_plain_yaml_as_kubernetes(tmp_path):
    config = tmp_path / "config" / "settings.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("feature: true\n")

    inv = build_inventory(tmp_path)

    assert inv.kubernetes_yaml_files == []


def test_skips_large_sql_candidate_and_records_it(tmp_path):
    sql = tmp_path / "db" / "huge.sql"
    sql.parent.mkdir()
    sql.write_text(" " * (10 * 1024 * 1024 + 1))

    inv = build_inventory(tmp_path)

    assert inv.sql_init_files == []
    assert inv.skipped_large_candidates == ["db/huge.sql"]
    detected = {(d.path, d.kind) for d in inv.detected}
    assert ("db/huge.sql", "candidate-skipped-large") in detected


def test_skipped_large_candidate_paths_are_deduplicated(tmp_path):
    manifest = tmp_path / "deploy.yaml"
    manifest.write_text(" " * (10 * 1024 * 1024 + 1))

    inv = build_inventory(tmp_path)

    assert inv.skipped_large_candidates == ["deploy.yaml"]
