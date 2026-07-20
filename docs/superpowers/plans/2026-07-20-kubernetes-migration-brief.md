# Kubernetes Migration Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Markdown brief that renders the existing seven-question `AnalysisResult.migration_questions` JSON into a concise Kubernetes migration brief.

**Architecture:** Keep the analyzer and JSON schema unchanged. Add a focused reporter module that consumes `AnalysisResult`, then wire it into the existing argparse CLI as an optional output file. Tests cover the pure renderer first and the CLI integration second.

**Tech Stack:** Python 3.12, Pydantic v2 models, argparse, pytest.

## Global Constraints

- Add a separate Markdown brief renderer.
- Add a CLI output option for writing the brief.
- Keep the existing JSON schema and full Markdown report compatible.
- Use only deterministic facts already present in `AnalysisResult`.
- Do not generate Kubernetes manifests or invent operational defaults.
- Do not change how migration questions are derived.
- Do not replace the existing `--markdown-output` report.
- Do not add timestamps, durations, absolute paths, or other non-deterministic output.
- Do not summarize source code outside the existing analyzer facts.
- If no output options are supplied, stdout remains canonical JSON.
- `--brief-output` can be combined with `--json-output` and `--markdown-output`.

---

## File Structure

- Create `src/repo_analyzer/reporters/brief_reporter.py`: pure Markdown brief renderer with `to_brief()` and `write_brief()`.
- Modify `tests/test_migration_questions.py`: add focused renderer and CLI tests.
- Modify `src/repo_analyzer/cli.py`: add `--brief-output`, call `write_brief()`, preserve stdout behavior.
- Modify `README.md`: document the new CLI option briefly.

### Task 1: Brief Reporter

**Files:**
- Create: `src/repo_analyzer/reporters/brief_reporter.py`
- Modify: `tests/test_migration_questions.py`

**Interfaces:**
- Consumes: `AnalysisResult.migration_questions`, `AnalysisResult.unresolved_operational_inputs`, `AnalysisResult.repository`, `AnalysisResult.components`
- Produces: `to_brief(result: AnalysisResult) -> str`
- Produces: `write_brief(result: AnalysisResult, path: str | Path) -> None`

- [ ] **Step 1: Write the failing renderer test**

Append this test to `tests/test_migration_questions.py`:

```python
def test_brief_renderer_outputs_human_readable_migration_brief(jpetstore_repo):
    from repo_analyzer.analyzer import analyze_repository
    from repo_analyzer.reporters.brief_reporter import to_brief

    result = analyze_repository(str(jpetstore_repo))
    brief = to_brief(result)

    assert brief.startswith("# Kubernetes migration brief - jpetstore-6\n")
    assert "## Executive summary" in brief
    assert "Questions: application_identity=answered" in brief
    assert "## Seven migration questions" in brief
    assert "### 1. 어떤 애플리케이션인가?" in brief
    assert "**Status:** answered" in brief
    assert "**Answer:** jpetstore: Java 17 web application" in brief
    assert "**Evidence:** components.jpetstore" in brief
    assert "### 7. Repository만으로 결정할 수 없는 값은 무엇인가?" in brief
    assert "## Open inputs" in brief
    assert "- readiness_liveness_probe:" in brief
    assert "## 1. Components" not in brief
    assert "- Basis:" not in brief
```

- [ ] **Step 2: Run the renderer test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_brief_renderer_outputs_human_readable_migration_brief
```

Expected: FAIL with `ModuleNotFoundError: No module named 'repo_analyzer.reporters.brief_reporter'`.

- [ ] **Step 3: Implement the brief reporter**

Create `src/repo_analyzer/reporters/brief_reporter.py`:

```python
"""Concise Markdown brief for the seven Kubernetes migration questions."""

from __future__ import annotations

from pathlib import Path

from ..models import AnalysisResult, AnswerBasis

_MAX_EVIDENCE_ITEMS = 6


def to_brief(result: AnalysisResult) -> str:
    lines: list[str] = []
    out = lines.append
    repo = result.repository

    out(f"# Kubernetes migration brief - {repo.name}")
    out("")
    out(f"- Profile: `{repo.profile}`")
    out(f"- Git ref: `{repo.git_ref}`" if repo.git_ref else "- Git ref: (not provided)")
    out(f"- Detected files: {repo.file_count}")
    out("")

    out("## Executive summary")
    out("")
    if result.migration_questions:
        statuses = ", ".join(f"{q.id}={q.status}" for q in result.migration_questions)
        out(f"- Questions: {statuses}")
    else:
        out("- Questions: none emitted")
    out(f"- Components: {len(result.components)}")
    out(f"- Open inputs: {len(result.unresolved_operational_inputs)}")
    out("")

    out("## Seven migration questions")
    out("")
    if not result.migration_questions:
        out("_No migration questions emitted._")
        out("")
    else:
        for index, question in enumerate(result.migration_questions, start=1):
            out(f"### {index}. {question.question}")
            out("")
            out(f"**Status:** {question.status}")
            out("")
            out(f"**Answer:** {question.answer}")
            out("")
            out(f"**Evidence:** {_format_basis(question.basis)}")
            out("")
            out(f"**Missing:** {_format_missing(question.missing)}")
            out("")

    out("## Open inputs")
    out("")
    if not result.unresolved_operational_inputs:
        out("_No unresolved operational inputs recorded._")
    else:
        for item in result.unresolved_operational_inputs:
            out(f"- {item.subject}: {item.needed_input}")
    out("")

    return "\n".join(lines) + "\n"


