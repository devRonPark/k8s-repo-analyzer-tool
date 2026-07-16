# Design — Kubernetes P0 Repository Analyzer

## Goal

Read an application source repository and give an engineer starting a Kubernetes
migration the **structural P0 context** they need, as a **deterministic** artifact.
The same repository content always produces byte-identical JSON.

The LLM (the Agent Skill) never extracts repository facts. All facts come from
Python parsers and explicit rules. The Skill only detects intent, calls the tool,
validates the structured result, and explains it.

## Layering

```
inventory  ->  parsers  ->  rules (kubernetes_p0)  ->  models  ->  reporters
```

* **inventory** — discovers relevant files by well-known names / patterns. No
  parsing of contents; just "what exists and what kind is it".
* **parsers** — one module per format. Each returns a small structured object and
  preserves *source line ranges* for every value it extracts. Parsers never guess:
  a construct they do not understand becomes an `UnsupportedConstruct`, never a
  silent skip.
* **rules/kubernetes_p0** — pure function: parsed facts in, `AnalysisResult` out.
  This is where `explicit` facts are combined into `derived` conclusions and where
  operational unknowns are recorded as `unresolved`. No I/O, no parsing here.
* **models** — Pydantic v2 models. Field order is fixed, which fixes JSON key order.
* **reporters** — `json_reporter` (canonical, deterministic bytes) and
  `markdown_reporter` (workload-centric human report).

`analyzer.py` wires these together; `cli.py` is a thin argparse front-end.

There are no cycles: `rules` imports `models`; `parsers` import `models`;
`analyzer` imports everything below it; nothing lower imports `analyzer`.

## Evidence

Every primary finding carries evidence: repo-relative `path`, a structural
`selector` (YAML path like `$.services.backend.healthcheck`, a Dockerfile
instruction like `CMD`, a Python symbol like `Settings.POSTGRES_PORT`, an env var
name, or an Nginx directive), and `start_line` / `end_line`.

Line numbers are **never hardcoded in rules**. Parsers locate the structural
target first (a YAML node, a Dockerfile instruction, an AST node, a directive)
and report the real line range of that node.

## Confidence

* `explicit` — stated directly in a file.
* `derived` — a conclusion combining two or more explicit facts. Every source is
  linked in `evidence`.
* `unresolved` — cannot be decided from the repository alone. Records *why*, the
  *input needed*, and states that no default value was invented.

Values the tool refuses to invent (always `unresolved`): replica count,
CPU/Memory requests & limits, PVC size, StorageClass, IngressClass, HPA triggers,
PodDisruptionBudget, DB HA & backup policy.

## Determinism

* No timestamps, durations, temp paths, absolute paths, random IDs, or unordered
  `set` output ever reach the result.
* Paths are stored repo-relative with `/` separators.
* Every list is sorted by an explicit, documented key before serialization.
* JSON is written UTF-8, `indent=2`, `ensure_ascii=False`, with fixed key order
  from the Pydantic field order (no `sort_keys` needed, order is intrinsic).
* Repository metadata uses only an optional caller-supplied `git_ref`; the tool
  does not shell out to `git`, so nothing environment-dependent leaks in.

## Scope

Only the `kubernetes-p0` profile. The tool does **not** generate Kubernetes/Helm
manifests, guess resource usage, or do P1/P2 deep analysis. Out-of-scope work is
reported, never silently added. The analyzed repository is only ever read.

## Compose overrides

`compose.override.yml` / `docker-compose.override.yml` are development overlays.
P0 analyzes the canonical base compose file and records a warning that overrides
are detected but **not** merged, rather than mixing dev-only ports/services into
the production topology.
