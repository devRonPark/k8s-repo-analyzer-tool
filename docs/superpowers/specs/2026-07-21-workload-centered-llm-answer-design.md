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

Primary-source fact check: a Kubernetes migration handoff should capture both
how each workload image is produced and how each workload runs. These should not
be collapsed into one overloaded `build method` term. Use an Image Build Profile
for image production facts and a Runtime Deployment Profile for start, port,
config, storage, probe, lifecycle, and relationship facts. See
`docs/research/2026-07-21-workload-build-runtime-profile-fact-check.md`.

Additional primary-source corrections:

- Kubernetes workload controller candidates, such as Deployment, StatefulSet,
  and Job, must be separated from companion object candidates such as Service,
  PVC, ConfigMap, Secret, Ingress, or Gateway.
- A container port, Dockerfile `EXPOSE`, Compose `ports`, and a Kubernetes
  Service port are related evidence, but they do not mean the same thing.
- Service type, IngressClass, host, TLS, and Gateway policy are unresolved
  unless existing repository facts declare them.
- ConfigMap candidates should represent non-confidential configuration keys and
  how workloads consume them. Secret candidates should name sensitive keys and
  consumers, not secret values.
- Dockerfile or Compose health checks can inform Probe Candidates, but they
  should not be copied as final Kubernetes startup/readiness/liveness probes
  without semantic review.
- A generic health check is not automatically both readiness and liveness.
- Compose `depends_on` is startup-order evidence. It is not by itself proof of
  production readiness semantics or runtime traffic.
- Database persistence evidence does not by itself imply that an application
  workload needs a PVC.
- Compose profiles and ignored override files can change the effective service
  set, so they must be surfaced as coverage caveats when present.

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
   - Include the workload role and language/runtime/framework when present in
     analyzer facts.
   - Include the Image Build Profile when present: build tool, image build path
     or context, Dockerfile/buildpack/Jib/prebuilt-image source, build command,
     produced artifact, and base or builder image.
   - Include the Runtime Deployment Profile when present: image reference, start
     command and arguments, exposed or listening container ports, published or
     Service-facing ports, Exposure Candidates, configuration candidates, Secret
     candidates, persistent volumes or mounts, Probe Candidates, lifecycle or
     init behavior, and Kubernetes workload controller candidate.
   - Mark derived Kubernetes mappings as Workload Candidates, not final
     manifests.
   - For missing fields, say the value was not detected from repository facts
     instead of inventing it.
   - Include only compact primary file references when they materially help
     verify a workload fact, such as the Compose service file, Dockerfile, or
     dotenv/config file.
3. `## 워크로드 간 관계`
   - Explain dependencies between workloads using natural language and compact
     arrows where helpful, for example `frontend -> backend`,
     `backend -> db`, `worker -> broker/cache/db`, or
     `prestart job -> db`.
   - Use only explicit relationships or strong repository-derived relationship
     candidates. Allowed sources are component runtime dependencies, Compose
     service dependency/startup facts, configuration references, ports, and
     deterministic migration answers.
   - When using Compose `depends_on`, phrase it as startup-order evidence, not
     as a final Kubernetes dependency mechanism.
   - Do not infer relationships from generic application architecture patterns
     alone.
   - If relationships are not detected, say that the repository facts do not
     expose enough relationship evidence.
4. `## Kubernetes 이관 관점`
   - Explain how the workloads would likely be split into Kubernetes objects:
     workload controller candidates first, then companion object candidates such
     as Service, PVC, ConfigMap, Secret, Ingress, or Gateway.
   - Keep all object mappings as candidates, and do not describe Services,
     PVCs, ConfigMaps, Secrets, Ingresses, or Gateways as workloads.
   - Use conservative controller wording: Deployment candidate for long-running
     stateless app/server/worker processes; StatefulSet or external managed
     service candidate for stateful services with persistent storage or stable
     identity evidence; Job candidate for one-off migration/seed/prestart work;
     init container candidate only when the evidence points to app-Pod startup
     gating.
   - Do not give a Service candidate to a background worker solely because it is
     a workload. Require inbound port or consumer evidence.
   - Keep Service type, IngressClass, host, TLS, Gateway policy, PVC size, access
     mode, and StorageClass unresolved unless declared by repository facts.
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
- Include compact primary file references only when they materially help a
  developer verify a workload fact.
- Do not invent Kubernetes values: replica count, CPU/memory, PVC size,
  StorageClass, IngressClass, HPA, PDB, DB HA, backup policy, hosts, TLS, or
  Secret values.
- Do not turn `not_detected`, `partial`, or `unresolved` into positive claims.
- Do not claim "no external dependency" without making it a
  Scanned-Facts-Only Claim: no dependency was detected from the repository facts
  the analyzer scanned.
- Do not treat `depends_on`, Dockerfile `EXPOSE`, Compose `ports`, Dockerfile or
  Compose health checks, or declared volumes as final Kubernetes design
  decisions. Treat them as evidence for candidates that still need review.
- Do not translate one generic health check into final startup, readiness, and
  liveness probes.
- Do not infer an application PVC from datasource or database evidence alone;
  report application-local mounts separately from database/service persistence.
- Surface ignored Compose overrides, sample/documented deployment evidence, and
  unknown/inactive Compose profiles as coverage caveats when present.

## Testing

Update `tests/test_llm_tool_call_demo.py` so the prompt-contract test verifies:

- The final instruction asks for Korean workload-centered Markdown.
- The instruction includes the five required section names.
- The instruction explicitly makes the seven migration questions an internal
  coverage check rather than the final answer structure.
- The instruction requires workload details: role, language/runtime/framework,
  Image Build Profile, Runtime Deployment Profile, and Kubernetes candidate.
- The instruction requires workload relationship explanation.
- The instruction preserves warning codes, image/runtime risks, unresolved
  inputs, and no-invention rules.

Run:

- `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py`
- `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q`
- One live Python repository spot check, preferably
  `tests/fixtures/full-stack-fastapi`, to inspect whether the output reads as a
  workload-centered developer handoff.