def _format_basis(basis_items: list[AnswerBasis]) -> str:
    if not basis_items:
        return "-"
    rendered = [_format_basis_item(item) for item in basis_items[:_MAX_EVIDENCE_ITEMS]]
    remaining = len(basis_items) - _MAX_EVIDENCE_ITEMS
    if remaining > 0:
        rendered.append(f"+{remaining} more")
    return "; ".join(rendered)


def _format_basis_item(item: AnswerBasis) -> str:
    prefix = f"{item.source_section}.{item.subject}"
    if not item.evidence:
        return prefix
    locations = ", ".join(
        f"{evidence.path}:{evidence.start_line}-{evidence.end_line}"
        for evidence in item.evidence[:2]
    )
    remaining = len(item.evidence) - 2
    if remaining > 0:
        locations += f", +{remaining} more"
    return f"{prefix} -> {locations}"


def _format_missing(missing: list[str]) -> str:
    if not missing:
        return "-"
    return "; ".join(missing)


def write_brief(result: AnalysisResult, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_brief(result), encoding="utf-8")
```

- [ ] **Step 4: Run the renderer test to verify it passes**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_brief_renderer_outputs_human_readable_migration_brief
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/repo_analyzer/reporters/brief_reporter.py tests/test_migration_questions.py
git commit -m "feat: add Kubernetes migration brief renderer"
```

### Task 2: CLI Brief Output

**Files:**
- Modify: `src/repo_analyzer/cli.py`
- Modify: `tests/test_migration_questions.py`

**Interfaces:**
- Consumes: `write_brief(result: AnalysisResult, path: str | Path) -> None`
- Produces: CLI option `repo-analyzer analyze --brief-output <path>`

- [ ] **Step 1: Write the failing CLI test**

Append this test to `tests/test_migration_questions.py`:

```python
def test_cli_writes_brief_output_file(jpetstore_repo, tmp_path):
    from repo_analyzer.cli import main

    brief_path = tmp_path / "brief.md"

    exit_code = main(
        [
            "analyze",
            "--repo",
            str(jpetstore_repo),
            "--brief-output",
            str(brief_path),
        ]
    )

    assert exit_code == 0
    brief = brief_path.read_text(encoding="utf-8")
    assert brief.startswith("# Kubernetes migration brief - jpetstore-6\n")
    assert "## Seven migration questions" in brief
```

- [ ] **Step 2: Run the CLI test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_cli_writes_brief_output_file
```

Expected: FAIL with argparse rejecting `--brief-output`.

- [ ] **Step 3: Implement the CLI option**

In `src/repo_analyzer/cli.py`, add the import:

```python
from .reporters.brief_reporter import write_brief
```

Add the argument near the existing output arguments:

```python
analyze.add_argument("--brief-output", default=None, help="path to write the migration brief Markdown")
```

Write the file after the full Markdown output block:

```python
if args.brief_output:
    write_brief(result, args.brief_output)
```

Update stdout preservation condition:

```python
if not args.json_output and not args.markdown_output and not args.brief_output:
    sys.stdout.write(to_json(result))
```

- [ ] **Step 4: Run the CLI test to verify it passes**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_cli_writes_brief_output_file
```

Expected: PASS.

- [ ] **Step 5: Run both migration-question tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/repo_analyzer/cli.py tests/test_migration_questions.py
git commit -m "feat: add migration brief CLI output"
```

### Task 3: Documentation and Final Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: CLI option `--brief-output <path>`
- Produces: README usage documentation

- [ ] **Step 1: Update README CLI usage**

In `README.md`, update the CLI example to include brief output:

```bash
uv run repo-analyzer analyze \
  --repo ./target-repository \
  --profile kubernetes-p0 \
  --json-output ./output/analysis.json \
  --markdown-output ./output/report.md \
  --brief-output ./output/brief.md
```

Add a bullet after `--markdown-output`:

```markdown
- `--brief-output`: 7문항 migration JSON만 사람이 읽기 좋은 Markdown brief로 씁니다.
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py
```

Expected: PASS.

- [ ] **Step 3: Run the full offline suite**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document migration brief output"
```
