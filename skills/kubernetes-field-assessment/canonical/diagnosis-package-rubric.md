# Migration Diagnosis Package Rubric

The Migration Diagnosis Package is written for a Kubernetes migration engineer
and customer/application stakeholders. Use field-work language by default.
Internal terms may appear only in machine-readable details or advanced
appendices.

## Required Sections

- selected application and why it was selected;
- source-confirmed build, runtime, port, configuration, Secret candidate,
  dependency, storage, health, and deployment-hint facts;
- values that remain unknown and why the repository cannot decide them;
- migration risks and source conflicts;
- repository/user-input conflicts;
- follow-up questions for the customer or application team;
- evidence appendix with file and line references or Evidence Result IDs.

The package must not add claims that are absent from the Evidence Result.
The machine-readable section and traceability contract lives in
`canonical/migration-diagnosis-package.json`.
