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

Three stack families are covered today:

- **Container/compose stacks** (e.g. FastAPI + Postgres + Nginx): compose
  services, Dockerfiles, dotenv, Nginx, Python settings.
- **Maven / Java web applications** (e.g. a WAR on an external servlet
  container): `pom.xml` (packaging, finalName, Java version, dependencies with
  scope, per-profile application servers), `web.xml` (servlets, listeners,
  mappings), and Spring application-context datasources (embedded vs external).
  This surfaces WAR packaging, the external-servlet-container dependency and its
  Maven-profile alternatives, the non-root HTTP **context path**, embedded
  (ephemeral) datastores, image-build risks (runtime server download, PID-1
  signal handling, root user), and Dockerfile↔README↔POM cross-checks
  (undefined run profile, JDK version mismatch).
- **Spring Boot / Gradle applications** (e.g. spring-petclinic): `build.gradle`
  (applied plugins with versions, Java toolchain, dependencies with
  configuration), `settings.gradle` (project name → artifact name),
  `gradle-wrapper.properties` (pinned Gradle version), and
  `application*.properties` (default vs per-profile datasources, SQL init,
  Actuator). This surfaces the **selected build system** (when both Maven and
  Gradle are present it lists both, records the choice, and how to switch — never
  "the first `pom.xml`"), the **executable Spring Boot JAR** (`bootJar` vs a plain
  `jar`, `build/libs/*.jar`, `java -jar`), the default **8080** port, the
  **H2 (default) vs external PostgreSQL/MySQL** profiles with their env vars
  classified into **ConfigMap (URL) vs Secret (user/password)** candidates,
  **`spring.sql.init`** startup initialization (idempotent, not Flyway/Liquibase),
  **Actuator** liveness/readiness probe candidates (with `/livez`,`/readyz` only
  when `add-additional-paths` is enabled), **`bootBuildImage`** OCI-image build
  without a Dockerfile, and that the **application needs no PVC** (state lives in
  the database).

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
- `--build-system`: `auto` (default) | `gradle` | `maven`. When a repo ships more
  than one build system, this forces which one is analyzed; `auto` selects
  deterministically and records the choice (and how to switch) in the result.
- `--git-ref`: optional commit/ref recorded in metadata for traceability.
- With no `--json-output`/`--markdown-output`, the JSON is written to stdout.

Try it against a committed golden fixture:

```bash
# compose stack (FastAPI + Postgres + Nginx)
uv run repo-analyzer analyze \
  --repo tests/fixtures/full-stack-fastapi \
  --json-output ./output/analysis.json \
  --markdown-output ./output/report.md

# Maven WAR on an external servlet container (jpetstore-6)
uv run repo-analyzer analyze \
  --repo tests/fixtures/jpetstore-6 \
  --json-output ./output/jpetstore.json \
  --markdown-output ./output/jpetstore.md

# Spring Boot + Gradle (spring-petclinic; both build systems present, analyze Gradle)
uv run repo-analyzer analyze \
  --repo tests/fixtures/spring-petclinic \
  --build-system gradle \
  --json-output ./output/spring-petclinic.json \
  --markdown-output ./output/spring-petclinic.md
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
`runtime_dependencies`, `startup_order`, `health_checks`,
`build_time_constraints`, `container_image`, `unresolved_operational_inputs`,
`warnings`, `unsupported_constructs`.

`runtime_dependencies` lists external services / datastores (or an embedded,
ephemeral one). `container_image` reports image build/run facts and risks
(base image, build/start command, runtime server download, signal handling,
root user).

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
nginx, python-settings, maven, webxml, spring-xml, **gradle, spring-properties,
sql-init**), three rule/golden-fixture integration suites (compose stack, Maven
WAR, **Spring Boot + Gradle**), category-level generalization tests (implicit
Dockerfile resolution, published-port fallback, Maven-without-compose,
**build-system selection, Spring Boot facts on a synthetic non-fixture repo**),
a **k8s-manifest ground-truth comparison** (the analyzer's source-only output vs
spring-petclinic's own `k8s/` manifests), byte-level determinism tests, "target
repo is never modified" tests, and missing-file / bad-profile / malformed-input /
unsupported-construct tests. All fixtures are local; **no test touches the
network**.

Golden fixtures are pinned local copies of the P0-relevant files:

- `tests/fixtures/full-stack-fastapi/` from
  [`fastapi/full-stack-fastapi-template`](https://github.com/fastapi/full-stack-fastapi-template)
  @ `4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8`.
- `tests/fixtures/jpetstore-6/` from
  [`mybatis/jpetstore-6`](https://github.com/mybatis/jpetstore-6)
  @ `5a7cc780505b88a60779b3e3c0a50b0e404cfb2d` (`mvnw`/`mvnw.cmd` are minimal
  placeholders — only their presence drives build-tool detection).
- `tests/fixtures/spring-petclinic/` from
  [`spring-projects/spring-petclinic`](https://github.com/spring-projects/spring-petclinic)
  @ `f182358d02e4a68e52bdbabf55ca7800288511e7` (Spring Boot 4.x; ships **both**
  `build.gradle` and `pom.xml`; `gradlew`/`mvnw` are presence-only placeholders;
  includes the upstream `k8s/` manifests as ground-truth reference only — the
  analyzer never reads them).

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
│   ├── parsers/               # compose, dockerfile, dotenv, nginx, python_settings,
│   │                          #   maven, webxml, spring_xml, xml_source
│   ├── rules/                 # kubernetes_p0 (engine) + java_webapp (Maven/WAR rules)
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
