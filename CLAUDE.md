# CLAUDE.md

Project memory for **k8s-repo-analyze-agent** (`repo-analyzer`).

## What this project is

A **deterministic** tool that reads an application source repository and emits the
**P0 structural context** an engineer needs to start a Kubernetes migration. Same
repository content → **byte-identical JSON**. Facts are extracted by Python
parsers with source-line evidence; **no LLM inspects the repo**. An Agent Skill is
only a thin layer that detects intent, calls the tool, and explains the result.

Only the `kubernetes-p0` profile exists. Two stack families are supported:
compose/Dockerfile stacks (FastAPI-style) and **Maven / Java web applications**
(WAR on an external servlet container — pom.xml, web.xml, Spring datasources).
**Non-goals** (do not add without a request): Kubernetes/Helm manifest
generation, resource sizing, replica/PVC/HPA/PDB/StorageClass/IngressClass
decisions, full business-code or security analysis, P1/P2 depth.

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
inventory  ->  parsers  ->  rules/{kubernetes_p0,java_webapp}  ->  models  ->  reporters
```

- `src/repo_analyzer/inventory.py` — discover P0-relevant files by name/pattern
  (no content parsing). Picks the primary compose file; extra compose files are
  detected but **not merged** (warning emitted). Also detects `pom.xml`,
  `web.xml`, Spring-context XML candidates, README, and build wrappers (`mvnw`).
- `src/repo_analyzer/parsers/` — one module per format, each preserving source
  line ranges via `common.Located`:
  `compose.py` (ruamel.yaml, line-preserving), `dockerfile.py` (instruction-level,
  joins `\` continuations), `dotenv.py`, `nginx.py` (brace/`;` tokenizer),
  `python_settings.py` (AST → `BaseSettings` fields), and for Java:
  `xml_source.py` (line-preserving SAX XML tree), `maven.py` (pom.xml: packaging,
  finalName, java version, deps+scope, profiles→app servers), `webxml.py`
  (servlets/listeners/mappings), `spring_xml.py` (embedded vs external datasource).
- `src/repo_analyzer/rules/kubernetes_p0.py` — **pure function**: parsed facts in,
  `AnalysisResult` out. The only place explicit facts become derived conclusions
  and unknowns become `unresolved`. No I/O here. Runs the compose path, then
  delegates Maven/WAR analysis to `rules/java_webapp.py:analyze_java_webapp`
  (also pure; enriches the matching component or synthesizes one without compose).
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
`runtime_dependencies`, `startup_order`, `health_checks`,
`build_time_constraints`, `container_image`, `unresolved_operational_inputs`,
`warnings`, `unsupported_constructs`.

(`runtime_dependencies` = external/embedded datastores & brokers;
`container_image` = image build/run facts & risks. `Component` also carries a
workload summary: `language`, `frameworks`, `build_tool`, `build_command`,
`build_artifact`, `packaging`, `application_server`, `context_path`,
`runtime_dependencies`.)

## Commands

```bash
uv sync                                   # Python >=3.12, deps: pydantic, ruamel.yaml
uv run pytest                             # 79 tests, fully offline
uv run repo-analyzer analyze \
  --repo tests/fixtures/full-stack-fastapi \
  --profile kubernetes-p0 \
  --json-output ./output/analysis.json \
  --markdown-output ./output/report.md
# Maven WAR category:
uv run repo-analyzer analyze --repo tests/fixtures/jpetstore-6 \
  --json-output ./output/jpetstore.json --markdown-output ./output/jpetstore.md
