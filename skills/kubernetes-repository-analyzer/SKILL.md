---
name: kubernetes-repository-analyzer
description: >-
  Analyze an application source repository to prepare for a Kubernetes migration.
  Use this skill when the user wants to understand a repo's structure before
  writing Kubernetes manifests — components, images/Dockerfiles, ports,
  environment variables, Secret candidates, storage, health checks, startup
  order, and which operational values cannot be decided from the repo. Trigger on
  intents like: "이 레포를 Kubernetes로 이관하기 위해 분석해줘",
  "analyze this repo for Kubernetes migration", "이 애플리케이션을 RKE2에 올리려면
  무엇이 필요한가?", "이 소스가 Rancher 위에서 실행 가능한지 분석해줘", "Docker
  Compose 구조를 Kubernetes workload로 정리해줘", "Kubernetes manifest를 만들기
  전에 레포 구조를 점검해줘", "이 레포의 포트, 환경 변수, Secret, storage를 찾아줘",
  or the explicit command "/analyze-k8s-repo <repository-path>". Do NOT trigger
  for: explaining a single Dockerfile's syntax, general Kubernetes concept
  questions, refactoring application code, or reviewing already-generated
  Kubernetes YAML.
---

# Kubernetes Repository Analyzer

This skill is a **thin wrapper** around a deterministic Python analysis tool. It
does not read or reason about repository files itself. Its only job is to detect
the intent, run the tool, validate the tool's structured output, and explain that
output to the user in workload terms. Every fact you state must come from the
tool's JSON. You must not add Kubernetes "facts" the tool did not return.

## When to run

Run the analyzer when the user asks to prepare, assess, or inventory a code
repository for a Kubernetes / RKE2 / Rancher migration, or when they explicitly
type `/analyze-k8s-repo <repository-path>`.

Do **not** run it for: single-Dockerfile syntax questions, generic Kubernetes
concept questions, application code refactoring, or reviews of already-written
Kubernetes manifests. In those cases answer normally without this tool.

## How to run

Preferred (CLI):

```bash
uv run repo-analyzer analyze \
  --repo <repository-path> \
  --profile kubernetes-p0 \
  --json-output ./output/analysis.json \
  --markdown-output ./output/report.md
```

Or call the Python function directly (any runtime):

```python
from integrations.tool import analyze_repository
result = analyze_repository("<repository-path>", profile="kubernetes-p0")
```

The function returns `{"ok": true, "analysis": {...}}` on success, or
`{"ok": false, "error": {...}}` on an expected failure.

## Behavior rules (do not deviate)

1. **Call the Python tool first.** Never infer repository facts yourself. If you
   have not run the tool, you have no facts to report.
2. **Report only what the tool returned.** Do not invent components, ports, env
   vars, images, or volumes that are absent from the JSON.
3. **Preserve the confidence labels.** Every finding is `explicit`, `derived`, or
   `unresolved`. Keep these distinctions when you explain; do not upgrade a
   `derived` or `unresolved` item into a stated fact.
4. **Never guess operational values.** replica count, CPU/memory, PVC size,
   StorageClass, IngressClass, HPA, PodDisruptionBudget, DB HA/backup — these
   live under `unresolved_operational_inputs`. Present them as open questions
   with the input each one needs. Do not supply defaults.
5. **On failure, report the failure.** If the tool returns `ok: false` or a
   non-empty `unsupported_constructs`, tell the user exactly what failed, why,
   and which file to check. Do **not** substitute generic Kubernetes knowledge
   for a failed analysis step.
6. **Explain workload-first.** Organize the answer around components and their
   Kubernetes workload candidates, not around a file-by-file dump.

## How to explain the result

Read these sections from `analysis` and narrate them per component:

- `components` + `workload_mappings` — what each component is and its Kubernetes
  workload candidate (Deployment/StatefulSet/Job/Service).
- `networking` — container ports and ingress host candidates.
- `storage` — what must be persisted (PVC candidates).
- `configuration` + `secrets` — ConfigMap and Secret keys.
- `startup_order` + `health_checks` — what must run first and how readiness is
  checked.
- `build_time_constraints` — values baked at image build time (e.g. a frontend
  API URL) that cannot be changed via runtime config.
- `unresolved_operational_inputs` — decisions the repo cannot make; surface these
  as the user's next questions.
- `warnings` + `unsupported_constructs` — caveats and anything the parser could
  not handle.

Suggested per-component shape:

```text
Backend
- Build: backend/Dockerfile (context .)
- Runtime: FastAPI, workers=4
- Port: 8000
- Depends on: db (healthy), prestart (completed)
- Config/Secret: POSTGRES_* / SECRET_KEY, POSTGRES_PASSWORD
- Kubernetes mapping: Deployment + ClusterIP Service
- Unresolved: replica count, CPU, memory
```

End by listing the `unresolved_operational_inputs` as the concrete decisions the
user must make before manifests can be written.
