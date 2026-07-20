# Kubernetes P0 Analysis — spring-petclinic

- Profile: `kubernetes-p0`
- Git ref: (not provided)
- Detected files: 21
- Schema version: 1.0

## 1. Components

### mysql

- Build: mysql:9.7
- Image: `mysql:9.7`
- Runtime: MySQL
- Container port: 3306
- Published (compose): 3306:3306
- Environment: MYSQL_ROOT_PASSWORD, MYSQL_ALLOW_EMPTY_PASSWORD, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
- Secret candidates: MYSQL_ROOT_PASSWORD, MYSQL_ALLOW_EMPTY_PASSWORD, MYSQL_PASSWORD
- Volumes: ./conf.d -> /etc/mysql/conf.d
- Kubernetes mapping: StatefulSet + headless Service (or external managed database)

### postgres

- Build: postgres:18.4
- Image: `postgres:18.4`
- Runtime: PostgreSQL
- Container port: 5432
- Published (compose): 5432:5432
- Environment: POSTGRES_PASSWORD, POSTGRES_USER, POSTGRES_DB
- Secret candidates: POSTGRES_PASSWORD
- Kubernetes mapping: StatefulSet + headless Service (or external managed database)

### spring-petclinic

- Build: via Gradle 9.5.1 (gradlew wrapper)
- Image: (built locally)
- Language: Java 17
- Frameworks: Spring Boot 4.1.0, Spring Cache, Spring Data JPA, Thymeleaf, Spring MVC (embedded servlet container), Bean Validation
- Build tool: Gradle 9.5.1 (gradlew wrapper)
- Build command: `./gradlew clean bootJar`
- Build artifact: `build/libs/spring-petclinic-4.0.0-SNAPSHOT.jar` (jar (Spring Boot executable))
- Runtime: Spring Boot 4.1.0 application on an embedded servlet container (Tomcat); self-contained executable JAR
- Container port: 8080
- Environment: MYSQL_PASS, MYSQL_URL, MYSQL_USER, POSTGRES_PASS, POSTGRES_URL, POSTGRES_USER, SPRING_PROFILES_ACTIVE
- Secret candidates: MYSQL_PASS, MYSQL_USER, POSTGRES_PASS, POSTGRES_USER
- Runtime dependencies: Embedded H2 (default profile, in-memory), External MySQL (mysql profile), External PostgreSQL (postgres profile)
- Kubernetes mapping: Deployment + ClusterIP Service

## 2. Kubernetes workload mappings

| Component | Workload candidate | Rationale |
| --- | --- | --- |
| mysql | StatefulSet + headless Service (or external managed database) | Stateful component with persistent data; not a stateless Deployment. |
| postgres | StatefulSet + headless Service (or external managed database) | Stateful component with persistent data; not a stateless Deployment. |
| spring-petclinic | Deployment + ClusterIP Service | Stateless Spring Boot application on an embedded server; horizontally scalable behind a ClusterIP Service (targetPort 8080). No application PVC. Needs a ConfigMap (profile, DB URL) and a Secret (DB credentials) when using an external database, plus liveness/readiness probes. |

## 3. Networking (ports & services)

| Subject | Value | Confidence | Kubernetes effect | Evidence |
| --- | --- | --- | --- | --- |
| k8s.service_port.demo-db | 5432 | explicit | existing Kubernetes Service port evidence | `k8s/db.yml:23-23` (port) |
| k8s.container_port.demo-db | 5432 | explicit | existing Kubernetes workload container port evidence | `k8s/db.yml:63-63` (containerPort) |
| k8s.service_port.petclinic | 80 | explicit | existing Kubernetes Service port evidence | `k8s/petclinic.yml:9-9` (port) |
| k8s.service_port.petclinic | 8080 | explicit | existing Kubernetes Service port evidence | `k8s/petclinic.yml:10-10` (targetPort) |
| k8s.container_port.petclinic | 8080 | explicit | existing Kubernetes workload container port evidence | `k8s/petclinic.yml:46-46` (containerPort) |
| mysql.container_port | 3306 | derived | mysql Service targetPort candidate | `docker-compose.yml:3-3` ($.services.mysql.image) |
| postgres.container_port | 5432 | derived | postgres Service targetPort candidate | `docker-compose.yml:15-15` ($.services.postgres.image) |
| app.default_port | 8080 | derived | no server.port is set, so Spring Boot's embedded server listens on 8080. Service targetPort=8080, containerPort=8080. | `build.gradle:37-37` (dependency[spring-boot-starter-webmvc]); `README.md:36-36` (README) |
| service.target_port | 8080 | derived | Service targetPort = 8080 (the Service `port` itself is an operational choice) | `build.gradle:37-37` (dependency[spring-boot-starter-webmvc]); `README.md:36-36` (README) |
| service.app | {'kind': 'Service', 'target_port': 8080, 'port': 'unresolved', 'type': 'unresolved'} | derived | Kubernetes Service is needed for the app; targetPort is repository-derived, while Service port/type are operational choices. | `build.gradle:37-37` (dependency[spring-boot-starter-webmvc]); `README.md:36-36` (README) |