```

Committed example outputs live in `examples/` (fastapi + jpetstore). `output/`
is gitignored.

## Tests / fixtures

Test-first where practical. Coverage: per-parser unit tests (incl. maven,
webxml, spring-xml), two golden integration suites (compose + Maven WAR),
category generalization tests (implicit Dockerfile, published-port fallback,
Maven-without-compose), byte-determinism, "target repo not modified", and
missing-file / bad-profile / malformed-input / unsupported-construct.
**No test touches the network.** Golden fixtures are pinned local copies of the
P0-relevant files: `tests/fixtures/full-stack-fastapi/` @
`4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8`; `tests/fixtures/jpetstore-6/`
(`mybatis/jpetstore-6`) @ `5a7cc780505b88a60779b3e3c0a50b0e404cfb2d` (mvnw
files are placeholders — presence only). When fixing a bug, add a failing test
first.

## Directory index

Each directory has its own `CLAUDE.md` with a file-level index. Read the
relevant directory's `CLAUDE.md` instead of scanning the entire codebase.

| Directory | CLAUDE.md | What it covers |
|---|---|---|
| `src/repo_analyzer/` | [`src/repo_analyzer/CLAUDE.md`](src/repo_analyzer/CLAUDE.md) | Core package — analyzer, CLI, inventory, models, sub-packages |
| `src/repo_analyzer/parsers/` | [`src/repo_analyzer/parsers/CLAUDE.md`](src/repo_analyzer/parsers/CLAUDE.md) | Per-format parsers (Compose, Dockerfile, dotenv, Nginx, Python AST, Maven, web.xml, Spring XML) |
| `src/repo_analyzer/reporters/` | [`src/repo_analyzer/reporters/CLAUDE.md`](src/repo_analyzer/reporters/CLAUDE.md) | JSON and Markdown output formatters |
| `src/repo_analyzer/rules/` | [`src/repo_analyzer/rules/CLAUDE.md`](src/repo_analyzer/rules/CLAUDE.md) | Pure rule engine (`kubernetes_p0.py`, `java_webapp.py`) |
| `tests/` | [`tests/CLAUDE.md`](tests/CLAUDE.md) | Test files, fixtures, coverage map |
| `integrations/` | [`integrations/CLAUDE.md`](integrations/CLAUDE.md) | Runtime-agnostic tool wrapper and schema |
| `docs/` | [`docs/CLAUDE.md`](docs/CLAUDE.md) | Operational docs (troubleshooting) |
| `examples/` | [`examples/CLAUDE.md`](examples/CLAUDE.md) | Committed reference outputs (golden JSON + report) |
| `skills/` | [`skills/CLAUDE.md`](skills/CLAUDE.md) | Agent Skill definitions |

## Not tracked in git

Pre-existing agent-memory infra at the repo root (`.agents/`, `.claude/`,
`data/`, `skills-lock.json`) plus `.venv/` and `output/` are gitignored — they are
not part of this tool.

## Git workflow

### Branch strategy

**Never commit directly to `main`.** All work happens on a feature branch.

```
git checkout -b <type>/<short-description>
```

Branch naming follows the commit type prefix:

- `feat/add-toml-parser`
- `fix/dockerfile-continuation-line`
- `refactor/split-rule-engine`
- `test/determinism-edge-cases`
- `docs/update-readme-commands`
- `chore/bump-pydantic-v2`

Keep the description short (2–4 words, kebab-case). One logical change per
branch. Merge back to `main` via PR (or fast-forward if solo) after all tests
pass.

### Commit message convention

Follow **Conventional Commits** in imperative mood, present tense.

```
<type>(<scope>): <subject>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`, `perf`.

Scope is the module or area touched — e.g. `parser`, `compose`, `dockerfile`,
`rules`, `models`, `cli`, `reporter`, `inventory`. Omit scope only when the
change is truly cross-cutting.

Examples:

```
feat(parser): add TOML parser with source-line tracking
fix(compose): handle unquoted port values in short syntax
test(rules): add determinism assertion for networking section
refactor(models): extract Evidence into standalone module
docs(cli): document --git-ref flag usage
chore: upgrade ruamel.yaml to 0.18
```

Rules:

- Subject line ≤ 72 characters, no trailing period.
- Imperative mood ("add", not "added" or "adds").
- No extra content such as "Generated with Claude Code" or author attributions.
- If a body is needed, separate it from the subject with a blank line. Explain
  **why**, not what (the diff shows what).
- For breaking changes, add `!` after the scope: `feat(models)!: rename Evidence.selector to Evidence.path`.

### When to commit

- **Atomic commits.** Each commit is one logical unit of change — a single
  feature sub-task, a single bug fix, or a single refactor. Do not bundle
  unrelated changes.
- **Commit after each verification step passes.** When a step in the task plan
  passes its tests, commit before moving to the next step.
- **Commit before switching context.** If you need to change direction or start
  a different sub-task, commit current passing work first.
- **Do not commit broken code.** Every commit on the branch should leave tests
  passing (`uv run pytest`). If tests fail, fix before committing.
- **Split by concern, not by file.** If one logical change touches three files,
  that is one commit. If one file has two unrelated changes, that is two commits
  (stage with `git add -p`).

## Environment & troubleshooting

This folder's mount blocks file deletion (`rm`/`unlink` fail), which notably
makes `git commit` fail on a stale `.git/index.lock`. Fix and other environment
notes: see [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).
