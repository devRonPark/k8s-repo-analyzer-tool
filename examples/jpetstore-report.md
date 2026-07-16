# Kubernetes P0 Analysis — jpetstore-6

- Profile: `kubernetes-p0`
- Git ref: `5a7cc780505b88a60779b3e3c0a50b0e404cfb2d`
- Detected files: 8
- Schema version: 1.0

## 1. Components

### jpetstore

- Build: Dockerfile (context `.`)
- Image: (built locally)
- Language: Java 17
- Frameworks: MyBatis 3.5.19, MyBatis-Spring 3.0.6, Spring Framework 6.2.19, Stripes 1.6.0
- Build tool: Maven (mvnw wrapper)
- Build command: `./mvnw clean package`
- Build artifact: `target/jpetstore.war` (war)
- Application server: External servlet container — Apache Tomcat 9.0.120 by default (Maven profile 'tomcat9'); alternatives via Maven profiles: Apache TomEE, WildFly, WebSphere Liberty, Eclipse Jetty, GlassFish, Payara, Resin
- Runtime: Java 17 web application (WAR) — requires an external servlet container
- Command: `./mvnw cargo:run -P tomcat90`
- Container port: 8080
- HTTP context path: `/jpetstore`
- Published (compose): 8080:8080
- Runtime dependencies: Embedded HSQL in-memory database (no external DB by default)
- Kubernetes mapping: Deployment + ClusterIP Service + Ingress (context path /jpetstore)

## 2. Kubernetes workload mappings

| Component | Workload candidate | Rationale |
| --- | --- | --- |
| jpetstore | Deployment + ClusterIP Service + Ingress (context path /jpetstore) | Stateless Java web application (WAR) on an external servlet container; horizontally scalable behind a Service. Uses an in-process in-memory database, so replicas do NOT share state — externalise the database before running more than one replica. |

## 3. Networking (ports & services)

| Subject | Value | Confidence | Kubernetes effect | Evidence |
| --- | --- | --- | --- | --- |
| jpetstore.container_port | 8080 | explicit | jpetstore Service targetPort candidate | `docker-compose.yaml:25-25` ($.services.jpetstore.ports[0]) |
| app.context_path | /jpetstore | derived | the app is served under '/jpetstore', not '/'. Ingress must route this path (or rename the WAR to ROOT); Service targetPort is unaffected. | `pom.xml:247-247` (build.finalName); `README.md:61-61` (README) |
| servlet.StripesDispatcher | *.action | explicit | HTTP route handled by the app (full path e.g. '/jpetstore/...*.action') | `src/main/webapp/WEB-INF/web.xml:60-63` (servlet-mapping[StripesDispatcher]) |

## 4. Persistent storage

_No persistent volumes detected._

## 4b. Runtime dependencies (external services & datastores)

- database.embedded: **embedded HSQL (in-memory, in-process)** — no external database is required by default. Data lives in the pod and is ephemeral; each replica has its own isolated copy. Externalise the DB (with JDBC config as ConfigMap/Secret) before scaling past 1 replica or needing durability. (derived); evidence `src/main/webapp/WEB-INF/applicationContext.xml:31-34` (jdbc:embedded-database)

## 5. Configuration & Secrets

### ConfigMap candidates

_None detected._

### Stack, build & profile facts

