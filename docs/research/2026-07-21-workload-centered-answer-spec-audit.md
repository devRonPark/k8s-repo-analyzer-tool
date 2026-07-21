# Workload-Centered Answer Spec Audit

Date: 2026-07-21

Target: `docs/superpowers/specs/2026-07-21-workload-centered-llm-answer-design.md`

Question: does the workload-centered final-answer spec align with primary sources for Kubernetes workload candidates, Service/Ingress exposure, ConfigMap/Secret handling, probes, volumes/PVC persistence, workload relationships, negative status claims, and sample/documentation Compose evidence?

Scope: primary sources only. External sources are official Kubernetes docs/API reference, the Compose Specification, and Docker Compose docs. Repo-local primary sources are the target spec, analyzer schema/code, and tests that define this project's own status and source-coverage semantics.

## Summary

Conclusion: the spec is directionally correct and should proceed, but the final prompt should be especially strict about candidate wording around Kubernetes objects. The highest-risk overreach is turning repository evidence into final platform design: `Deployment`, `StatefulSet`, `Job`, `Service`, `Ingress`, `PVC`, `ConfigMap`, and `Secret` should stay candidates unless an existing manifest or explicit repository deployment file already declares them.

The target spec already has the right guardrails: it says derived Kubernetes mappings are Workload Candidates, missing fields should be reported as not detected from repository facts, relationships must come from explicit or strong repository-derived evidence, operational values must not be invented, and `not_detected` must not become a positive absence claim.[^target-spec]

## Audit Findings

| Area | Assessment | Required wording discipline |
| --- | --- | --- |
| Workload candidates | Supported, with precise controller semantics. | Say `Deployment candidate` for usually stateless long-running app/server/worker Pods; say `StatefulSet candidate or external managed-service decision` when stable identity or persistent storage drives the evidence; say `Job candidate` for one-off/prestart/migration work. |
| Service/Ingress exposure | Supported, but high-risk for overclaiming. | Distinguish listening/container ports, Service-facing ports, Service type, and Ingress. A worker with no inbound port should not automatically get a Service candidate. Ingress hosts, TLS, and IngressClass remain unresolved unless explicit. |
| ConfigMap/Secret handling | Supported. | ConfigMaps are non-confidential config candidates; Secrets are confidential data candidates. Do not emit Secret values as recommended production values, even if sample values are present. |
| Probes/health checks | Supported, but do not mechanically translate. | Compose or Docker health checks are probe evidence, not final liveness/readiness/startup design. Readiness, liveness, and startup have different Kubernetes effects. |
| Volumes/PVC persistence | Supported, with a key caveat. | Declared volumes/mounts and stateful services can justify storage candidates, but datasource use alone does not imply an application PVC. PVC size/access mode/StorageClass remain unresolved. |
| Relationships/dependencies | Supported. | Compose `depends_on`, health-gated dependencies, config URLs, ports, and deterministic dependency facts can support arrows. Do not imply Kubernetes has a generic cross-Deployment startup dependency mechanism. |
| Negative claims | Supported by repo schema/tests. | Preserve `not_detected` as "not detected from scanned repository facts", not "does not exist". Preserve `partial` and `unresolved` as coverage/open-decision labels. |
| Sample/documentation Compose | Supported by repo tests and Compose docs, with nuance. | Documentation/example Compose files should be sample evidence unless selected by README/run instructions. Ignored overrides must be disclosed because Docker Compose normally merges `compose.yaml` with optional `compose.override.yaml`. |

## Workload Candidate Wording

The spec's "Workload Candidates, not final manifests" rule is correct.[^target-spec] Kubernetes defines Deployments as managing Pods for an application workload, "usually one that doesn't maintain state", with declarative rollout/update behavior.[^k8s-deployment] That supports `Deployment candidate` for long-running HTTP apps, frontends, workers, admin tools, and other replicated stateless-ish processes when repository facts do not require stable identity or per-replica storage.

