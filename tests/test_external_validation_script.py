import importlib.util
from pathlib import Path


def _load_script():
    path = Path("scripts/validate_external_repos.py")
    spec = importlib.util.spec_from_file_location("validate_external_repos", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_required_repositories_are_exactly_the_validation_set():
    module = _load_script()

    assert module.REQUIRED_REPOSITORIES == [
        "mybatis/jpetstore-6",
        "spring-projects/spring-petclinic",
        "jhipster/jhipster-sample-app",
        "macrozheng/mall",
        "jeecgboot/JeecgBoot",
        "apache/guacamole-client",
        "apache/ofbiz-framework",
        "openmrs/openmrs-core",
        "shopizer-ecommerce/shopizer",
        "halo-dev/halo",
    ]


def test_validate_result_requires_seven_questions_coverage_and_evidence_samples():
    module = _load_script()

    class Evidence:
        path = "pom.xml"
        start_line = 10
        end_line = 12

    class Basis:
        source_section = "configuration"
        subject = "build.tool"
        evidence = [Evidence()]

    class Question:
        def __init__(self, missing):
            self.basis = [Basis()]
            self.missing = missing

    class Result:
        source_coverage = ["coverage"]
        migration_questions = [Question([]) for _ in range(7)]

    assert module.validate_result("owner/repo", Result()) == []


def test_validate_result_reports_missing_basis_or_missing():
    module = _load_script()

    class Question:
        basis = []
        missing = []

    class Result:
        source_coverage = []
        migration_questions = [Question()]

    errors = module.validate_result("owner/repo", Result())

    assert "expected 7 migration questions, got 1" in errors
    assert "source_coverage is empty" in errors
    assert "question 1 has neither basis nor missing" in errors


def test_validate_result_requires_two_evidence_samples():
    module = _load_script()

    class Question:
        basis = []
        missing = ["missing input"]

    class Result:
        source_coverage = ["coverage"]
        migration_questions = [Question() for _ in range(7)]

    errors = module.validate_result("owner/repo", Result())

    assert "expected at least 2 representative evidence samples, got 0" in errors


def test_render_repo_row_includes_commit_sha_and_evidence_samples():
    module = _load_script()

    class Evidence:
        path = "pom.xml"
        start_line = 10
        end_line = 12

    class Basis:
        source_section = "configuration"
        subject = "build.tool"
        evidence = [Evidence()]

    class Question:
        id = "build_and_run"
        status = "answered"
        basis = [Basis()]
        missing = []

    class Coverage:
        source_class = "build_file"
        status = "present"

    class Result:
        source_coverage = [Coverage()]
        migration_questions = [Question()]

    row = module.render_repo_row("owner/repo", "abc1234", Result(), [])

    assert "`abc1234`" in row
    assert "configuration.build.tool @ pom.xml:10-12" in row


def test_render_repo_row_reports_warnings_without_failing():
    module = _load_script()

    class Warning:
        code = "source_conflict"

    class Coverage:
        source_class = "skipped_large_candidates"
        status = "error"

    class Result:
        warnings = [Warning()]
        source_coverage = [Coverage()]
        migration_questions = []

    row = module.render_repo_row("owner/repo", "abc1234", Result(), [])

    assert "| PASS |" in row
    assert "warnings: source_conflict" in row
    assert "coverage gaps: skipped_large_candidates" in row