| Subject | Value | Kubernetes effect | Evidence |
| --- | --- | --- | --- |
| build.system | maven | determines the build/CI pipeline and the image-build strategy; detected build systems: maven | `pom.xml:33-33` (project) |
| build.system.selection | {'detected': ['maven'], 'selected': 'maven', 'rationale': 'only build system detected in the repository', 'how_to_select_other': 'n/a (single build system)'} | records why this build system was chosen and how to analyze the other(s) | `pom.xml:33-33` (project) |
| runtime.language | Java 17 | informs the container base image (JRE/JDK major version) | `pom.xml:62-62` (properties.java.version) |
| framework.mybatis | 3.5.19 | application framework (no direct K8s object; informs runtime behaviour) | `pom.xml:97-101` (dependency[mybatis]) |
| framework.mybatis-spring | 3.0.6 | application framework (no direct K8s object; informs runtime behaviour) | `pom.xml:102-106` (dependency[mybatis-spring]) |
| framework.spring_framework | 6.2.19 | application framework (no direct K8s object; informs runtime behaviour) | `pom.xml:107-111` (dependency[spring-context]) |
| framework.stripes | 1.6.0 | application framework (no direct K8s object; informs runtime behaviour) | `pom.xml:123-137` (dependency[stripes]) |
| build.tool | Maven (mvnw wrapper) | build system that produces the deployable artifact (build image / CI) | `pom.xml:33-33` (packaging) |
| build.artifact | target/jpetstore.war | the WAR/JAR that must be present in (or built into) the container image | `pom.xml:247-247` (build.finalName); `pom.xml:33-33` (packaging) |
| profile.tomcat9 | Apache Tomcat 9.0.120 | Maven profile selecting the servlet container at run time (changes runtime image) | `pom.xml:336-364` (profile[tomcat9]) |
| profile.tomee80 | Apache TomEE 8.0.16 | Maven profile selecting the servlet container at run time (changes runtime image) | `pom.xml:365-391` (profile[tomee80]) |
| profile.wildfly26 | WildFly 26.1.3.Final | Maven profile selecting the servlet container at run time (changes runtime image) | `pom.xml:392-419` (profile[wildfly26]) |
| profile.liberty-ee8 | WebSphere Liberty 26.0.0.6 | Maven profile selecting the servlet container at run time (changes runtime image) | `pom.xml:420-447` (profile[liberty-ee8]) |
| profile.jetty | Eclipse Jetty 12.1.11 | Maven profile selecting the servlet container at run time (changes runtime image) | `pom.xml:448-475` (profile[jetty]) |
| profile.glassfish5 | GlassFish 5.1.0 | Maven profile selecting the servlet container at run time (changes runtime image) | `pom.xml:476-502` (profile[glassfish5]) |
| profile.payara5 | Payara 5.2022.5 | Maven profile selecting the servlet container at run time (changes runtime image) | `pom.xml:503-530` (profile[payara5]) |
| profile.resin | Resin 4.0.67 | Maven profile selecting the servlet container at run time (changes runtime image) | `pom.xml:531-564` (profile[resin]) |
| runtime.application_server | External servlet container — Apache Tomcat 9.0.120 by default (Maven profile 'tomcat9'); alternatives via Maven profiles: Apache TomEE, WildFly, WebSphere Liberty, Eclipse Jetty, GlassFish, Payara, Resin | the app is NOT self-contained: it needs a servlet container. For K8s, bake the WAR into a fixed server image (e.g. tomcat:9-jre17) rather than downloading a server at runtime. | `pom.xml:336-364` (profile[tomcat9]); `Dockerfile:21-21` (CMD); `README.md:43-43` (README) |

### Secret candidates

_None detected._

## 6. Startup order & initialization

- startup.db_init: `classpath:database/jpetstore-hsqldb-schema.sql` — schema/seed SQL executed in-process at application startup; re-runs on every pod start (no separate migration Job for the embedded DB). (explicit); evidence `src/main/webapp/WEB-INF/applicationContext.xml:32-32` (jdbc:script)
- startup.db_init: `classpath:database/jpetstore-hsqldb-dataload.sql` — schema/seed SQL executed in-process at application startup; re-runs on every pod start (no separate migration Job for the embedded DB). (explicit); evidence `src/main/webapp/WEB-INF/applicationContext.xml:33-33` (jdbc:script)

## 7. Health checks

_No health checks defined._

## 8. Build-time constraints

_None detected._

## 8b. Container image build & runtime

- image.build_command: **./mvnw clean package** — produces the artifact during image build; needs network for dependency resolution (derived)
  - evidence: `Dockerfile:20-20` (RUN); `README.md:37-37` (README)
- image.start_command: **./mvnw cargo:run -P tomcat90** — container entrypoint/command (Deployment container.command/args) (explicit)
  - evidence: `Dockerfile:21-21` (CMD)