## 4. Persistent storage

- storage.application_pvc: not required — the application is stateless: it writes no local persistent files and keeps all state in the database. The Deployment needs no PVC/volumeMount. Database persistence is a SEPARATE concern handled by the (external/managed) DB, not the app. (derived); evidence `build.gradle:1-1` (dependencies)
- storage.database_persistence: database tables: owners, pets, specialties, types, vet_specialties, vets, visits (profiles: mysql, postgres) — application state is stored in the selected external database profile. The database needs durable storage or a managed database service; the application Deployment still does not need its own PVC. (derived); evidence `src/main/resources/db/h2/schema.sql:10-10` (CREATE TABLE vets); `src/main/resources/db/h2/schema.sql:17-17` (CREATE TABLE specialties); `src/main/resources/db/h2/schema.sql:23-23` (CREATE TABLE vet_specialties); `src/main/resources/db/h2/schema.sql:30-30` (CREATE TABLE types); `src/main/resources/db/h2/schema.sql:36-36` (CREATE TABLE owners); `src/main/resources/db/h2/schema.sql:46-46` (CREATE TABLE pets); `src/main/resources/db/h2/schema.sql:58-58` (CREATE TABLE visits); `src/main/resources/db/mysql/schema.sql:1-1` (CREATE TABLE vets); `src/main/resources/db/mysql/schema.sql:8-8` (CREATE TABLE specialties); `src/main/resources/db/mysql/schema.sql:14-14` (CREATE TABLE vet_specialties); `src/main/resources/db/mysql/schema.sql:22-22` (CREATE TABLE types); `src/main/resources/db/mysql/schema.sql:28-28` (CREATE TABLE owners); `src/main/resources/db/mysql/schema.sql:38-38` (CREATE TABLE pets); `src/main/resources/db/mysql/schema.sql:50-50` (CREATE TABLE visits); `src/main/resources/db/postgres/schema.sql:1-1` (CREATE TABLE vets); `src/main/resources/db/postgres/schema.sql:8-8` (CREATE TABLE specialties); `src/main/resources/db/postgres/schema.sql:14-14` (CREATE TABLE vet_specialties); `src/main/resources/db/postgres/schema.sql:20-20` (CREATE TABLE types); `src/main/resources/db/postgres/schema.sql:26-26` (CREATE TABLE owners); `src/main/resources/db/postgres/schema.sql:36-36` (CREATE TABLE pets); `src/main/resources/db/postgres/schema.sql:47-47` (CREATE TABLE visits)

## 4b. Runtime dependencies (external services & datastores)

- database.default: **h2 (embedded, in-memory)** — default profile uses an in-process, in-memory database. Data is ephemeral and per-replica; suitable for dev/demo only. Do NOT run this in production — choose an external database (postgres/mysql profile). (explicit); evidence `src/main/resources/application.properties:2-2` (database)
- database.profile.mysql: **External MySQL** — 'mysql' profile connects to an external MySQL. Provide the JDBC URL via ConfigMap and credentials via Secret; ensure network reachability from the cluster. (explicit); evidence `src/main/resources/application-mysql.properties:3-3` (spring.datasource.url)
- database.profile.postgres: **External PostgreSQL** — 'postgres' profile connects to an external PostgreSQL. Provide the JDBC URL via ConfigMap and credentials via Secret; ensure network reachability from the cluster. (explicit); evidence `src/main/resources/application-postgres.properties:3-3` (spring.datasource.url)

## 5. Configuration & Secrets

### ConfigMap candidates

| Key | Default | Evidence |
| --- | --- | --- |
| SPRING_PROFILES_ACTIVE | (unset → default/h2) | `src/main/resources/application-mysql.properties:3-3` (spring.datasource.url); `src/main/resources/application-postgres.properties:3-3` (spring.datasource.url) |
| MYSQL_URL | spring.datasource.url (mysql profile) | `src/main/resources/application-mysql.properties:3-3` (spring.datasource.url) |
| POSTGRES_URL | spring.datasource.url (postgres profile) | `src/main/resources/application-postgres.properties:3-3` (spring.datasource.url) |

### Stack, build & profile facts

