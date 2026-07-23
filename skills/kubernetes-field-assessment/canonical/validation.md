# Package Validation

This Agent Runtime Skill Package is valid only when:

- the canonical package defines the workflow, evidence rules, analysis start
  card semantics, candidate recommendation contract, confirmed-scope Evidence
  Result contract, Migration Diagnosis Package contract and rubric, and
  validation criteria;
- runtime adapters for Codex, Claude Code, OpenCode, and QwenCode reference
  `canonical/` files;
- runtime adapters preserve Evidence Result semantics;
- runtime adapters do not change no-invention or Secret masking behavior.

Use the repository validation script to check the package structure before
claiming the package foundation is complete.

## Five-Repository POC Validation

The POC validation matrix lives in `canonical/poc-validation.json` and fixes the
five repository snapshots used to exercise the workflow:

- `jbangdev/jbang`
- `spring-petclinic/spring-petclinic-rest`
- `ether/etherpad`
- `pypa/pipx`
- `searxng/searxng`

Each case must include canned intake answers for the analysis start card and a
recorded POC result. A valid recorded result may finish as one of three
classifications:

- `evidence_result_backed_diagnosis_package`
- `partial_result`
- `explicit_failure`

Partial results must still include a checked Evidence Result with
source-confirmed facts. Failed results must include the failed stage and reason.
A failed or partial run must not replace missing repository evidence with
generic Kubernetes advice.

The POC summary must include the per-repository classification and the next
implementation priorities implied by the results.

The repository validation script may replay recorded results for offline tests,
or it may receive a workflow runner that executes the same repository case and
canned intake against checked repository artifacts.
