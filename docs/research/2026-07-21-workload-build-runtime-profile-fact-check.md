# Workload Build and Runtime Profile Fact Check

Date: 2026-07-21

Question: for a Kubernetes migration handoff, what information should be captured per application workload, and should `build method` include build tool, image build path, build command, application start command, base image, exposed ports, environment/config/secrets, volumes, probes, and workload relationships/dependencies?

Scope: primary sources only: official Kubernetes docs/API reference, Docker docs, OCI image-spec, Cloud Native Buildpacks/Paketo docs, and Google Jib docs.

## Summary

Conclusion: capture all of the listed information per workload, but do not put all of it under a single `build method` field.

Use two linked sections:

1. `image_build_profile`: how the workload image is produced. Include build tool, build invocation, image build context/path, Dockerfile path or buildpack/Jib configuration, target image, base image/builder, build args/environment that affect the image, and produced artifact path when known.
2. `runtime_deployment_profile`: how the workload runs on Kubernetes. Include image reference, start command/arguments, exposed/listening ports and Service ports, environment variables, ConfigMap candidates, Secret candidates, volumes/mounts/PVC needs, probes, lifecycle/init behavior, workload controller mapping, and dependencies/relationships.

The reason to separate them is that Kubernetes Pod/container configuration explicitly models runtime fields such as `image`, `command`, `args`, `env`, `envFrom`, `ports`, probes, resources, lifecycle, and `volumeMounts`; Dockerfile/Jib/OCI/buildpacks can provide defaults for some of those fields, but Kubernetes can override or supplement them at deployment time.[^k8s-pod-api][^oci-config][^dockerfile][^jib-maven]

## Fact Check Table

| Candidate field | Should the handoff capture it? | Best location | Primary-source basis |
| --- | --- | --- | --- |
| Build tool | Yes. | `image_build_profile.build_tool` | Buildpacks detect source build tools such as Maven/Gradle/SBT/Leiningen from app contents, and Jib is specifically a Maven/Gradle plugin for building Docker/OCI images.[^paketo-java][^jib-maven] |
| Image build path/context | Yes. | `image_build_profile.context_path` / `dockerfile_path` / `artifact_path` | Docker build uses a build context; Compose `build` can be a context path or structured build definition with an alternate Dockerfile; `pack build` supports `--path`; Jib supports `extraDirectories` and app root/containerizing mode.[^docker-context][^compose-build][^pack-build][^jib-maven] |
| Build command | Yes. | `image_build_profile.build_command` | Docker docs show `docker build`; Buildpacks use `pack build`; Jib Maven docs show `mvn compile jib:build`, `jib:dockerBuild`, and lifecycle binding; Paketo allows build arguments such as `BP_<TOOL>_BUILD_ARGUMENTS`.[^docker-dockerfile-overview][^pack-build][^jib-maven][^paketo-java] |
| Application start command | Yes, but it is runtime, not only build. | `runtime_deployment_profile.start.command` and `.args`, with image default source if known | Kubernetes `command` maps to entrypoint and `args` maps to CMD/default arguments; if omitted, image ENTRYPOINT/CMD are used. Dockerfile `ENTRYPOINT`/`CMD`, OCI `Entrypoint`/`Cmd`, Buildpacks process types, and Jib `container.entrypoint`/`args` can supply image defaults.[^k8s-command-args][^k8s-pod-api][^dockerfile][^oci-config][^cnb-process][^jib-maven] |
| Base image / builder | Yes. | `image_build_profile.base_image` or `.builder_image` | Dockerfile `FROM` sets the base image. OCI image config includes OS/architecture and layer metadata. Jib has a `from.image` base-image setting. Buildpacks use a builder and contribute runtime components; Paketo Java says JDK is used at build time and JRE at runtime.[^dockerfile][^oci-config][^jib-maven][^paketo-reference] |
| Exposed/listening ports | Yes, but distinguish image metadata, container port, and Service exposure. | `runtime_deployment_profile.ports` | Dockerfile `EXPOSE` is documentation and does not publish a port. OCI has `ExposedPorts` defaults. Kubernetes container `ports` documents/exposes ports on the Pod IP but omission does not prevent listening ports from being reachable. Services expose Pods behind stable endpoints.[^dockerfile][^oci-config][^k8s-pod-api][^k8s-service] |
| Environment/config/secrets | Yes. | `runtime_deployment_profile.env`, `.config`, `.secrets` | Kubernetes ConfigMaps provide non-confidential config via env vars, args, or files; Secrets are intended for sensitive data and can be consumed by Pods or used for image pulls. Dockerfile/Jib/OCI can set image-level environment defaults, but deployment-specific values belong in ConfigMaps/Secrets or Pod env.[^k8s-configmap][^k8s-secret][^dockerfile][^oci-config][^jib-maven] |
| Volumes/mounts/persistence | Yes. | `runtime_deployment_profile.volumes`, `.mounts`, `.persistence` | Kubernetes volumes provide filesystem access/sharing and persistence; Pods declare `.spec.volumes` and containers declare `volumeMounts`. PVCs request persistent storage and are mounted through Pod volumes. Dockerfile/OCI/Jib can declare volume mount-point defaults, and Compose volumes are useful source evidence.[^k8s-volumes][^k8s-pv][^k8s-pod-api][^dockerfile][^oci-config][^jib-maven][^compose-services] |
| Probes / health checks | Yes. | `runtime_deployment_profile.probes` | Kubernetes supports startup, readiness, and liveness probes with distinct traffic/restart semantics. Dockerfile and Compose health checks can be migration evidence, but should not be copied mechanically because Kubernetes probe semantics differ.[^k8s-probes][^k8s-probe-task][^dockerfile][^compose-services] |
| Workload relationships/dependencies | Yes. | `runtime_deployment_profile.relationships` / `dependencies` | Kubernetes workloads may be multiple components that work together; Services provide stable discovery for Pod backends; readiness can model backend availability; init containers can perform setup before app containers. Compose `depends_on` provides source evidence for startup ordering, including health-gated dependencies in long syntax.[^k8s-workloads][^k8s-service][^k8s-init][^k8s-probes][^compose-services] |

