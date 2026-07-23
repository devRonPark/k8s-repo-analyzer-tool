# QwenCode Adapter

Use the canonical Agent Runtime Skill Package in `../../canonical/`.

Load the canonical workflow and rules before running the field assessment:

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

## Smoke Path

Command: `/kubernetes-field-assessment <repository-path>`

First action: read `../../canonical/workflow.md` and `../../canonical/intake-card.json`,
then render the choice-first analysis start card before any repository analysis.

This adapter may define QwenCode command wording, but it must preserve Evidence Result semantics,
Secret masking, no-invention behavior, and the Migration Diagnosis Package contract and rubric
from the canonical package.
