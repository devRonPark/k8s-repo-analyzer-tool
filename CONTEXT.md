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

### Workload Candidate

A Kubernetes workload controller shape that the analyzer can propose from repository evidence, such as Deployment, StatefulSet, Job, or init container. A workload candidate is not a final manifest decision.

### Companion Object Candidate

A non-workload Kubernetes object that may be needed to support a workload candidate, such as a Service, PVC, ConfigMap, Secret, Ingress, or Gateway. A companion object candidate is not a workload.

### Workload Relationship

A dependency or interaction between workload candidates that is backed by explicit repository facts or strong repository-derived evidence, such as service startup order, runtime dependency facts, configuration references, or port-facing service roles.

### Workload Build And Runtime Profile

The repository-backed handoff view for one workload, combining its Image Build Profile and Runtime Deployment Profile so a developer can understand both how the runnable image is produced and how the workload starts and operates.

### Image Build Profile

The repository-backed facts that explain how a workload image is produced, such as build tool, image build path or context, Dockerfile/buildpack/Jib/prebuilt-image source, build command, produced artifact, and base or builder image.

### Runtime Deployment Profile

The repository-backed facts that explain how a workload runs in Kubernetes, such as image reference, start command and arguments, ports, configuration, Secret candidates, volumes, probes, lifecycle or init behavior, workload candidate, and workload relationships.

### Exposure Candidate

A repository-backed guess about how a workload is reached over the network, such as a container port, Service target port, Service candidate, Ingress or Gateway need. An exposure candidate is separate from the workload controller candidate.

### Probe Candidate

A repository-backed health or readiness signal that may inform Kubernetes startup, readiness, or liveness probes. A probe candidate requires semantic review before becoming a final probe configuration.

### Scanned-Facts-Only Claim

A negative statement that is limited to the repository facts the analyzer scanned. For example, "no external dependency was detected" does not mean the application has no external dependency.

### Source Conflict

A disagreement between two repository-backed facts, such as a Kubernetes Service target port differing from an application or Compose port. Source conflicts are reported instead of one value silently replacing the other.

### Validation Gate

The structural check used to decide whether the analyzer output is complete enough for the required external repository validation. Source conflicts and skipped large candidates are reported but do not fail the gate by themselves.

### Candidate Size Limit

The maximum file size the analyzer will read for broad SQL and YAML candidate discovery. Files above this limit are not parsed and are reported as coverage gaps.
