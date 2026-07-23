---
name: kubernetes-field-assessment
description: Run the runtime-neutral Kubernetes Migration Field Assessment workflow for repository-backed migration diagnosis.
---

# Kubernetes Field Assessment Adapter

Use the canonical Agent Runtime Skill Package in `../../canonical/`.

Before acting, read:

- `../../canonical/workflow.md`
- `../../canonical/evidence-rules.md`
- `../../canonical/intake.md`
- `../../canonical/intake-card.json`
- `../../canonical/candidate-recommendation.md`
- `../../canonical/candidate-recommendation.json`
- `../../canonical/confirmed-scope-evidence-result.md`
- `../../canonical/confirmed-scope-evidence-result.json`
- `../../canonical/migration-diagnosis-package.json`
- `../../canonical/diagnosis-package-rubric.md`
- `../../canonical/validation.md`

This adapter may only supply Codex trigger metadata. It must preserve Evidence Result
semantics, Secret masking, no-invention behavior, and the Migration
Diagnosis Package contract and rubric from the canonical package.