| Subject | Value | Kubernetes effect | Evidence |
| --- | --- | --- | --- |
| build.system | gradle | determines the build/CI pipeline and the image-build strategy; detected build systems: gradle, maven | `build.gradle:4-4` (plugins.spring-boot); `pom.xml:1-1` (project) |
| build.system.selection | {'detected': ['gradle', 'maven'], 'selected': 'gradle', 'rationale': 'explicitly requested via --build-system gradle', 'how_to_select_other': '--build-system maven to analyze the maven build instead'} | records why this build system was chosen and how to analyze the other(s) | `build.gradle:4-4` (plugins.spring-boot); `pom.xml:1-1` (project) |
| runtime.java_version | Java 17 | informs the container base image / buildpack JRE major version | `build.gradle:19-19` (java.toolchain.languageVersion) |
| framework.spring_boot | 4.1.0 | Spring Boot app: self-contained executable JAR with an embedded server | `build.gradle:4-4` (plugin) |
| framework.spring_cache | Spring Cache | application framework (informs runtime behaviour; no direct K8s object) | `build.gradle:34-34` (dependency[spring-boot-starter-cache]) |
| framework.spring_data_jpa | Spring Data JPA | application framework (informs runtime behaviour; no direct K8s object) | `build.gradle:35-35` (dependency[spring-boot-starter-data-jpa]) |
| framework.thymeleaf | Thymeleaf | application framework (informs runtime behaviour; no direct K8s object) | `build.gradle:36-36` (dependency[spring-boot-starter-thymeleaf]) |
| framework.spring_mvc | Spring MVC (embedded servlet container) | application framework (informs runtime behaviour; no direct K8s object) | `build.gradle:37-37` (dependency[spring-boot-starter-webmvc]) |
| framework.bean_validation | Bean Validation | application framework (informs runtime behaviour; no direct K8s object) | `build.gradle:38-38` (dependency[spring-boot-starter-validation]) |
| build.tool | Gradle 9.5.1 (gradlew wrapper) | build system that produces the deployable artifact (CI / image build) | `gradlew:1-1` (gradlew); `gradle/wrapper/gradle-wrapper.properties:3-3` (distributionUrl) |
| build.wrapper | ./gradlew | pinned Gradle wrapper makes the build reproducible in CI/image without a preinstalled Gradle | `gradlew:1-1` (gradlew); `gradle/wrapper/gradle-wrapper.properties:3-3` (distributionUrl) |
| build.command.bootjar | ./gradlew clean bootJar | produces the executable Spring Boot JAR for the image | `build.gradle:4-4` (plugin) |
| build.command.bootrun | ./gradlew bootRun | developer run (not used in the container image) | `build.gradle:4-4` (plugin) |
| build.command.test | ./gradlew test | unit/integration tests (CI gate) | `build.gradle:4-4` (plugin) |
| build.artifact_type | executable-jar | the Spring Boot plugin's bootJar produces a self-contained, runnable fat JAR (java -jar). This differs from the plain `jar` task, which produces a thin library JAR that is NOT directly runnable. | `build.gradle:4-4` (plugin) |
| build.artifact | build/libs/spring-petclinic-4.0.0-SNAPSHOT.jar | the runnable JAR to copy into the image / run with `java -jar` | `settings.gradle:1-1` (rootProject.name) |
| runtime.exec_command | java -jar build/libs/spring-petclinic-4.0.0-SNAPSHOT.jar | container command for the Deployment (exec form; JVM is PID 1 for clean SIGTERM) | `settings.gradle:1-1` (rootProject.name) |
| run.command.maven | ./mvnw spring-boot:run | README-declared developer/build command; recorded as repository fact, not selected as the production build path | `README.md:28-28` (fenced-command) |
| run.command.gradle | ./gradlew bootRun | README-declared developer/build command; recorded as repository fact, not selected as the production build path | `README.md:33-33` (fenced-command) |
| image.build_command.maven | ./mvnw spring-boot:build-image | README-declared developer/build command; recorded as repository fact, not selected as the production build path | `README.md:50-50` (fenced-command) |
| profile.mysql.required_env | ['MYSQL_URL', 'MYSQL_USER', 'MYSQL_PASS'] | environment variables the 'mysql' profile needs (URL→ConfigMap, USER/PASS→Secret), sourced from datasource property placeholders | `src/main/resources/application-mysql.properties:3-3` (spring.datasource.url); `src/main/resources/application-mysql.properties:4-4` (spring.datasource.username); `src/main/resources/application-mysql.properties:5-5` (spring.datasource.password) |
| profile.mysql.kubernetes_inputs | {'configmap_keys': ['SPRING_PROFILES_ACTIVE', 'MYSQL_URL'], 'secret_keys': ['MYSQL_USER', 'MYSQL_PASS']} | complete env input set to run the 'mysql' profile in Kubernetes | `src/main/resources/application-mysql.properties:3-3` (spring.datasource.url); `src/main/resources/application-mysql.properties:4-4` (spring.datasource.username); `src/main/resources/application-mysql.properties:5-5` (spring.datasource.password) |
| profile.postgres.required_env | ['POSTGRES_URL', 'POSTGRES_USER', 'POSTGRES_PASS'] | environment variables the 'postgres' profile needs (URL→ConfigMap, USER/PASS→Secret), sourced from datasource property placeholders | `src/main/resources/application-postgres.properties:3-3` (spring.datasource.url); `src/main/resources/application-postgres.properties:4-4` (spring.datasource.username); `src/main/resources/application-postgres.properties:5-5` (spring.datasource.password) |
| profile.postgres.kubernetes_inputs | {'configmap_keys': ['SPRING_PROFILES_ACTIVE', 'POSTGRES_URL'], 'secret_keys': ['POSTGRES_USER', 'POSTGRES_PASS']} | complete env input set to run the 'postgres' profile in Kubernetes | `src/main/resources/application-postgres.properties:3-3` (spring.datasource.url); `src/main/resources/application-postgres.properties:4-4` (spring.datasource.username); `src/main/resources/application-postgres.properties:5-5` (spring.datasource.password) |
| application.summary | Spring PetClinic Sample Application - Spring Petclinic is a Spring Boot application built using Maven or Gradle. Runtime: Spring Boot web application backed by relational tables: owners, pets, specialties, types, vet_specialties, vets, visits | high-level application shape for migration planning, derived from build dependencies and repository schema files; it is not a generated manifest. | `README.md:1-1` (heading.h1); `README.md:16-16` (application-description); `build.gradle:37-37` (dependency[spring-boot-starter-webmvc]); `src/main/resources/db/h2/schema.sql:10-10` (CREATE TABLE vets); `src/main/resources/db/h2/schema.sql:17-17` (CREATE TABLE specialties); `src/main/resources/db/h2/schema.sql:23-23` (CREATE TABLE vet_specialties); `src/main/resources/db/h2/schema.sql:30-30` (CREATE TABLE types); `src/main/resources/db/h2/schema.sql:36-36` (CREATE TABLE owners) |
| application.data_model | ['owners', 'pets', 'specialties', 'types', 'vet_specialties', 'vets', 'visits'] | repository SQL init declares these relational tables; use them as the source-level data-domain inventory when planning database migration. | `src/main/resources/db/h2/schema.sql:10-10` (CREATE TABLE vets); `src/main/resources/db/h2/schema.sql:17-17` (CREATE TABLE specialties); `src/main/resources/db/h2/schema.sql:23-23` (CREATE TABLE vet_specialties); `src/main/resources/db/h2/schema.sql:30-30` (CREATE TABLE types); `src/main/resources/db/h2/schema.sql:36-36` (CREATE TABLE owners); `src/main/resources/db/h2/schema.sql:46-46` (CREATE TABLE pets); `src/main/resources/db/h2/schema.sql:58-58` (CREATE TABLE visits); `src/main/resources/db/mysql/schema.sql:1-1` (CREATE TABLE vets); `src/main/resources/db/mysql/schema.sql:8-8` (CREATE TABLE specialties); `src/main/resources/db/mysql/schema.sql:14-14` (CREATE TABLE vet_specialties); `src/main/resources/db/mysql/schema.sql:22-22` (CREATE TABLE types); `src/main/resources/db/mysql/schema.sql:28-28` (CREATE TABLE owners); `src/main/resources/db/mysql/schema.sql:38-38` (CREATE TABLE pets); `src/main/resources/db/mysql/schema.sql:50-50` (CREATE TABLE visits); `src/main/resources/db/postgres/schema.sql:1-1` (CREATE TABLE vets); `src/main/resources/db/postgres/schema.sql:8-8` (CREATE TABLE specialties); `src/main/resources/db/postgres/schema.sql:14-14` (CREATE TABLE vet_specialties); `src/main/resources/db/postgres/schema.sql:20-20` (CREATE TABLE types); `src/main/resources/db/postgres/schema.sql:26-26` (CREATE TABLE owners); `src/main/resources/db/postgres/schema.sql:36-36` (CREATE TABLE pets); `src/main/resources/db/postgres/schema.sql:47-47` (CREATE TABLE visits) |

