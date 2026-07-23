# Confirmed Scope To Evidence Result

After the user confirms an application target and analysis scope, build an
Evidence Core request from that confirmed scope. The Evidence Core request must
preserve the target candidate, repository root, path filters, analysis topics,
and user input context.

## Required Separation

Evidence Result output keeps these boundaries separate:

- source-confirmed facts from repository evidence;
- user input context supplied during the interview;
- Required Inputs for values the repository cannot decide;
- conflicts between source facts and user input context;
- Secret masking events;
- no-invention rules applied to operational values.

Do not turn user input context into repository facts. Do not invent operational
values such as replicas, resource requests, ingress host, StorageClass, or
production Secret values. When a source fact and user input context disagree,
report a conflict or follow-up item instead of choosing a winner.

The machine-readable contract lives in
`canonical/confirmed-scope-evidence-result.json`.
