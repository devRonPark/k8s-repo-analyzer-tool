# skills/

Agent-facing packages for repository assessment workflows.

Compatibility skills are thin layers that detect intent, call the Python tool,
and explain results. Runtime-neutral Agent Runtime Skill Packages keep canonical
workflow rules under `canonical/` and expose runtime-specific adapters under
`adapters/`.

## Structure

```
skills/
├── kubernetes-repository-analyzer/
│   └── SKILL.md    (112 lines) — K8s migration analysis skill
└── kubernetes-field-assessment/
    ├── canonical/  — runtime-neutral Field Assessment workflow and rules
    └── adapters/   — Codex, Claude Code, and OpenCode entry files
```

## Invariants

- Call the Python tool; report only what it returns.
- Preserve confidence labels (`explicit` / `derived` / `unresolved`).
- On failure, report the failed step — never substitute generic K8s knowledge.
- Runtime adapters must reference the canonical package and must not alter
  Evidence Result semantics, Secret masking, no-invention behavior, or the
  Migration Diagnosis Package rubric.
