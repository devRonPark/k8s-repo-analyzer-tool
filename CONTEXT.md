# Context

## Glossary

### Source Coverage

The set of repository source classes the analyzer did or did not find, such as build files, application config, Dockerfiles, Compose files, SQL files, Kubernetes manifests, README files, and web descriptors.

### Migration Question

One of the seven Kubernetes migration overview questions the analyzer answers from deterministic repository evidence.

### Basis

The source-backed facts that support a migration question answer. A basis can point to line-located evidence when the underlying parser provides it.

### Missing

The repository facts or operational inputs that are required to complete an answer but are not determined by the repository.

### Primary Evidence

Evidence from files that appear to define the repository's main build, runtime, or deployment path.

### Selected Primary Evidence

Evidence from a documentation or example path that becomes primary because another repository fact, such as a README run command, explicitly selects it.

### Supplemental Evidence

Evidence from files that are useful for analysis but are not enough by themselves to define the repository's main deployment path.

### Sample Or Documented Deployment Evidence

Supplemental deployment evidence found under documentation, example, sample, demo, or test-oriented paths unless another source explicitly selects it.

### Repository Unknown

An input that Kubernetes migration requires but the repository cannot decide, such as replica count, resource sizing, ingress host, TLS, StorageClass, production Secret values, or production database endpoints.

### Source Conflict

A disagreement between two repository-backed facts, such as a Kubernetes Service target port differing from an application or Compose port. Source conflicts are reported instead of one value silently replacing the other.

### Validation Gate

The structural check used to decide whether the analyzer output is complete enough for the required external repository validation. Source conflicts and skipped large candidates are reported but do not fail the gate by themselves.

### Candidate Size Limit

The maximum file size the analyzer will read for broad SQL and YAML candidate discovery. Files above this limit are not parsed and are reported as coverage gaps.
