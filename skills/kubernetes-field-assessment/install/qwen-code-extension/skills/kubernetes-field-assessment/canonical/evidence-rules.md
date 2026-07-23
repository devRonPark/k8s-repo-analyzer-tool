# Evidence Rules

Repository facts must come from the Evidence Core or an equivalent checked
repository evidence boundary. User answers from the analysis start card are
context, not repository facts.

## Required Semantics

- Preserve Evidence Result semantics for evidence references, checked claims,
  Required Inputs, Secret masking, and conflicts.
- Apply no-invention behavior: do not invent operational values such as
  replicas, resource requests, PVC sizes, StorageClass, IngressClass, HPA, PDB,
  production Secret values, database HA, or backup policy.
- Keep source-confirmed facts separate from user input context.
- Report repository/user-input conflicts instead of silently choosing one.
- Treat unknown values as follow-up inputs for customer or application-team
  confirmation.

## Secret Handling

Secret masking applies before values reach the Migration Diagnosis Package.
Secret key names may be reported when useful; Secret values must not be copied.
