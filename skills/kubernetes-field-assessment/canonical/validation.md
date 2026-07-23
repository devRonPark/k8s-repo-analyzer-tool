# Package Validation

This Agent Runtime Skill Package is valid only when:

- the canonical package defines the workflow, evidence rules, analysis start
  card semantics, candidate recommendation contract, confirmed-scope Evidence
  Result contract, Migration Diagnosis Package rubric, and validation criteria;
- runtime adapters for Codex, Claude Code, and OpenCode reference `canonical/`
  files;
- runtime adapters preserve Evidence Result semantics;
- runtime adapters do not change no-invention or Secret masking behavior.

Use the repository validation script to check the package structure before
claiming the package foundation is complete.