### Secret candidates

| Key | Evidence |
| --- | --- |
| k8s.secret_ref.demo-db | `k8s/db.yml:50-50` (secretKeyRef.name) |
| k8s.secret_ref.demo-db | `k8s/db.yml:55-55` (secretKeyRef.name) |
| k8s.secret_ref.demo-db | `k8s/db.yml:60-60` (secretKeyRef.name) |
| MYSQL_USER | `src/main/resources/application-mysql.properties:4-4` (spring.datasource.username) |
| MYSQL_PASS | `src/main/resources/application-mysql.properties:5-5` (spring.datasource.password) |
| POSTGRES_USER | `src/main/resources/application-postgres.properties:4-4` (spring.datasource.username) |
| POSTGRES_PASS | `src/main/resources/application-postgres.properties:5-5` (spring.datasource.password) |

## 6. Startup order & initialization

Overall order (derived):

1. database becomes ready

- startup.sql_init: `spring.sql.init.schema-locations=classpath*:db/${database}/schema.sql; spring.sql.init.data-locations=classpath*:db/${database}/data.sql` — Spring SQL init runs schema/data scripts in-process at application startup (basic script init), NOT a separate migration Job. (explicit); evidence `src/main/resources/application.properties:3-3` (spring.sql.init.schema-locations); `src/main/resources/application.properties:4-4` (spring.sql.init.data-locations)
- startup.migration_tool: `spring.sql.init (no Flyway/Liquibase)` — no versioned migration tool (Flyway/Liquibase) is on the classpath, so there is no dedicated migration Job/initContainer; schema/data are applied in-process at startup. (derived); evidence `build.gradle:1-1` (dependencies)
- startup.sql_init.mode.mysql: `always` — 'mysql' profile forces SQL init to run even against the external DB (mode=always); it re-runs on every pod start. (explicit); evidence `src/main/resources/application-mysql.properties:7-7` (spring.sql.init.mode)
- startup.sql_init.mode.postgres: `always` — 'postgres' profile forces SQL init to run even against the external DB (mode=always); it re-runs on every pod start. (explicit); evidence `src/main/resources/application-postgres.properties:7-7` (spring.sql.init.mode)
- startup.sql_init.idempotent: `3 schema script(s) use IF (NOT) EXISTS guards` — schema DDL is guarded (CREATE TABLE IF NOT EXISTS / DROP TABLE IF EXISTS), so startup SQL init re-runs safely on each pod start; no one-shot migration Job is required. (derived); evidence `src/main/resources/db/h2/schema.sql:1-1` (schema.sql); `src/main/resources/db/mysql/schema.sql:1-1` (schema.sql); `src/main/resources/db/postgres/schema.sql:1-1` (schema.sql)