- image.base: **openjdk:25** — container base image (explicit)
  - evidence: `Dockerfile:17-17` (FROM)
- image.runtime_server_download: **server downloaded at container start (cargo:run)** — the servlet container is fetched from the internet on every start; pods need egress and startup is slow/non-reproducible. Build a fixed WAR-on-Tomcat image instead. (derived)
  - evidence: `Dockerfile:21-21` (CMD)
- image.signal_handling: **Maven runs as PID 1 (shell form CMD)** — SIGTERM goes to the mvn/mvnw wrapper, not the JVM, so graceful shutdown and fast pod termination are not guaranteed. Use exec form / tini, or run the server directly. (derived)
  - evidence: `Dockerfile:21-21` (CMD)
- image.runs_as_root: **no USER instruction** — the container runs as root by default; set securityContext.runAsNonRoot / runAsUser and a non-root USER in the image. (derived)
  - evidence: `Dockerfile:17-17` (USER)

## 9. Unresolved operational inputs

_These are NOT decided from the repository. No default values were invented._

| Subject | Why unresolved | Input needed | Kubernetes effect |
| --- | --- | --- | --- |
| readiness_liveness_probe | the repository defines no health/readiness endpoint (no Spring Boot Actuator, no compose healthcheck) | an HTTP path or TCP port to probe (e.g. TCP 8080, or GET the context root once warm) | container readinessProbe / livenessProbe |
| security_context_run_as_non_root | the image sets no USER; running as root is a deployment decision, not stated in the repo | target UID/GID and runAsNonRoot policy | Pod/container securityContext |
| graceful_shutdown | start command runs a shell/Maven wrapper as PID 1; signal propagation to the JVM is not guaranteed | an exec-form entrypoint (or tini) and the app's termination behaviour | terminationGracePeriodSeconds, preStop hook, container.command |
| external_database_for_scaling | the app uses an in-process in-memory database; replicas cannot share state and data is ephemeral | whether to externalise to a managed/in-cluster DB, and its connection details | external DB Service + ConfigMap/Secret; enables replicas>1 and durability |
| replica_count | desired availability/throughput is an operational decision, not in the repo | target replicas per Deployment (SLO / load expectations) | Deployment.spec.replicas |
| resource_requests_limits | repo contains no CPU/memory sizing information | measured or estimated CPU/memory per component | container resources.requests / resources.limits |
| ingress_class | cluster ingress controller is environment-specific and not declared in the repo | target IngressClass in the destination cluster | Ingress.spec.ingressClassName |
| horizontal_pod_autoscaler | no scaling policy is expressed in the repo | scaling metric and min/max replicas | HorizontalPodAutoscaler |
| pod_disruption_budget | availability tolerance during disruptions is an operational decision | minAvailable/maxUnavailable policy | PodDisruptionBudget |

## 10. Warnings & unsupported constructs

Warnings:

- [run_profile_undefined] run command activates Maven profile 'tomcat90', which is not defined in the POM (defined: glassfish5, jetty, liberty-ee8, payara5, resin, tomcat9, tomee80, wildfly26). It resolves only because the default profile stays active; verify the intended server. (`Dockerfile`)
- [jdk_version_mismatch] Dockerfile base image 'openjdk:25' targets Java 25, but the POM builds for Java 17. Align the runtime JDK to the build target to avoid class-version surprises. (`Dockerfile`)

_No unsupported constructs._

## Quick answers

1. **Components?** jpetstore
2. **Which workloads?** jpetstore → Deployment + ClusterIP Service + Ingress (context path /jpetstore)
3. **Ports/Services?** jpetstore:8080
4. **What must persist?** none
5. **ConfigMap/Secret?** 0 ConfigMap keys, 0 secret keys
6. **Init first?** classpath:database/jpetstore-hsqldb-schema.sql; classpath:database/jpetstore-hsqldb-dataload.sql
7. **External runtime dependencies?** embedded HSQL (in-memory, in-process)
8. **HTTP context path?** jpetstore:/jpetstore
9. **Undecidable from repo?** 9 operational inputs (see section 9)