StatefulSet wording should be narrower. Kubernetes says StatefulSets maintain sticky Pod identity and are useful for applications needing persistent storage or stable, unique network identity; it lists stable identifiers, stable persistent storage, and ordered deployment/scaling as StatefulSet use cases.[^k8s-statefulset] Therefore a database/cache/search service in Compose should not be presented as "StatefulSet" as a final answer. The safer form is: `StatefulSet candidate, or external managed service, because repository facts show persistent/stateful service evidence; final storage, HA, backup, and managed-service choice are unresolved`.

Job wording is well supported for migrations, seed tasks, and prestart one-shot commands. Kubernetes says Jobs represent one-off tasks that run to completion and then stop, and that a Job retries Pods until the requested successful completions are reached.[^k8s-job] If the repo evidence is a long-running init/precondition check within the same Pod, an `initContainer candidate` may be more precise than a Job; Kubernetes init containers run before app containers, run to completion, and can block app startup until preconditions are met.[^k8s-init]

Recommended prompt phrase: "State Kubernetes controllers as candidates based on detected evidence: Deployment for long-running stateless app/server/worker processes, StatefulSet or external managed-service candidate for stateful services needing stable identity or persistent storage, Job for one-off migration/seed/prestart tasks, and init container candidate only when the evidence is app-Pod startup gating rather than an independently managed task."

## Service and Ingress Semantics

The spec should keep Service and Ingress as companion object candidates, not workloads.[^target-spec] Kubernetes Services expose network applications running as Pods and provide a stable abstraction over backend Pods.[^k8s-service] The Service API distinguishes `ClusterIP`, `NodePort`, `LoadBalancer`, and `ExternalName`; `ClusterIP` is cluster-internal and is the default, while `LoadBalancer` and `NodePort` imply external-facing behavior through cluster/cloud mechanics.[^k8s-service-api] Ingress exposes HTTP/HTTPS routes from outside the cluster to Services, and the IngressClass/controller is cluster-specific configuration.[^k8s-ingress]

Container ports need careful wording. The Kubernetes Pod API says `container.ports` lists ports to expose from the container, but not specifying a port does not prevent a listening port from being accessible on the Pod network.[^k8s-pod-api-ports] Therefore the answer should distinguish:

- `listening/container port evidence`: Dockerfile `EXPOSE`, app config, README URL, Compose target port, or Kubernetes `containerPort`.
- `Service candidate`: only when a workload has inbound network consumers or explicit port/published-port evidence.
- `Service type`: unresolved unless declared; do not infer LoadBalancer/NodePort from a local Compose host port.
- `Ingress candidate`: only when external HTTP routing is evidenced or likely needed from an explicit web-facing port/context path; host, TLS, and class remain unresolved unless present.

The repo's own tests already enforce one important boundary: a queue worker with no inbound port maps to a Deployment without a Service, while an HTTP backend keeps a ClusterIP Service candidate.[^repo-compose-discovery]

## ConfigMap and Secret Handling

The spec's ConfigMap/Secret candidate wording is supported. Kubernetes ConfigMaps store non-confidential key-value data and can be consumed by Pods as environment variables, command-line arguments, or files in a volume.[^k8s-configmap] Kubernetes Secrets hold sensitive data such as passwords, tokens, or keys and are specifically intended for confidential data.[^k8s-secret]

Compose evidence can support candidates but does not finalize Kubernetes objects. The Compose Specification defines service environment variables, `env_file`, `configs`, and `secrets` as separate service inputs; Docker Compose docs say `configs` allow service behavior changes without rebuilding the image, and services only access configs explicitly granted to them.[^compose-spec][^docker-compose-services]

Recommended prompt phrase: "Classify keys as ConfigMap or Secret candidates from names and source context; do not recommend or repeat sample Secret values as production values; preserve Secret ownership/value population as unresolved unless existing Kubernetes manifests explicitly define the object."

## Probes and Health Checks

The spec's `probe or health check candidates` language is correct, provided it stays conservative.[^target-spec] Kubernetes probes are kubelet diagnostics; based on probe results, Kubernetes can restart unhealthy containers or stop sending traffic to containers that are not ready.[^k8s-probes] Startup probes delay liveness/readiness checks until startup succeeds.[^k8s-probes]