## Recommended Per-Workload Handoff Shape

```yaml
workload:
  name: <component name>
  source_evidence:
    files:
      - README.md
      - Dockerfile
      - compose.yaml
      - pom.xml/build.gradle/package.json
      - application.yml/.env
      - kubernetes manifests, if present

  image_build_profile:
    method: dockerfile | compose-build | buildpacks | jib | prebuilt-image | unknown
    build_tool: maven | gradle | npm | go | pack | jib | docker | unknown
    build_command: <exact command or unresolved>
    context_path: <path passed to build context/path or unresolved>
    dockerfile_path: <path or not_applicable>
    artifact_path: <jar/war/dist path if build produces one>
    base_image: <Dockerfile FROM or Jib from.image>
    builder_image: <buildpack builder, if buildpacks>
    target_image: <registry/repository/tag if known>
    build_args_or_env: <non-secret build-time inputs only>
    limits:
      - <what cannot be known from repo evidence>

  runtime_deployment_profile:
    controller_candidate: Deployment | StatefulSet | Job | CronJob | DaemonSet | external | unresolved
    image: <runtime image reference>
    start:
      command: <Kubernetes command / image ENTRYPOINT / buildpack process / unresolved>
      args: <Kubernetes args / image CMD / unresolved>
      working_dir: <if known>
    ports:
      - container_port: <port>
        protocol: tcp | udp | sctp
        source: dockerfile_expose | compose_ports | app_config | k8s_manifest | README | unresolved
        service_needed: true | false | unresolved
    env:
      explicit: []
      configmap_candidates: []
      secret_candidates: []
    storage:
      volumes: []
      mounts: []
      pvc_candidates: []
      unresolved: []
    health:
      startup_probe: <source-backed candidate or unresolved>
      readiness_probe: <source-backed candidate or unresolved>
      liveness_probe: <source-backed candidate or unresolved>
    lifecycle_and_init:
      init_containers_or_jobs: []
      hooks: []
      migration_or_seed_steps: []
    relationships:
      depends_on:
        - name: <db/cache/service>
          kind: service | database | cache | queue | object_store | external | unresolved
          evidence: <compose depends_on, env var, URL, README, manifest>
      exposes_service_to:
        - <consumer or external user>
    unresolved_operational_decisions:
      - replicas/HPA/resources/securityContext/Ingress/StorageClass/Secret values/etc.
```

## Field Notes

`build method` should be narrow. The official build sources describe how images are created: Dockerfile/build context, Compose build context, `pack build`, Jib Maven/Gradle goals, base image/builder, build args, and artifacts. That is enough to rebuild or audit the image, but not enough to describe Kubernetes behavior.[^docker-context][^compose-build][^pack-build][^jib-maven]

`start command` crosses the boundary. The image may carry ENTRYPOINT/CMD/process-type defaults, but Kubernetes can override them with `command` and `args`. Capture both the image default and the Kubernetes override when both exist.[^k8s-command-args][^oci-config]

`ports` need source and semantics. Dockerfile `EXPOSE`, OCI `ExposedPorts`, Compose `ports`, app config, and Kubernetes `containerPort` are not identical. The migration handoff should record the source and decide separately whether a Kubernetes Service, Ingress, or Gateway is needed.[^dockerfile][^compose-services][^k8s-pod-api][^k8s-service]

`environment/config/secrets` belong in the runtime profile even when defaults are set in the image. Kubernetes explicitly separates non-confidential ConfigMaps from Secrets, and ConfigMaps can be consumed as env vars, command args, or mounted files. Secret values usually cannot and should not be recovered from source; capture keys, consumers, and unresolved value ownership.[^k8s-configmap][^k8s-secret]

`volumes` must separate image-declared mount points, Compose/local mounts, Kubernetes volumes, and persistent storage claims. A database dependency does not automatically imply an application PVC; only source evidence for filesystem writes, declared volumes, or stateful services should drive a persistence candidate.[^k8s-volumes][^k8s-pv][^compose-services]

