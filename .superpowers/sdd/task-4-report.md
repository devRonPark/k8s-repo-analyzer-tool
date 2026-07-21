# Task 4 Report: Make Reporters Profile-First

## Scope

- Added profile-first rendering to the Markdown and concise brief reporters.
- Preserved the Markdown reporter's legacy evidence-rich sections and the brief's seven migration questions.
- Did not change analyzer or rule behavior.

## TDD Evidence

### RED

Command:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_markdown_reporter.py tests/test_brief_reporter.py
```

Result: failed as expected (2 failures). The Markdown reporter lacked `## 1. Workload profiles`; the brief lacked `Image build` profile content.

### GREEN

Command:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_markdown_reporter.py tests/test_brief_reporter.py
```

Result: passed (2 tests).

## Implementation

- Markdown renders `## 1. Workload profiles` when profiles exist, with source files, image build facts, runtime deployment facts, separately labeled workload-controller and companion candidates, relationship arrows from `WorkloadRelationship`, and deduplicated unresolved decisions.
- The concise brief adds workload-prefixed image-build/runtime summaries, candidate categories, and compact relationship arrows before the existing seven migration questions.
- When `workload_profiles` is empty, the Markdown reporter keeps the existing Components section; the brief keeps its existing behavior.

## Full Verification

Command:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
```

Result: passed (exit code 0).

## Review Fix: Brief Question Enrichment

- The brief now enriches the `build_and_run` answer with workload-name-prefixed `Image build` and `Runtime deployment` profile summaries.
- The `ports_and_services` answer now renders profile-derived `Workload controller candidates` and `Companion object candidates` separately, and includes compact workload relationship arrows.
- Status, evidence, missing fields, and the existing seven-question structure are preserved. Briefs without workload profiles continue to use the legacy answer unchanged.
- Added a section-extraction regression test that verifies profile-derived text occurs inside the relevant seven-question sections, rather than only in the separate workload-profile section.

### Verification

Command:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_markdown_reporter.py tests/test_brief_reporter.py
```

Result: passed (4 tests, exit code 0).

Command:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
```

Result: passed (261 tests, exit code 0).

## Review Fix: Nested Unresolved Decisions

- Markdown profile rendering now includes `open_decisions` from exposure candidates (when present), probe candidates, Kubernetes object candidates, and workload relationships, in addition to image/runtime unresolved and open decisions.
- Decisions remain deterministic by preserving source-list order and are deduplicated before rendering.
- Added `test_markdown_reporter_includes_candidate_and_relationship_open_decisions` using direct model construction.

### Verification

Command:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_markdown_reporter.py tests/test_brief_reporter.py
```

Result: passed (exit code 0).

Command:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
```

Result: passed (exit code 0).