Compose `healthcheck` evidence is not identical to Kubernetes liveness/readiness/startup probes. Docker Compose docs define `healthcheck` as a check used to determine whether service containers are "healthy" and note that Compose can override a Dockerfile health check.[^docker-compose-healthcheck] That is useful migration evidence, but the final answer should not decide liveness versus readiness semantics unless the repository has Kubernetes manifests, explicit Spring Boot liveness/readiness endpoints, or similarly specific source facts.

Recommended prompt phrase: "Treat Dockerfile/Compose health checks and framework health endpoints as Probe Candidates. If only one generic health check is found, say the exact readiness/liveness/startup split remains an operational decision."

## Volumes and PVC Persistence

The spec's volume/PVC candidate requirement is supported by Kubernetes storage semantics. Kubernetes volumes solve the problem that container filesystem changes are ephemeral across crashes and can provide shared files among containers in a Pod.[^k8s-volumes] PVCs are user storage requests; claims can request size and access modes, and StorageClass abstracts storage implementation differences.[^k8s-pv]

The key audit requirement is to keep application-local persistence separate from database persistence. A datasource URL, SQL schema, or external database dependency can prove persistent data exists, but it does not by itself prove that the application Pod needs a PVC. This boundary is already captured in the existing build/runtime fact-check and repo tests that distinguish "No application PVC was detected" from database storage decisions.[^build-runtime-fact-check][^repo-migration-tests]

Recommended prompt phrase: "Report declared mounts, named volumes, database service volumes, and app-local writable paths separately. Leave PVC size, access mode, StorageClass, backup policy, and managed database replacement as unresolved unless declared by source facts."

## Workload Relationships and Dependencies

The spec's relationship evidence rule is well founded. Compose `depends_on` expresses startup/shutdown dependencies, and the Compose Specification says Compose creates services in dependency order and waits for healthchecks when a dependency is marked `service_healthy`.[^compose-depends-on] This supports arrows like `prestart -> db` or `backend -> db` when backed by Compose or configuration evidence.

Kubernetes does not make `depends_on` a generic cross-workload ordering primitive. The Kubernetes-native translation is usually a combination of Services for stable discovery, readiness probes to gate traffic, init containers for Pod-local startup preconditions, and Jobs for independently managed one-off tasks.[^k8s-service][^k8s-probes][^k8s-init][^k8s-job] Therefore the spec should keep relationship arrows as repository-derived dependency evidence, not as final Kubernetes startup-order design.

Recommended prompt phrase: "Use arrows for source-backed relationships only; explain that Compose startup order or config references become migration evidence, while final Kubernetes readiness/init/Job/service-discovery design remains candidate-level."

## Negative Claims and Status Labels

The target spec is correct to prohibit turning `not_detected`, `partial`, or `unresolved` into positive claims.[^target-spec] In the repo schema, migration question statuses are exactly `answered`, `partial`, `unresolved`, and `not_detected`, while finding confidence is separately `explicit`, `derived`, or `unresolved`.[^repo-models] Tests assert every migration question must carry either basis or missing information, and validation docs show `not_detected` alongside warnings and coverage gaps rather than as proof of absence.[^repo-migration-tests][^repo-validation-python]

Recommended prompt phrase: "For negative claims, always qualify scope: `scanned repository facts did not expose ...`. Never write `there is no external dependency`, `no Secret is needed`, or `no PVC is needed` without the scanned-facts-only qualifier and the relevant coverage caveat."

## Sample and Documentation Compose Evidence

The spec should retain caveats for ignored Compose override files and missing deployment topology files.[^target-spec] Docker Compose normally reads `compose.yaml` plus optional `compose.override.yaml`, and if a service appears in both files, Compose merges the configuration.[^docker-compose-merge] If the analyzer reports `compose_override_not_merged`, the final answer must not claim the primary Compose file is the complete runtime topology.

The repo has a clear local policy for documentation/example Compose files: inventory marks Compose files under documentation/docs/examples/demo/test-style paths as ignored sample or documented deployment files unless a README/run instruction selects them.[^repo-inventory][^repo-compose-discovery][^repo-migration-tests] Compose profiles add another caveat: the Compose Specification says services can be ignored when none of their profiles are active, while top-level elements are not affected by profiles.[^compose-profiles]

