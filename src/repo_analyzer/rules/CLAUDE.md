# src/repo_analyzer/rules/

Pure rule engine — no filesystem I/O. Takes parsed facts, produces `AnalysisResult`.

## Files

| File | Lines | Role |
|---|---|---|
| `__init__.py` | 0 | Package marker |
| `kubernetes_p0.py` | 793 | The only rule module. Combines explicit facts into derived conclusions; marks unknowns as `unresolved`. All confidence labeling happens here. |

## Invariants

- Pure function: parsed data in → `AnalysisResult` out.
- Never invent operational values (replica, CPU, memory, PVC size → `unresolved`).
- Every `derived` finding links all source evidence.
