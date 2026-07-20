# Kubernetes Migration Brief Design

## Goal

Render the existing seven-question `AnalysisResult.migration_questions` JSON into a concise, human-readable Kubernetes migration brief.

The brief is for engineers who need the migration picture quickly without reading the full workload-centric Markdown report or raw JSON.

## Scope

- Add a separate Markdown brief renderer.
- Add a CLI output option for writing the brief.
- Keep the existing JSON schema and full Markdown report compatible.
- Use only deterministic facts already present in `AnalysisResult`.
- Do not generate Kubernetes manifests or invent operational defaults.

## Non-Goals

- Do not change how migration questions are derived.
- Do not replace the existing `--markdown-output` report.
- Do not add timestamps, durations, absolute paths, or other non-deterministic output.
- Do not summarize source code outside the existing analyzer facts.

## Proposed Interface

Add `src/repo_analyzer/reporters/brief_reporter.py` with:

```python
def to_brief(result: AnalysisResult) -> str: ...
def write_brief(result: AnalysisResult, path: str | Path) -> None: ...
```

Add `--brief-output <path>` to `repo-analyzer analyze`.

The existing behavior stays the same:

- If no output options are supplied, stdout remains canonical JSON.
- `--json-output` and `--markdown-output` continue to work as they do now.
- `--brief-output` can be combined with the other output options.

## Output Shape

The brief is Markdown with four sections:

1. Title and repository metadata:
   - `# Kubernetes migration brief - <repository>`
   - profile, git ref, detected file count
2. `## Executive summary`:
   - compact status line for all seven questions
   - component count and unresolved-input count
3. `## Seven migration questions`:
   - one subsection per question
   - status, natural-language answer, compact evidence summary, missing inputs
4. `## Open inputs`:
   - deterministic list of unresolved operational inputs, or a none-detected line

Evidence is compressed to `section.subject -> path:start-end` entries. If a question has many basis entries, the renderer may cap the displayed evidence per question and report how many additional entries exist. The cap must be deterministic.

## Error and Empty States

- If `migration_questions` is empty, render `_No migration questions emitted._`.
- If a question has no basis, render `Evidence: -`.
- If a question has no missing inputs, render `Missing: -`.
- If there are no unresolved operational inputs, render `_No unresolved operational inputs recorded._`.

## Testing

Add focused tests in `tests/test_migration_questions.py`:

- `to_brief()` renders the title, all seven questions, statuses, answers, missing inputs, and compact evidence.
- `to_brief()` does not include raw JSON-like `Basis:` or full report sections such as `## Components`.
- CLI accepts `--brief-output` and writes a brief file while preserving existing stdout behavior.

Run targeted tests first, then the full offline suite.

## Risks

- The brief could hide too much evidence. Mitigation: show compact evidence and keep the full JSON/full Markdown available.
- Existing users may confuse brief Markdown with full Markdown. Mitigation: use a separate option and distinct title.
- Long answers may become hard to scan. Mitigation: keep the renderer structural and avoid adding prose beyond existing answer strings.