`probes` should be conservative. Kubernetes liveness, readiness, and startup probes have different effects. Readiness controls Service endpoints; liveness restarts containers; startup delays the other probes. Dockerfile/Compose health checks are useful clues, but the handoff should mark them as candidates until semantics are reviewed.[^k8s-probes][^k8s-probe-task][^compose-services]

`relationships/dependencies` are first-class migration data. Kubernetes Services solve stable discovery for sets of Pods, init containers can run setup before app containers, and readiness probes can prevent traffic until backend dependencies are available. Compose `depends_on`, env vars such as database URLs, service names, and manifests are evidence; final ordering and managed-service replacement remain operational decisions.[^k8s-service][^k8s-init][^k8s-probes][^compose-services]

## Limits and Uncertainties

- These sources define platform fields and semantics; they do not define a universal "migration handoff" schema. The recommended schema above is an inference from Kubernetes/Docker/OCI/buildpack/Jib fields.
- Dockerfile `EXPOSE`, OCI `ExposedPorts`, Kubernetes `containerPort`, and Compose `ports` are related but not interchangeable. A handoff should not infer external exposure from image metadata alone.
- Dockerfile/OCI/Jib image metadata may contain defaults that are overridden by Kubernetes manifests, Helm values, Kustomize patches, CI variables, or deployment tooling outside the repo.
- Secret values, production database endpoints, replica counts, resource requests/limits, HPA policy, PDBs, StorageClass, Ingress/Gateway policy, NetworkPolicy, and cloud-managed service choices are often not derivable from application source.
- Compose `depends_on` documents local orchestration order, not necessarily production readiness or Kubernetes startup design. Treat it as evidence, not as a final Kubernetes dependency mechanism.
- Buildpacks can infer build tools and contribute process types; exact build behavior may depend on builder version, buildpack version, environment variables, and platform/lifecycle configuration not present in the repo.

## Sources

[^k8s-workloads]: Kubernetes docs, "Workloads" — https://kubernetes.io/docs/concepts/workloads/
[^k8s-pod-api]: Kubernetes API reference, "Pod v1 / Container" — https://kubernetes.io/docs/reference/kubernetes-api/core/pod-v1/
[^k8s-command-args]: Kubernetes docs, "Define a Command and Arguments for a Container" — https://kubernetes.io/docs/tasks/inject-data-application/define-command-argument-container/
[^k8s-service]: Kubernetes docs, "Service" — https://kubernetes.io/docs/concepts/services-networking/service/
[^k8s-configmap]: Kubernetes docs, "ConfigMaps" — https://kubernetes.io/docs/concepts/configuration/configmap/
[^k8s-secret]: Kubernetes docs, "Secrets" — https://kubernetes.io/docs/concepts/configuration/secret/
[^k8s-volumes]: Kubernetes docs, "Volumes" — https://kubernetes.io/docs/concepts/storage/volumes/
[^k8s-pv]: Kubernetes docs, "Persistent Volumes" — https://kubernetes.io/docs/concepts/storage/persistent-volumes/
[^k8s-probes]: Kubernetes docs, "Liveness, Readiness, and Startup Probes" — https://kubernetes.io/docs/concepts/workloads/pods/probes/
[^k8s-probe-task]: Kubernetes docs, "Configure Liveness, Readiness and Startup Probes" — https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-probes/
[^k8s-init]: Kubernetes docs, "Init Containers" — https://kubernetes.io/docs/concepts/workloads/pods/init-containers/
[^dockerfile]: Docker docs, "Dockerfile reference" — https://docs.docker.com/reference/dockerfile/
[^docker-context]: Docker docs, "Build context" — https://docs.docker.com/build/concepts/context/
[^docker-dockerfile-overview]: Docker docs, "Dockerfile overview" — https://docs.docker.com/build/concepts/dockerfile/
[^compose-build]: Docker docs, "Compose Build Specification" — https://docs.docker.com/reference/compose-file/build/
[^compose-services]: Docker docs, "Define services in Docker Compose" — https://docs.docker.com/reference/compose-file/services/
[^oci-config]: Open Container Initiative, "OCI Image Configuration" — https://github.com/opencontainers/image-spec/blob/main/config.md
[^pack-build]: Cloud Native Buildpacks docs, "`pack build`" — https://buildpacks.io/docs/for-platform-operators/how-to/integrate-ci/pack/cli/pack_build/
[^cnb-process]: Cloud Native Buildpacks docs, "Specify process types" — https://buildpacks.io/docs/for-buildpack-authors/how-to/write-buildpacks/specify-launch-processes/
[^paketo-java]: Paketo docs, "How to Build Java Apps with Paketo Buildpacks" — https://paketo.io/docs/howto/java/
[^paketo-reference]: Paketo docs, "Java Buildpack Reference" — https://paketo.io/docs/reference/java-reference/
[^jib-maven]: GoogleContainerTools Jib, "jib-maven-plugin README" — https://github.com/GoogleContainerTools/jib/tree/master/jib-maven-plugin