## 7. Health checks

- health.actuator: `spring-boot-starter-actuator present` — exposes /actuator/health and the Kubernetes liveness/readiness health groups (explicit); evidence `build.gradle:41-41` (dependency[spring-boot-starter-actuator])
- health.exposure: `*` — controls which /actuator/* endpoints are reachable over HTTP (explicit); evidence `src/main/resources/application.properties:21-21` (management.endpoints.web.exposure.include)
- health.liveness_probe: `/actuator/health/liveness` — livenessProbe httpGet path candidate on port 8080. Spring Boot auto-enables the liveness health group when running under Kubernetes. (derived); evidence `build.gradle:41-41` (dependency[spring-boot-starter-actuator]); `src/main/resources/application.properties:21-21` (management.endpoints.web.exposure.include)
- health.readiness_probe: `/actuator/health/readiness` — readinessProbe httpGet path candidate on port 8080. Spring Boot auto-enables the readiness health group when running under Kubernetes. (derived); evidence `build.gradle:41-41` (dependency[spring-boot-starter-actuator]); `src/main/resources/application.properties:21-21` (management.endpoints.web.exposure.include)
- health.overall: `/actuator/health` — overall health endpoint (aggregate) on port 8080 (derived); evidence `build.gradle:41-41` (dependency[spring-boot-starter-actuator]); `src/main/resources/application.properties:21-21` (management.endpoints.web.exposure.include)
- health.additional_paths: `/livez, /readyz require management.endpoint.health.probes.add-additional-paths=true (NOT set in repo)` — use /actuator/health/liveness and /actuator/health/readiness by default. Only probe /livez and /readyz if you enable add-additional-paths=true (e.g. via env/ConfigMap). (unresolved); evidence `build.gradle:41-41` (dependency[spring-boot-starter-actuator]); `src/main/resources/application.properties:21-21` (management.endpoints.web.exposure.include)

## 8. Build-time constraints

_None detected._

## 8b. Container image build & runtime

- image.dockerfile: **none (no application Dockerfile)** — no Dockerfile — but this does NOT mean the app cannot be containerised (see bootBuildImage) (explicit)
  - evidence: —
- image.buildpack_support: **True** — the Spring Boot Gradle plugin provides `bootBuildImage`, which builds an OCI image with Cloud Native Buildpacks — no Dockerfile needed. (derived)
  - evidence: `build.gradle:4-4` (plugin)
- image.build_command: **./gradlew bootBuildImage** — builds the container image via buildpacks (requires a Docker daemon or rootless builder) (derived)
  - evidence: `build.gradle:4-4` (plugin)
- image.build_strategy: **buildpack (bootBuildImage) vs Dockerfile** — buildpacks auto-detect the JDK/JRE and layer the app for you (reproducible, maintained base images); a Dockerfile gives full control but you own the base image and CVE patching. (derived)
  - evidence: `build.gradle:4-4` (plugin)
- image.runs_as_nonroot: **buildpack image runs as non-root by default** — Paketo/Spring buildpack images run as the non-root `cnb` user, so securityContext.runAsNonRoot is satisfied when built via bootBuildImage (still set it explicitly). (derived)
  - evidence: `build.gradle:4-4` (plugin)

## 9. Unresolved operational inputs

_These are NOT decided from the repository. No default values were invented._

| Subject | Why unresolved | Input needed | Kubernetes effect |
| --- | --- | --- | --- |
| production_database_selection | the repo supports an embedded H2 default plus external mysql, postgres profiles; which one to run in production is not decided by the repository | choose a profile (e.g. postgres or mysql) and supply the JDBC URL + credentials | SPRING_PROFILES_ACTIVE (ConfigMap) + datasource ConfigMap/Secret; external DB Service |
| database_service_endpoint | the repo declares datasource placeholders but does not decide the destination database host/service name, JDBC URL value, or Secret key mapping for the selected profile | the database service endpoint/JDBC URL and the Secret keys to map into datasource env vars | ConfigMap datasource URL + Secret-backed datasource username/password env |
| service_port_and_type | the repository determines the container/service targetPort but not how the app is exposed inside or outside the destination cluster | Service port/type and, if externally exposed, the Ingress/Gateway route | Service.spec.ports[].port, Service.spec.type, and optional Ingress/Gateway |
| container_image_name | bootBuildImage's image name/registry is not pinned in the repo | target image coordinates, e.g. registry/namespace/spring-petclinic:<tag> | Deployment.spec.template.spec.containers[].image |
| health_probe_additional_paths | the repo does not enable management.endpoint.health.probes.add-additional-paths | decide whether to expose /livez,/readyz or use /actuator/health/{liveness,readiness} | livenessProbe/readinessProbe httpGet.path |
| startup_probe | JVM/Spring Boot cold-start time is environment-dependent and not stated in the repo | expected startup duration to size startupProbe failureThreshold/periodSeconds | container.startupProbe (protects a slow-starting JVM from liveness restarts) |
| graceful_shutdown | server.shutdown=graceful is not set in the repo (Spring Boot defaults to immediate shutdown) | whether to enable graceful shutdown and the drain timeout | server.shutdown + spring.lifecycle.timeout-per-shutdown-phase; terminationGracePeriodSeconds |
| security_context_run_as_non_root | runAsNonRoot/UID is a deployment policy; buildpack images default to non-root but it is not pinned | target UID/GID and runAsNonRoot policy | Pod/container securityContext |
| replica_count | desired availability/throughput is an operational decision, not in the repo | target replicas per Deployment (SLO / load expectations) | Deployment.spec.replicas |
| resource_requests_limits | repo contains no CPU/memory sizing information | measured or estimated CPU/memory per component | container resources.requests / resources.limits |
| ingress_class | cluster ingress controller is environment-specific and not declared in the repo | target IngressClass in the destination cluster | Ingress.spec.ingressClassName |
| horizontal_pod_autoscaler | no scaling policy is expressed in the repo | scaling metric and min/max replicas | HorizontalPodAutoscaler |
| pod_disruption_budget | availability tolerance during disruptions is an operational decision | minAvailable/maxUnavailable policy | PodDisruptionBudget |
| pvc_size | database volume size is not declared in the repo | expected data volume / growth for the database PVC | PersistentVolumeClaim.spec.resources.requests.storage |
| storage_class | storage backend is cluster-specific | target StorageClass in the destination cluster | PersistentVolumeClaim.spec.storageClassName |
| database_ha_and_backup | repo runs a single-container DB; HA and backup are operational policy | managed DB vs in-cluster HA, and backup/restore policy | operator/StatefulSet topology, backup CronJobs |

## 10. Warnings & unsupported constructs

Warnings:

- [multiple_build_systems] multiple build systems detected (gradle, maven); analysis uses 'gradle'. Override with --build-system {gradle,maven}.

_No unsupported constructs._

## Migration questions

1. **어떤 애플리케이션인가?**
   - Status: `answered`
   - Answer: mysql: MySQL; postgres: PostgreSQL; spring-petclinic: Spring Boot 4.1.0 application on an embedded servlet container (Tomcat); self-contained executable JAR
   - Basis: components.mysql; components.postgres; components.spring-petclinic
   - Missing: —
2. **어떻게 빌드하고 실행하는가?**
   - Status: `partial`
   - Answer: spring-petclinic: Gradle 9.5.1 (gradlew wrapper), build `./gradlew clean bootJar`
   - Basis: components.spring-petclinic
   - Missing: mysql build/run command; postgres build/run command
3. **어떤 Port와 Service가 필요한가?**
   - Status: `answered`
   - Answer: mysql targetPort 3306; postgres targetPort 5432; spring-petclinic targetPort 8080; mysql -> StatefulSet + headless Service (or external managed database); postgres -> StatefulSet + headless Service (or external managed database); spring-petclinic -> Deployment + ClusterIP Service; k8s.service_port.demo-db: 5432; k8s.container_port.demo-db: 5432; k8s.service_port.petclinic: 80; k8s.service_port.petclinic: 8080; k8s.container_port.petclinic: 8080
   - Basis: networking.k8s.service_port.demo-db (`k8s/db.yml:23-23` (port)); networking.k8s.container_port.demo-db (`k8s/db.yml:63-63` (containerPort)); networking.k8s.service_port.petclinic (`k8s/petclinic.yml:9-9` (port)); networking.k8s.service_port.petclinic (`k8s/petclinic.yml:10-10` (targetPort)); networking.k8s.container_port.petclinic (`k8s/petclinic.yml:46-46` (containerPort)); networking.mysql.container_port (`docker-compose.yml:3-3` ($.services.mysql.image)); networking.postgres.container_port (`docker-compose.yml:15-15` ($.services.postgres.image)); networking.app.default_port (`build.gradle:37-37` (dependency[spring-boot-starter-webmvc]); `README.md:36-36` (README)); networking.service.target_port (`build.gradle:37-37` (dependency[spring-boot-starter-webmvc]); `README.md:36-36` (README)); workload_mappings.mysql (`docker-compose.yml:3-3` ($.services.mysql)); workload_mappings.postgres (`docker-compose.yml:15-15` ($.services.postgres)); workload_mappings.spring-petclinic (`build.gradle:1-1` (plugins))
   - Missing: —
4. **어떤 외부 의존성이 있는가?**
   - Status: `answered`
   - Answer: database.default: h2 (embedded, in-memory); database.profile.mysql: External MySQL; database.profile.postgres: External PostgreSQL
   - Basis: runtime_dependencies.database.default (`src/main/resources/application.properties:2-2` (database)); runtime_dependencies.database.profile.mysql (`src/main/resources/application-mysql.properties:3-3` (spring.datasource.url)); runtime_dependencies.database.profile.postgres (`src/main/resources/application-postgres.properties:3-3` (spring.datasource.url))
   - Missing: —
5. **어떤 ConfigMap과 Secret이 필요한가?**
   - Status: `answered`
   - Answer: ConfigMap candidates: 3; Secret candidates: 7
   - Basis: configuration.config.SPRING_PROFILES_ACTIVE (`src/main/resources/application-mysql.properties:3-3` (spring.datasource.url); `src/main/resources/application-postgres.properties:3-3` (spring.datasource.url)); configuration.config.MYSQL_URL (`src/main/resources/application-mysql.properties:3-3` (spring.datasource.url)); configuration.config.POSTGRES_URL (`src/main/resources/application-postgres.properties:3-3` (spring.datasource.url)); secrets.k8s.secret_ref.demo-db (`k8s/db.yml:50-50` (secretKeyRef.name)); secrets.k8s.secret_ref.demo-db (`k8s/db.yml:55-55` (secretKeyRef.name)); secrets.k8s.secret_ref.demo-db (`k8s/db.yml:60-60` (secretKeyRef.name)); secrets.secret.MYSQL_USER (`src/main/resources/application-mysql.properties:4-4` (spring.datasource.username)); secrets.secret.MYSQL_PASS (`src/main/resources/application-mysql.properties:5-5` (spring.datasource.password)); secrets.secret.POSTGRES_USER (`src/main/resources/application-postgres.properties:4-4` (spring.datasource.username)); secrets.secret.POSTGRES_PASS (`src/main/resources/application-postgres.properties:5-5` (spring.datasource.password))
   - Missing: —
6. **어떤 데이터가 영속되어야 하는가?**
   - Status: `answered`
   - Answer: storage.application_pvc: not required; storage.database_persistence: {'profiles': ['mysql', 'postgres'], 'tables': ['owners', 'pets', 'specialties', 'types', 'vet_specialties', 'vets', 'visits']}
   - Basis: storage.storage.application_pvc (`build.gradle:1-1` (dependencies)); storage.storage.database_persistence (`src/main/resources/db/h2/schema.sql:10-10` (CREATE TABLE vets); `src/main/resources/db/h2/schema.sql:17-17` (CREATE TABLE specialties); `src/main/resources/db/h2/schema.sql:23-23` (CREATE TABLE vet_specialties); `src/main/resources/db/h2/schema.sql:30-30` (CREATE TABLE types); `src/main/resources/db/h2/schema.sql:36-36` (CREATE TABLE owners); `src/main/resources/db/h2/schema.sql:46-46` (CREATE TABLE pets); `src/main/resources/db/h2/schema.sql:58-58` (CREATE TABLE visits); `src/main/resources/db/mysql/schema.sql:1-1` (CREATE TABLE vets); `src/main/resources/db/mysql/schema.sql:8-8` (CREATE TABLE specialties); `src/main/resources/db/mysql/schema.sql:14-14` (CREATE TABLE vet_specialties); `src/main/resources/db/mysql/schema.sql:22-22` (CREATE TABLE types); `src/main/resources/db/mysql/schema.sql:28-28` (CREATE TABLE owners); `src/main/resources/db/mysql/schema.sql:38-38` (CREATE TABLE pets); `src/main/resources/db/mysql/schema.sql:50-50` (CREATE TABLE visits); `src/main/resources/db/postgres/schema.sql:1-1` (CREATE TABLE vets); `src/main/resources/db/postgres/schema.sql:8-8` (CREATE TABLE specialties); `src/main/resources/db/postgres/schema.sql:14-14` (CREATE TABLE vet_specialties); `src/main/resources/db/postgres/schema.sql:20-20` (CREATE TABLE types); `src/main/resources/db/postgres/schema.sql:26-26` (CREATE TABLE owners); `src/main/resources/db/postgres/schema.sql:36-36` (CREATE TABLE pets); `src/main/resources/db/postgres/schema.sql:47-47` (CREATE TABLE visits)); runtime_dependencies.database.default (`src/main/resources/application.properties:2-2` (database)); runtime_dependencies.database.profile.mysql (`src/main/resources/application-mysql.properties:3-3` (spring.datasource.url)); runtime_dependencies.database.profile.postgres (`src/main/resources/application-postgres.properties:3-3` (spring.datasource.url))
   - Missing: —
7. **Repository만으로 결정할 수 없는 값은 무엇인가?**
   - Status: `answered`
   - Answer: production_database_selection; database_service_endpoint; service_port_and_type; container_image_name; health_probe_additional_paths; startup_probe; graceful_shutdown; security_context_run_as_non_root; replica_count; resource_requests_limits; ingress_class; horizontal_pod_autoscaler; pod_disruption_budget; pvc_size; storage_class; database_ha_and_backup
   - Basis: unresolved_operational_inputs.production_database_selection; unresolved_operational_inputs.database_service_endpoint; unresolved_operational_inputs.service_port_and_type; unresolved_operational_inputs.container_image_name; unresolved_operational_inputs.health_probe_additional_paths; unresolved_operational_inputs.startup_probe; unresolved_operational_inputs.graceful_shutdown; unresolved_operational_inputs.security_context_run_as_non_root; unresolved_operational_inputs.replica_count; unresolved_operational_inputs.resource_requests_limits; unresolved_operational_inputs.ingress_class; unresolved_operational_inputs.horizontal_pod_autoscaler; unresolved_operational_inputs.pod_disruption_budget; unresolved_operational_inputs.pvc_size; unresolved_operational_inputs.storage_class; unresolved_operational_inputs.database_ha_and_backup
   - Missing: choose a profile (e.g. postgres or mysql) and supply the JDBC URL + credentials; the database service endpoint/JDBC URL and the Secret keys to map into datasource env vars; Service port/type and, if externally exposed, the Ingress/Gateway route; target image coordinates, e.g. registry/namespace/spring-petclinic:<tag>; decide whether to expose /livez,/readyz or use /actuator/health/{liveness,readiness}; expected startup duration to size startupProbe failureThreshold/periodSeconds; whether to enable graceful shutdown and the drain timeout; target UID/GID and runAsNonRoot policy; target replicas per Deployment (SLO / load expectations); measured or estimated CPU/memory per component; target IngressClass in the destination cluster; scaling metric and min/max replicas; minAvailable/maxUnavailable policy; expected data volume / growth for the database PVC; target StorageClass in the destination cluster; managed DB vs in-cluster HA, and backup/restore policy

