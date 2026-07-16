# skills/

Agent Skill definitions — thin layers that detect intent, call the Python tool,
and explain results. Skills must never contain analysis logic.

## Structure

```
skills/
└── kubernetes-repository-analyzer/
    └── SKILL.md    (112 lines) — K8s migration analysis skill
```

## Invariants

- Call the Python tool; report only what it returns.
- Preserve confidence labels (`explicit` / `derived` / `unresolved`).
- On failure, report the failed step — never substitute generic K8s knowledge.
