"""Validate migration question output against the required external Java repos."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from repo_analyzer.analyzer import analyze_repository

REQUIRED_REPOSITORIES = [
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default="/tmp/repo-analyzer-validation")
    parser.add_argument("--output", default="docs/validation/2026-07-20-required-java-repos.md")
    parser.add_argument("--skip-clone", action="store_true")
    args = parser.parse_args()

    workdir = Path(args.workdir)
    output = Path(args.output)
    workdir.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    failures: list[tuple[str, list[str]]] = []

    for repo in REQUIRED_REPOSITORIES:
        repo_dir = workdir / repo.replace("/", "__")
        if not args.skip_clone:
            clone_or_update(repo, repo_dir)
        commit_sha = current_commit(repo_dir)
        result = analyze_repository(str(repo_dir))
        errors = validate_result(repo, result)
        if errors:
            failures.append((repo, errors))
        rows.append(render_repo_row(repo, commit_sha, result, errors))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(rows, failures), encoding="utf-8")
    return 1 if failures else 0


def clone_or_update(repo: str, repo_dir: Path) -> None:
    url = f"https://github.com/{repo}.git"
    if repo_dir.exists():
        subprocess.run(["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin"], check=True)
        subprocess.run(["git", "-C", str(repo_dir), "reset", "--hard", "FETCH_HEAD"], check=True)
        return
    subprocess.run(["git", "clone", "--depth", "1", url, str(repo_dir)], check=True)


def current_commit(repo_dir: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def validate_result(repo: str, result) -> list[str]:
    errors: list[str] = []
    if len(result.migration_questions) != 7:
        errors.append(f"expected 7 migration questions, got {len(result.migration_questions)}")
    if not result.source_coverage:
        errors.append("source_coverage is empty")
    for index, question in enumerate(result.migration_questions, start=1):
        if not question.basis and not question.missing:
            errors.append(f"question {index} has neither basis nor missing")
    evidence_count = len(representative_evidence(result, limit=3))
    if evidence_count < 2:
        errors.append(f"expected at least 2 representative evidence samples, got {evidence_count}")
    return errors


def representative_evidence(result, limit: int = 3) -> list[str]:
    samples: list[str] = []
    for question in result.migration_questions:
        for basis in question.basis:
            if not basis.evidence:
                continue
            evidence = basis.evidence[0]
            samples.append(
                f"{basis.source_section}.{basis.subject} @ "
                f"{evidence.path}:{evidence.start_line}-{evidence.end_line}"
            )
            if len(samples) >= limit:
                return samples
    return samples


def render_repo_row(repo: str, commit_sha: str, result, errors: list[str]) -> str:
    statuses = ", ".join(f"{question.id}={question.status}" for question in result.migration_questions)
    coverage = ", ".join(f"{item.source_class}:{item.status}" for item in result.source_coverage)
    warning_codes = ", ".join(warning.code for warning in getattr(result, "warnings", [])) or "none"
    coverage_gaps = ", ".join(
        item.source_class
        for item in result.source_coverage
        if item.status in {"error", "ignored", "missing"}
    ) or "none"
    samples = "; ".join(representative_evidence(result)) or "no line-located evidence samples"
    outcome = "PASS" if not errors else "FAIL: " + "; ".join(errors)
    return (
        f"| `{repo}` | `{commit_sha[:12]}` | {outcome} | {statuses} | {coverage} | "
        f"warnings: {warning_codes}; coverage gaps: {coverage_gaps} | {samples} |"
    )


def render_report(rows: list[str], failures: list[tuple[str, list[str]]]) -> str:
    lines = [
        "# Required Java Repository Validation",
        "",
        "Validation set is fixed by requirement and must contain exactly 10 repositories.",
        "",
        "| Repository | Commit | Outcome | Question statuses | Source coverage | Warnings/gaps | Evidence samples |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
    ]
    if failures:
        lines.append("## Failures")
        lines.append("")
        for repo, errors in failures:
            lines.append(f"- `{repo}`: {'; '.join(errors)}")
        lines.append("")
    else:
        lines.append("All required repositories passed structural validation with representative evidence samples.")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