Recommended prompt phrase: "If Compose evidence comes from docs/examples or inactive/unknown profiles, describe it as sample/documented deployment evidence unless README or run instructions select it as the primary topology; mention ignored overrides and profile caveats in `## 확인이 필요한 부분`."

## Spec Adjustments to Consider

1. Add explicit controller-selection wording for `Deployment`, `StatefulSet`, `Job`, and `initContainer candidate`, using the conservative phrases above.
2. Strengthen the Service/Ingress rule: Services, Ingresses, PVCs, ConfigMaps, and Secrets are companion object candidates, not workloads; Service type, IngressClass, host, and TLS are unresolved unless declared.
3. Add a one-line probe warning: a generic health check is not automatically both liveness and readiness.
4. Add a one-line persistence warning: database persistence does not imply an application PVC.
5. Add a one-line Compose caveat: ignored override files and documentation/sample Compose files must be surfaced as coverage caveats, and Compose profile activation can change the service set.
6. Keep the existing `not_detected` rule exactly as written, and use the scanned-facts-only qualifier in any "no X detected" wording.

## Sources

[^target-spec]: Repo primary source, `docs/superpowers/specs/2026-07-21-workload-centered-llm-answer-design.md`.
[^build-runtime-fact-check]: Repo primary source, `docs/research/2026-07-21-workload-build-runtime-profile-fact-check.md`.
[^repo-models]: Repo primary source, `src/repo_analyzer/models.py`.
[^repo-inventory]: Repo primary source, `src/repo_analyzer/inventory.py`.
[^repo-compose-discovery]: Repo primary source, `tests/test_compose_discovery.py`.
[^repo-migration-tests]: Repo primary source, `tests/test_migration_questions.py`.
[^repo-validation-python]: Repo primary source, `docs/validation/2026-07-21-sglang-live-python-repos.md`.
[^k8s-deployment]: Kubernetes docs, "Deployments" — https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
[^k8s-statefulset]: Kubernetes docs, "StatefulSets" — https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/
[^k8s-job]: Kubernetes docs, "Jobs" — https://kubernetes.io/docs/concepts/workloads/controllers/job/
[^k8s-init]: Kubernetes docs, "Init Containers" — https://kubernetes.io/docs/concepts/workloads/pods/init-containers/
[^k8s-service]: Kubernetes docs, "Service" — https://kubernetes.io/docs/concepts/services-networking/service/
[^k8s-service-api]: Kubernetes API reference, "Service v1" — https://kubernetes.io/docs/reference/kubernetes-api/core/service-v1/
[^k8s-ingress]: Kubernetes docs, "Ingress" — https://kubernetes.io/docs/concepts/services-networking/ingress/
[^k8s-pod-api-ports]: Kubernetes API reference, "Pod v1 / Container ports" — https://kubernetes.io/docs/reference/kubernetes-api/core/pod-v1/
[^k8s-configmap]: Kubernetes docs, "ConfigMaps" — https://kubernetes.io/docs/concepts/configuration/configmap/
[^k8s-secret]: Kubernetes docs, "Secrets" — https://kubernetes.io/docs/concepts/configuration/secret/
[^k8s-probes]: Kubernetes docs, "Liveness, Readiness, and Startup Probes" — https://kubernetes.io/docs/concepts/workloads/pods/probes/
[^k8s-volumes]: Kubernetes docs, "Volumes" — https://kubernetes.io/docs/concepts/storage/volumes/
[^k8s-pv]: Kubernetes docs, "Persistent Volumes" — https://kubernetes.io/docs/concepts/storage/persistent-volumes/
[^compose-spec]: Compose Specification — https://compose-spec.github.io/compose-spec/spec.html
[^compose-depends-on]: Compose Specification, `depends_on` — https://compose-spec.github.io/compose-spec/spec.html#depends_on
[^compose-profiles]: Compose Specification, "Profiles" — https://compose-spec.github.io/compose-spec/spec.html#profiles
[^docker-compose-services]: Docker Docs, "Compose file reference: services" — https://docs.docker.com/reference/compose-file/services/
[^docker-compose-healthcheck]: Docker Docs, "Compose file reference: healthcheck" — https://docs.docker.com/reference/compose-file/services/#healthcheck
[^docker-compose-merge]: Docker Docs, "Merge Compose files" — https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/
