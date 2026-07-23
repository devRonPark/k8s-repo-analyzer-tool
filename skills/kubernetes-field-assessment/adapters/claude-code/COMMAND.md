# Claude Code Adapter

Use the canonical Agent Runtime Skill Package in `../../canonical/`.

Load the canonical workflow and rules before running the field assessment:

- `../../canonical/workflow.md`
- `../../canonical/evidence-rules.md`
- `../../canonical/intake.md`
- `../../canonical/diagnosis-package-rubric.md`
- `../../canonical/validation.md`

This adapter may define Claude Code command wording, but it must preserve Evidence Result
semantics, Secret masking, no-invention behavior, and the
Migration Diagnosis Package rubric from the canonical package.
