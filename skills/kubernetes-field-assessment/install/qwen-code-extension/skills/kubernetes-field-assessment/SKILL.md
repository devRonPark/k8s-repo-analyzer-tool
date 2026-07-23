---
name: kubernetes-field-assessment
description: Use when assessing an application source repository for Kubernetes migration in Qwen Code, especially for repository-backed field assessment, Evidence Result review, or Migration Diagnosis Package output.
---

# Kubernetes Field Assessment

Use the bundled canonical Agent Runtime Skill Package files in `canonical/`.
Read the required files before repository analysis:

- `canonical/workflow.md`
- `canonical/evidence-rules.md`
- `canonical/intake.md`
- `canonical/intake-card.json`
- `canonical/candidate-recommendation.md`
- `canonical/candidate-recommendation.json`
- `canonical/confirmed-scope-evidence-result.md`
- `canonical/confirmed-scope-evidence-result.json`
- `canonical/migration-diagnosis-package.json`
- `canonical/diagnosis-package-rubric.md`
- `canonical/validation.md`

## Workflow

1. Render the choice-first analysis start card from `canonical/intake-card.json`.
2. Run the cheap repository scan and recommend application candidates using `canonical/candidate-recommendation.json`.
3. Confirm the target and scope with the user.
4. Build the confirmed-scope Evidence Core request from `canonical/confirmed-scope-evidence-result.json`.
5. Produce an Evidence Result that separates repository facts, user input context, required inputs, conflicts, and secret masking events.
6. Write the Migration Diagnosis Package using `canonical/migration-diagnosis-package.json` and `canonical/diagnosis-package-rubric.md`.

Preserve Evidence Result semantics, Secret masking, no-invention behavior, and
the Migration Diagnosis Package contract. Do not generate Kubernetes manifests,
replica counts, resource sizing, IngressClass, StorageClass, HPA, PDB, or
production Secret values unless they are source-confirmed facts.

For package self-validation or regression review, read
`canonical/poc-validation.json` with `canonical/validation.md`.
