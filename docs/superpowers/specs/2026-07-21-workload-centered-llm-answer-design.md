# Workload-Centered LLM Answer Design

## Goal

Change the live LLM final answer from a seven-question audit summary into a
workload-centered Korean narrative that helps a developer understand how the
application is composed and how it should be approached for Kubernetes
migration.

The seven migration questions remain source-of-truth coverage checks, but they
should no longer dominate the final answer structure.

## Problem

The current final answer is structurally correct, but it reads like a rigid
checklist:

- It leads with the seven migration questions instead of the application's
  runtime shape.
- It often says only "ConfigMap candidates: N" or "Secret candidates: N", which
  is hard for a developer to act on.
- It hides workload relationships such as `frontend -> backend`,
  `backend -> db`, or `prestart job -> db readiness`.
- It can make Kubernetes mapping candidates feel final unless the wording is
  carefully constrained.

For migration planning, a developer first needs to picture the application as a
set of workloads, their build/run characteristics, their ports, and their
dependencies.

## Scope

- Change only the live final-answer instruction in
  `scripts/llm_tool_call_demo.py`.
- Keep the analyzer output, JSON schema, deterministic brief renderer, and tool
  schema unchanged.
- Keep the deterministic brief as source material.
- Preserve warning codes, image/runtime risk subjects, status labels, and
  unresolved operational inputs.
- Continue prohibiting invented Kubernetes values.

## Output Contract

The live LLM final answer should be Korean Markdown with these top-level
sections:

1. `## 애플리케이션 구성 개요`
   - Explain the application as a set of runtime workloads.
   - Mention the main roles such as API, frontend, database, cache, admin tool,
     worker, or init/prestart job when those roles are present in analyzer facts.
   - Make the first paragraph conversational enough that a developer can quickly
     understand the system shape.
2. `## 워크로드 구성`
   - Describe each detected workload in a short paragraph or compact bullet
     group.
   - Include, when present in analyzer facts: role, programming language,
     runtime/framework, build tool, build method, build command, run command,
     Dockerfile/base image, exposed container ports, published ports, persistent
     volumes, and Kubernetes workload candidate.
   - Mark derived Kubernetes mappings as candidates, not final manifests.
   - For missing fields, say the value was not detected from repository facts
     instead of inventing it.
3. `## 워크로드 간 관계`
   - Explain dependencies between workloads using natural language and compact
     arrows where helpful, for example `frontend -> backend`,
     `backend -> db`, `worker -> broker/cache/db`, or
     `prestart job -> db`.
   - Use only relationships present in component runtime dependencies, Compose
     service dependency/startup facts, configuration evidence, ports, or
     deterministic migration answers.
   - If relationships are not detected, say that the repository facts do not
     expose enough relationship evidence.
4. `## Kubernetes 이관 관점`
   - Explain how the workloads would likely be split into Kubernetes objects:
     Deployment, StatefulSet, Job, Service, PVC, ConfigMap, and Secret
     candidates.
   - Keep all object mappings as candidates.
   - Include image/runtime risks and analyzer warning codes in context, with why
     they matter for migration.
5. `## 확인이 필요한 부분`
   - List unresolved operational inputs concretely.
   - Preserve `not_detected`, `partial`, and `unresolved` meanings as missing
     evidence or open decisions.
   - Include any important coverage caveats, such as ignored compose override
     files or missing deployment topology files.

## Content Rules

- The final answer should read like a developer handoff narrative, not a rigid
  seven-question report.
- The seven migration question statuses must still be represented, but they can
  be summarized in context rather than listed as numbered questions.
- Do not include raw `Evidence:` lines by default.
- Include compact file references only when they materially help a developer
  verify a workload fact.
- Do not invent Kubernetes values: replica count, CPU/memory, PVC size,
  StorageClass, IngressClass, HPA, PDB, DB HA, backup policy, hosts, TLS, or
  Secret values.
- Do not turn `not_detected`, `partial`, or `unresolved` into positive claims.
- Do not claim "no external dependency" without the qualifier that no dependency
  was detected from scanned repository facts.

## Testing

Update `tests/test_llm_tool_call_demo.py` so the prompt-contract test verifies:

- The final instruction asks for Korean workload-centered Markdown.
- The instruction includes the five required section names.
- The instruction explicitly makes the seven migration questions an internal
  coverage check rather than the final answer structure.
- The instruction requires workload details: role, language/runtime, framework,
  build tool, build method, build/run commands, Dockerfile/base image, ports,
  persistence, and Kubernetes candidate.
- The instruction requires workload relationship explanation.
- The instruction preserves warning codes, image/runtime risks, unresolved
  inputs, and no-invention rules.

Run:

- `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py`
- `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q`
- One live Python repository spot check, preferably
  `tests/fixtures/full-stack-fastapi`, to inspect whether the output reads as a
  workload-centered developer handoff.
