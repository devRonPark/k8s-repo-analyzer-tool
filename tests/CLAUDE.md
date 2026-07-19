# tests/

All tests run fully offline — no network access.

## Files

| File | Lines | Role |
|---|---|---|
| `__init__.py` | 0 | Package marker |
| `conftest.py` | 16 | Shared pytest fixtures (fixture paths, tmp dirs) |
| `test_parser_compose.py` | 52 | Compose YAML parser unit tests |
| `test_parser_dockerfile.py` | 41 | Dockerfile parser unit tests |
| `test_parser_dotenv.py` | 31 | `.env` parser unit tests |
| `test_parser_nginx.py` | 27 | Nginx config parser unit tests |
| `test_parser_python_settings.py` | 34 | Python BaseSettings AST parser unit tests |
| `test_parser_maven.py` | — | Maven `pom.xml` parser unit tests (packaging, java version+line, dep scope, profiles, `${prop}` left verbatim) |
| `test_parser_webxml.py` | — | Servlet `web.xml` parser unit tests |
| `test_parser_spring_xml.py` | — | Spring datasource detector (embedded/external/CDI-negative) |
| `test_parser_gradle.py` | — | Gradle build-script parser (plugins+versions+lines, toolchain, deps w/ configuration, Groovy+Kotlin, settings, wrapper, unsupported-plugin recorded) |
| `test_parser_spring_properties.py` | — | `application*.properties` parser (keys/values/lines, profile-from-filename, `${ENV:default}` placeholders) |
| `test_parser_sql_init.py` | — | SQL init idempotency scanner (IF NOT EXISTS, DROP IF EXISTS, non-idempotent, data-only) |
| `test_golden_analysis.py` | 143 | Golden integration — full pipeline against `fixtures/full-stack-fastapi/` |
| `test_golden_jpetstore.py` | — | Golden integration (Maven WAR) — structured assertions against `fixtures/jpetstore-6/` |
| `test_golden_spring_petclinic.py` | — | Golden integration (Spring Boot + Gradle) — structured assertions against `fixtures/spring-petclinic/` (build system, JAR, port, profiles, env classification, SQL init, probes, bootBuildImage, PVC, determinism, not-modified) |
| `test_petclinic_k8s_ground_truth.py` | — | Compares source-only analysis vs spring-petclinic's own `k8s/` manifests (targetPort, active profile, probes, no app PVC, DB Secret); asserts the `/livez`,`/readyz` difference is surfaced |
| `test_build_system_selection.py` | — | Build-system detection/selection on synthetic repos (gradle-only, maven-only, both→gradle+warning, explicit override, requested-absent fallback, invalid rejected) |
| `test_java_generalization.py` | — | Category regression: implicit Dockerfile, published-port fallback, Maven-without-compose, Maven `-Pprod clean verify` build command from README, Maven actuator-from-pom probes (base-path `/management` vs default `/actuator`, unresolved suppressed) + no-actuator guard, `jib-maven-plugin` detection, empty-repo guard, jpetstore not modified |
| `test_spring_boot_generalization.py` | — | Category regression on a synthetic (non-fixture) Gradle Spring Boot repo: name/port/env derived from content, server.port override, `/livez`,`/readyz` only when enabled, no-actuator case, PVC not required; multi-module artifact path (`api/build/libs/api-*.jar`) + module-qualified `:api:bootJar` + single-module unchanged, `-P` build-property surfaced |
| `test_determinism_and_errors.py` | 63 | Byte-level determinism, bad-profile, missing-file, repo-not-modified checks |

## Fixtures

`fixtures/full-stack-fastapi/` — pinned local copy of P0-relevant files from
`fastapi/full-stack-fastapi-template` @ `4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8`.

`fixtures/jpetstore-6/` — pinned local copy of P0-relevant files from
`mybatis/jpetstore-6` @ `5a7cc780505b88a60779b3e3c0a50b0e404cfb2d` (Maven WAR on
an external servlet container). `mvnw`/`mvnw.cmd` are minimal placeholders — only
their presence drives build-tool detection; the analyzer never reads them.

`fixtures/spring-petclinic/` — pinned local copy of P0-relevant files from
`spring-projects/spring-petclinic` @ `f182358d02e4a68e52bdbabf55ca7800288511e7`
(Spring Boot 4.x; ships **both** `build.gradle` and `pom.xml`). `gradlew`/`mvnw`
are presence-only placeholders. The upstream `k8s/` manifests are included as
**ground-truth reference only** — the analyzer never reads them; only
`test_petclinic_k8s_ground_truth.py` parses them, to compare against the
source-derived analysis.

Never fetch from network; never modify a fixture without updating golden expectations.
