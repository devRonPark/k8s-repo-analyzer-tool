from repo_analyzer.models import (
    AnalysisResult,
    AnswerBasis,
    MigrationQuestionAnswer,
    RepositoryMetadata,
    SourceCoverage,
)


def test_analysis_result_accepts_source_coverage_and_migration_questions():
    result = AnalysisResult(
        repository=RepositoryMetadata(
            name="sample",
            profile="kubernetes-p0",
            file_count=1,
        ),
        source_coverage=[
            SourceCoverage(
                source_class="sql",
                status="present",
                paths=["db/init/customer-schema.sql"],
                role="primary",
                detection="extension .sql plus CREATE TABLE content",
            )
        ],
        migration_questions=[
            MigrationQuestionAnswer(
                id="persistent_data",
                question="어떤 데이터가 영속되어야 하는가?",
                status="partial",
                answer="Database schema was detected, but production database storage policy is unresolved.",
                basis=[
                    AnswerBasis(
                        source_section="storage",
                        subject="database.schema",
                        evidence=[],
                    )
                ],
                missing=["production database StorageClass/managed service decision"],
            )
        ],
    )

    dumped = result.model_dump(mode="json")
    assert dumped["source_coverage"][0]["source_class"] == "sql"
    assert dumped["migration_questions"][0]["id"] == "persistent_data"
    assert dumped["migration_questions"][0]["status"] == "partial"


def test_kubernetes_manifest_facts_are_emitted_as_findings(tmp_path):
    from repo_analyzer.analyzer import analyze_repository

    manifest = tmp_path / "k8s" / "app.yaml"
    manifest.parent.mkdir()
    manifest.write_text(
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "        - name: api\n"
        "          ports:\n"
        "            - containerPort: 8080\n"
        "          envFrom:\n"
        "            - configMapRef:\n"
        "                name: app-config\n"
        "            - secretRef:\n"
        "                name: app-secret\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  ports:\n"
        "    - port: 80\n"
        "      targetPort: 8080\n"
    )

    result = analyze_repository(str(tmp_path))

    assert any(f.subject == "k8s.container_port.api" for f in result.networking)
    assert any(f.subject == "k8s.service_port.api" for f in result.networking)
    assert any(f.subject == "k8s.configmap_ref.app-config" for f in result.configuration)
    assert any(f.subject == "k8s.secret_ref.app-secret" for f in result.secrets)


def test_source_coverage_records_present_missing_and_supplemental_sources(tmp_path):
    from repo_analyzer.analyzer import analyze_repository

    (tmp_path / "README.md").write_text("# Sample App\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "docker-compose.yml").write_text("services:\n  db:\n    image: postgres:16\n")
    sql = tmp_path / "db" / "init.sql"
    sql.parent.mkdir()
    sql.write_text("CREATE TABLE account (id int);\n")

    result = analyze_repository(str(tmp_path))
    coverage = {c.source_class: c for c in result.source_coverage}

    assert coverage["readme"].status == "present"
    assert coverage["sql"].status == "present"
    assert coverage["compose"].status == "ignored"
    assert coverage["compose"].role == "sample_or_documented_deployment"
    assert coverage["dockerfile"].status == "missing"


def test_source_coverage_promotes_documented_compose_when_readme_selects_it(tmp_path):
    from repo_analyzer.analyzer import analyze_repository

    (tmp_path / "README.md").write_text("Run with `docker compose -f docs/docker-compose.yml up`.\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "docker-compose.yml").write_text("services:\n  app:\n    image: demo/app\n")

    result = analyze_repository(str(tmp_path))
    coverage = {c.source_class: c for c in result.source_coverage}

    assert coverage["compose"].status == "present"
    assert coverage["compose"].role == "selected_primary"
    assert coverage["compose"].paths == ["docs/docker-compose.yml"]


def test_source_coverage_records_large_candidate_gaps(tmp_path):
    from repo_analyzer.analyzer import analyze_repository

    sql = tmp_path / "db" / "huge.sql"
    sql.parent.mkdir()
    sql.write_text(" " * (10 * 1024 * 1024 + 1))

    result = analyze_repository(str(tmp_path))
    coverage = {c.source_class: c for c in result.source_coverage}

    assert coverage["skipped_large_candidates"].status == "error"
    assert coverage["skipped_large_candidates"].paths == ["db/huge.sql"]


def test_migration_questions_are_always_emitted_with_basis_or_missing(jpetstore_repo):
    from repo_analyzer.analyzer import analyze_repository

    result = analyze_repository(str(jpetstore_repo))

    expected_ids = [
        "application_identity",
        "build_and_run",
        "ports_and_services",
        "external_dependencies",
        "configmaps_and_secrets",
        "persistent_data",
        "repository_unknowns",
    ]
    assert [q.id for q in result.migration_questions] == expected_ids

    for question in result.migration_questions:
        assert question.question
        assert question.answer
        assert question.status in {"answered", "partial", "unresolved", "not_detected"}
        assert question.basis or question.missing


def test_persistent_data_question_does_not_treat_empty_app_storage_as_no_data(jpetstore_repo):
    from repo_analyzer.analyzer import analyze_repository

    result = analyze_repository(str(jpetstore_repo))
    persistent = next(q for q in result.migration_questions if q.id == "persistent_data")

    assert persistent.status == "partial"
    assert "embedded HSQL" in persistent.answer
    assert "application PVC" in persistent.answer
    assert any("external database" in item.lower() for item in persistent.missing)


def test_kubernetes_manifest_findings_are_used_as_question_basis(tmp_path):
    from repo_analyzer.analyzer import analyze_repository

    manifest = tmp_path / "k8s" / "app.yaml"
    manifest.parent.mkdir()
    manifest.write_text(
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "        - name: api\n"
        "          ports:\n"
        "            - containerPort: 8080\n"
        "          envFrom:\n"
        "            - configMapRef:\n"
        "                name: app-config\n"
        "            - secretRef:\n"
        "                name: app-secret\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  ports:\n"
        "    - port: 80\n"
        "      targetPort: 8080\n"
    )

    result = analyze_repository(str(tmp_path))
    questions = {q.id: q for q in result.migration_questions}

    assert any(b.source_section == "networking" for b in questions["ports_and_services"].basis)
    assert any(b.source_section == "configuration" for b in questions["configmaps_and_secrets"].basis)
    assert any(b.source_section == "secrets" for b in questions["configmaps_and_secrets"].basis)


def test_build_and_run_question_uses_line_located_build_evidence(jpetstore_repo):
    from repo_analyzer.analyzer import analyze_repository

    result = analyze_repository(str(jpetstore_repo))
    question = next(q for q in result.migration_questions if q.id == "build_and_run")

    assert any(b.evidence for b in question.basis)


def test_markdown_renders_migration_questions_with_status_basis_and_missing(jpetstore_repo):
    from repo_analyzer.analyzer import analyze_repository
    from repo_analyzer.reporters.markdown_reporter import to_markdown

    result = analyze_repository(str(jpetstore_repo))
    report = to_markdown(result)

    assert "## Migration questions" in report
    assert "## Quick answers" not in report
    assert "1. **어떤 애플리케이션인가?**" in report
    assert "- Status: `partial`" in report or "- Status: `answered`" in report
    assert "- Basis:" in report
    assert "- Missing:" in report
