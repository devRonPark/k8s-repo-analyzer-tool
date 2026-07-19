# src/repo_analyzer/rules/

Pure rule engine — no filesystem I/O. Takes parsed facts, produces `AnalysisResult`.

## Files

| File | Lines | Role |
|---|---|---|
| `__init__.py` | 0 | Package marker |
| `kubernetes_p0.py` | — | Orchestrating rule module. Runs the compose path (per-service analysis, config/secrets, startup), resolves implicit `<context>/Dockerfile`, derives container ports (incl. published-mapping fallback), resolves the build system, then delegates to `spring_boot` (gradle) or `java_webapp` (maven). With no deployment compose and no Java build system, synthesizes a component from the primary Dockerfile (`_analyze_dockerfile_component`: runtime via root-base-image alias resolution, EXPOSE/`--port`, non-root USER, multi-stage targets, migration stage) + dotenv config/secrets + Alembic init. Compose files under documentation/examples/test paths are ignored (warning). All compose-side confidence labeling lives here. |
| `build_system.py` | — | Detect + select the build system (never "first pom.xml"). Lists every build system present, records the selection + rationale + how to switch, warns on ambiguity; `auto` is deterministic (Spring Boot build preferred, else fixed `gradle,maven` order). Honours `--build-system`. Emits `build.system` / `build.system.selection` findings. |
| `java_webapp.py` | — | Maven/WAR rules. Enriches the matching compose component (or synthesizes one without compose): language/frameworks/build/artifact, external servlet container + profiles, context path, servlet routes, embedded vs external datastore, image build/run risks, Dockerfile↔README↔POM cross-checks, Java-specific `unresolved`. Also consumes parsed Spring `application*` config (`.properties`/`.yml`, test scopes excluded) for the default 8080 port, per-profile datasources (external DB vs embedded), and datasource/JWT/keystore env → ConfigMap(URL)/Secret(credentials) candidates (env names via the standard Spring relaxed-binding mapping, cited to the source property). Only matches a component that has a build context (an image-only DB service must not absorb app facts). Pure; must not import `kubernetes_p0` (one-way). |
| `spring_boot.py` | — | Spring Boot / Gradle rules. Synthesizes the app component: Java toolchain, Spring Boot version + starters (WebFlux→reactive/Netty vs servlet/Tomcat), gradlew + bootJar/bootRun/test (module-qualified `:api:bootJar` in a multi-module repo), executable-JAR artifact resolved to the deployable module (`build/libs/<name>-<version>.jar` at root, else `api/build/libs/api-*.jar` — module-dir base name, version wildcarded when undeclared in the module), `-P` build properties (`build.property.*` build-time constraints + a `build_profile_properties` unresolved input, e.g. `-Pinclude-frontend`), default 8080, Actuator liveness/readiness (+`/livez`,`/readyz` only when `add-additional-paths` enabled), `bootBuildImage` without a Dockerfile, app-needs-no-PVC, Spring-specific `unresolved`. DB-related facts (H2 default, `SPRING_PROFILES_ACTIVE`, `spring.sql.init`, `production_database_selection`) are emitted **only when `_has_db_evidence`** holds (a JDBC driver, JPA/JDBC starter, datasource/`database` property, or non-demo SQL init) — never invented for a DB-less app; the image-name example uses the real project name. Pure; one-way. |

## Invariants

- Pure functions: parsed data in → `AnalysisResult` out (mutation only).
- Never invent operational values (replica, CPU, memory, PVC size → `unresolved`).
- Every `derived` finding links all source evidence.
- `java_webapp` never re-fetches facts the parsers didn't produce; it maps
  explicit Maven/servlet/Spring facts to derived Kubernetes conclusions only.
