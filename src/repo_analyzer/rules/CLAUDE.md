# src/repo_analyzer/rules/

Pure rule engine — no filesystem I/O. Takes parsed facts, produces `AnalysisResult`.

## Files

| File | Lines | Role |
|---|---|---|
| `__init__.py` | 0 | Package marker |
| `kubernetes_p0.py` | — | Orchestrating rule module. Runs the compose path (per-service analysis, config/secrets, startup), resolves implicit `<context>/Dockerfile`, derives container ports (incl. published-mapping fallback), then calls `java_webapp`. All compose-side confidence labeling lives here. |
| `java_webapp.py` | — | Maven/WAR rules. Enriches the matching compose component (or synthesizes one without compose): language/frameworks/build/artifact, external servlet container + profiles, context path, servlet routes, embedded vs external datastore, image build/run risks, Dockerfile↔README↔POM cross-checks, Java-specific `unresolved`. Pure; must not import `kubernetes_p0` (one-way). |

## Invariants

- Pure functions: parsed data in → `AnalysisResult` out (mutation only).
- Never invent operational values (replica, CPU, memory, PVC size → `unresolved`).
- Every `derived` finding links all source evidence.
- `java_webapp` never re-fetches facts the parsers didn't produce; it maps
  explicit Maven/servlet/Spring facts to derived Kubernetes conclusions only.
