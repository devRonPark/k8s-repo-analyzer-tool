---
name: kubernetes-repository-analyzer
description: >-
  Use when existing automation explicitly requires the deterministic repo-analyzer
  compatibility workflow for Kubernetes migration analysis, or the user invokes
  "/analyze-k8s-repo PATH". Do not use for new general repository assessments,
  Dockerfile syntax, Kubernetes concepts, application refactoring, or manifest review.
---

# Kubernetes Repository Analyzer

This is the **compatibility skill** for the legacy `repo-analyzer analyze`
workflow. Use the `repository-assessment assess` product path for new repository
assessment work; do not silently substitute this skill for it.

This skill is a **thin wrapper** around a deterministic Python analysis tool. It
does not read or reason about repository files itself. Its only job is to detect
the intent, run the tool, validate the tool's structured output, and explain that
output to the user in workload terms. Every fact you state must come from the
tool's JSON. You must not add Kubernetes "facts" the tool did not return.

## When to run

Run the analyzer only when the user explicitly requests the compatibility analyzer
or types `/analyze-k8s-repo <repository-path>`. For a new general Kubernetes
repository assessment, direct the user to `repository-assessment assess` instead.

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
