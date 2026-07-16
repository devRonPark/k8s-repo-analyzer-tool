# CLAUDE.md

Project memory for **k8s-repo-analyze-agent** (`repo-analyzer`).

## What this project is

A **deterministic** tool that reads an application source repository and emits the
**P0 structural context** an engineer needs to start a Kubernetes migration. Same
repository content → **byte-identical JSON**. Facts are extracted by Python
parsers with source-line evidence; **no LLM inspects the repo**. An Agent Skill is
only a thin layer that detects intent, calls the tool, and explains the result.

Only the `kubernetes-p0` profile exists. **Non-goals** (do not add without a
request): Kubernetes/Helm manifest generation, resource sizing, replica/PVC/HPA/
PDB/StorageClass/IngressClass decisions, full business-code or security analysis,
P1/P2 depth.

## Core invariants (do not break)

- **Deterministic output.** No timestamps, durations, temp/absolute paths, random
  IDs, or unordered sets in results. Paths are repo-relative POSIX. Every list is
  sorted by an explicit key. JSON key order is intrinsic (Pydantic field order).
  A byte-level determinism test enforces this.
- **Parsers extract facts, not the LLM.** All repo facts come from `parsers/` +
  `rules/`. Never hardcode line numbers in rules — parsers locate the structural
  node (YAML path, Dockerfile instruction, AST symbol, env name, Nginx directive)
  and report its real line range.
- **Confidence labels.** Every finding is `explicit` (stated in a file),
  `derived` (≥2 explicit facts combined; link all sources), or `unresolved`
  (undecidable from the repo — record why, the input needed, `no_default_used`).
- **Never invent operational values.** replica count, CPU/memory, PVC size,
  StorageClass, IngressClass, HPA, PDB, DB HA/backup → always `unresolved`.
- **Never modify the analyzed repo.** Read-only; a test hashes the target dir
  before/after to prove it.
- **Never silently ignore unsupported syntax.** Record a `ParseIssue` →
  `warnings` / `unsupported_constructs`.

## Architecture (one-way, no cycles)

```
inventory  ->  parsers  ->  rules/kubernetes_p0  ->  models  ->  reporters
```

- `src/repo_analyzer/inventory.py` — discover P0-relevant files by name/pattern
  (no content parsing). Picks the primary compose file; extra compose files are
  detected but **not merged** (warning emitted).
- `src/repo_analyzer/parsers/` — one module per format, each preserving source
  line ranges via `common.Located`:
  `compose.py` (ruamel.yaml, line-preserving), `dockerfile.py` (instruction-level,
  joins `\` continuations), `dotenv.py`, `nginx.py` (brace/`;` tokenizer),
  `python_settings.py` (AST → `BaseSettings` fields).
- `src/repo_analyzer/rules/kubernetes_p0.py` — **pure function**: parsed facts in,
  `AnalysisResult` out. The only place explicit facts become derived conclusions
  and unknowns become `unresolved`. No I/O here.
- `src/repo_analyzer/models.py` — Pydantic v2 schema; field order is intentional
  (fixes JSON key order). `extra="forbid"`.
- `src/repo_analyzer/reporters/` — `json_reporter.py` (canonical bytes),
  `markdown_reporter.py` (workload-centric report answering the 7 P0 questions).
- `src/repo_analyzer/analyzer.py` — orchestration; performs **all** filesystem
  reads, then calls the pure rule engine.

## Entry points

- **CLI:** `repo-analyzer analyze` → `src/repo_analyzer/cli.py:main` (argparse).
- **Library:** `repo_analyzer.analyzer.analyze_repository(repository_path, profile="kubernetes-p0", git_ref=None) -> AnalysisResult`.
- **Runtime-agnostic wrapper:** `integrations/tool.py:analyze_repository(...) -> dict`
  returns `{"ok": True, "analysis": {...}}` or `{"ok": False, "error": {...}}`
  (never raises for expected errors). Schema: `integrations/tool-schema.json`
  (OpenAI-compatible function tool).
- **Agent Skill:** `skills/kubernetes-repository-analyzer/SKILL.md` — thin layer;
  must call the Python tool, report only what it returns, preserve confidence
  labels, and on failure report the failed step (never substitute generic K8s
  knowledge).

## Result sections

`schema_version`, `repository`, `detected_files`, `components`,
`workload_mappings`, `networking`, `configuration`, `secrets`, `storage`,
`startup_order`, `health_checks`, `build_time_constraints`,
`unresolved_operational_inputs`, `warnings`, `unsupported_constructs`.

## Commands

```bash
uv sync                                   # Python >=3.12, deps: pydantic, ruamel.yaml
uv run pytest                             # 45 tests, fully offline
uv run repo-analyzer analyze \
  --repo tests/fixtures/full-stack-fastapi \
  --profile kubernetes-p0 \
  --json-output ./output/analysis.json \
  --markdown-output ./output/report.md
```

Committed example outputs live in `examples/`. `output/` is gitignored.

## Tests / fixtures

Test-first where practical. Coverage: per-parser unit tests, rule/golden
integration, byte-determinism, "target repo not modified", and
missing-file / bad-profile / malformed-input / unsupported-construct.
**No test touches the network.** Golden fixture
`tests/fixtures/full-stack-fastapi/` is a pinned local copy of the P0-relevant
files from `fastapi/full-stack-fastapi-template` @
`4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8`. When fixing a bug, add a failing test
first.

## Not tracked in git

Pre-existing agent-memory infra at the repo root (`.agents/`, `.claude/`,
`data/`, `skills-lock.json`) plus `.venv/` and `output/` are gitignored — they are
not part of this tool.

## Environment & troubleshooting

This folder's mount blocks file deletion (`rm`/`unlink` fail), which notably
makes `git commit` fail on a stale `.git/index.lock`. Fix and other environment
notes: see [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).
