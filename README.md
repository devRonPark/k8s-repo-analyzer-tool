# repo-analyzer — Kubernetes P0 Repository Analyzer

A **deterministic** tool that reads an application source repository and produces
the **P0 structural context** an engineer needs to start a Kubernetes migration.

The same repository content always produces **byte-identical JSON**. Facts are
extracted by Python parsers with source-line evidence — no LLM inspects the repo.
An optional Agent Skill only detects intent, calls this tool, and explains the
result. See [`DESIGN.md`](./DESIGN.md) for the rationale.

> Scope: the `kubernetes-p0` profile only. This tool does **not** generate
> Kubernetes/Helm manifests, guess resource sizing, or do P1/P2 analysis.

## What it analyzes

Application components & service topology, images & Dockerfiles, build
context/args, run command/entrypoint/worker count, container ports & exposed
hosts, environment variables, Secret candidates, volumes & persistent data,
health checks, service dependencies & startup order, DB migration/init tasks,
whether the frontend API URL is build-time or runtime, Kubernetes workload
drafts, and — importantly — the operational inputs that **cannot** be decided
from the repository.

Every finding is labeled:

- `explicit` — stated directly in a file.
- `derived` — a conclusion combining ≥2 explicit facts (all sources linked).
- `unresolved` — cannot be decided from the repo; records why, the input needed,
  and that no default was invented.

Values the tool refuses to guess: replica count, CPU/memory, PVC size,
StorageClass, IngressClass, HPA, PodDisruptionBudget, DB HA/backup.

## Requirements

- Python ≥ 3.12
- [`uv`](https://docs.astral.sh/uv/)

## Install

```bash
uv sync
```

This creates `.venv` and installs the package (editable) plus dev dependencies.

## Usage (CLI)

```bash
uv run repo-analyzer analyze \
  --repo ./target-repository \
  --profile kubernetes-p0 \
  --json-output ./output/analysis.json \
  --markdown-output ./output/report.md
```

- `--repo` (required): path to the repository (read-only; never modified).
- `--profile`: defaults to `kubernetes-p0` (the only supported profile).
- `--git-ref`: optional commit/ref recorded in metadata for traceability.
- With no `--json-output`/`--markdown-output`, the JSON is written to stdout.

Try it against the committed golden fixture:

```bash
uv run repo-analyzer analyze \
  --repo tests/fixtures/full-stack-fastapi \
  --profile kubernetes-p0 \
  --json-output ./output/analysis.json \
  --markdown-output ./output/report.md
```

Committed example outputs live in [`examples/`](./examples/).

## Usage (Python / any agent runtime)

```python
from integrations.tool import analyze_repository

result = analyze_repository("./target-repository", profile="kubernetes-p0")
if result["ok"]:
    analysis = result["analysis"]        # JSON-safe dict, full schema
else:
    print(result["error"])               # structured error, never a raise
```

The OpenAI-compatible function schema is in
[`integrations/tool-schema.json`](./integrations/tool-schema.json). It is
runtime-agnostic — usable from an OpenShell/Ollama loop or any function-calling
agent.

## Output schema

The JSON result contains these top-level sections (stable key order):

`schema_version`, `repository`, `detected_files`, `components`,
`workload_mappings`, `networking`, `configuration`, `secrets`, `storage`,
`startup_order`, `health_checks`, `build_time_constraints`,
`unresolved_operational_inputs`, `warnings`, `unsupported_constructs`.

Each primary finding looks like:

```json
{
  "subject": "backend.container_port",
  "value": 8000,
  "confidence": "derived",
  "kubernetes_effect": "backend Service targetPort candidate",
  "evidence": [
    { "path": "compose.yml", "selector": "$.services.backend.healthcheck.test",
      "symbol": "healthcheck.url", "start_line": 113, "end_line": 113 }
  ]
}
```

The Markdown report is workload-centric and answers the seven P0 questions:
which components exist, how they map to Kubernetes workloads, what ports/Services
are needed, what must persist, which ConfigMaps/Secrets are required, what must
run first, and what cannot be decided from the repo alone.

## Agent Skill integration

[`skills/kubernetes-repository-analyzer/SKILL.md`](./skills/kubernetes-repository-analyzer/SKILL.md)
is a thin wrapper. It triggers on migration-analysis intents (e.g. "이 레포를
Kubernetes로 이관하기 위해 분석해줘", "analyze this repo for Kubernetes migration",
or `/analyze-k8s-repo <repository-path>`) and explicitly does **not** trigger for
Dockerfile-syntax questions, generic Kubernetes questions, code refactoring, or
reviews of existing manifests.

Skill rules: call the Python tool first; report only what the tool returned;
preserve the `explicit`/`derived`/`unresolved` labels; never guess operational
values; and on failure report the failed step, cause, and file to check rather
than substituting generic Kubernetes knowledge.

## Determinism

No timestamps, durations, temp paths, absolute paths, random IDs, or unordered
sets reach the output. Paths are repo-relative POSIX. Lists are ordered. JSON is
UTF-8, 2-space indented, with intrinsic key order. Identical input → identical
bytes (enforced by a test).

## Testing

```bash
uv run pytest
```

Coverage includes: a unit test suite per parser (compose, dockerfile, dotenv,
nginx, python-settings), rule/golden-fixture integration tests, a byte-level
determinism test, a "target repo is never modified" test, and
missing-file / bad-profile / malformed-input / unsupported-construct tests. All
fixtures are local; **no test touches the network**.

The golden fixture (`tests/fixtures/full-stack-fastapi/`) is a pinned local copy
of the P0-relevant files from
[`fastapi/full-stack-fastapi-template`](https://github.com/fastapi/full-stack-fastapi-template)
at commit `4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8`.

## Project structure

```text
.
├── pyproject.toml
├── README.md
├── DESIGN.md
├── src/repo_analyzer/
│   ├── cli.py                 # argparse entry point
│   ├── models.py              # Pydantic result schema (fixed key order)
│   ├── inventory.py           # file discovery by name/pattern
│   ├── analyzer.py            # orchestration (all filesystem reads)
│   ├── parsers/               # compose, dockerfile, dotenv, nginx, python_settings
│   ├── rules/kubernetes_p0.py # pure rule engine: facts -> findings
│   └── reporters/             # json_reporter, markdown_reporter
├── skills/kubernetes-repository-analyzer/SKILL.md
├── integrations/
│   ├── tool.py                # analyze_repository(...) wrapper
│   └── tool-schema.json       # OpenAI-compatible function schema
├── examples/                  # committed golden-fixture outputs
└── tests/
    ├── fixtures/full-stack-fastapi/
    └── test_*.py
```

## Limitations & non-goals

- Compose override files are detected but **not merged** (a warning is emitted);
  analysis is based on the primary compose file.
- No manifest/Helm generation, no resource sizing, no P1/P2 analysis.
- Unsupported syntax is reported (`warnings` / `unsupported_constructs`), never
  silently ignored.
