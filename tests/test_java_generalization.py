"""Category-level regression tests for the generalized analysis behaviours.

These do not depend on the jpetstore fixture; they assert the reusable rules the
Java/WAR work introduced: implicit compose Dockerfile resolution, deriving a
container port from a published mapping, and analysing a Maven web app that has
no compose file at all.
"""

from __future__ import annotations

from repo_analyzer.analyzer import analyze_repository

_BOOT_POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>svc</artifactId>
  <version>0.0.1</version>
  <packaging>jar</packaging>
  <properties><java.version>21</java.version></properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
      <version>3.3.0</version>
    </dependency>
  </dependencies>
  <build><finalName>svc</finalName></build>
</project>
"""

_WAR_POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>app</artifactId>
  <version>1.0.0</version>
  <packaging>war</packaging>
  <properties><java.version>17</java.version></properties>
  <dependencies>
    <dependency>
      <groupId>jakarta.servlet</groupId>
      <artifactId>jakarta.servlet-api</artifactId>
      <version>4.0.4</version>
      <scope>provided</scope>
    </dependency>
  </dependencies>
  <build><finalName>app</finalName></build>
</project>
"""


def test_implicit_dockerfile_and_published_port(tmp_path):
    (tmp_path / "compose.yml").write_text(
        "services:\n"
        "  api:\n"
        "    build:\n"
        "      context: ./svc\n"
        "    ports:\n"
        '      - "9090:8080"\n'
    )
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "Dockerfile").write_text("FROM python:3.12\nCMD [\"python\", \"app.py\"]\n")

    result = analyze_repository(str(tmp_path))
    api = next(c for c in result.components if c.name == "api")
    # Implicit "<context>/Dockerfile" resolved even though compose omits it.
    assert api.dockerfile == "svc/Dockerfile"
    # Container port derived from the container side of the published mapping.
    assert api.container_ports == [8080]
    port = next(f for f in result.networking if f.subject == "api.container_port")
    assert port.evidence[0].symbol == "ports.published"


def test_maven_spring_boot_consumes_application_yaml(tmp_path):
    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (tmp_path / "pom.xml").write_text(_BOOT_POM)
    (tmp_path / "Dockerfile").write_text(
        'FROM eclipse-temurin:21-jre\nCOPY target/svc.jar /app.jar\nCMD ["java","-jar","/app.jar"]\n'
    )
    (res / "application.yml").write_text(
        "management:\n"
        "  endpoints:\n"
        "    web:\n"
        "      exposure:\n"
        "        include: health,info\n"
        "cors:\n"
        "  allow-credentials: true\n"
        "jhipster:\n"
        "  security:\n"
        "    authentication:\n"
        "      jwt:\n"
        "        base64-secret: c2VjcmV0\n"
    )
    (res / "application-prod.yml").write_text(
        "spring:\n"
        "  datasource:\n"
        "    url: jdbc:postgresql://db:5432/app\n"
        "    username: appuser\n"
        "    password:\n"
    )
    # Test-scoped config MUST be excluded from deployment analysis.
    test_res = tmp_path / "src" / "test" / "resources"
    test_res.mkdir(parents=True)
    (test_res / "application.yml").write_text(
        "spring:\n  datasource:\n    url: jdbc:h2:mem:testdb\n    password: testpw\n"
    )
    # Build output (target/) is a COPY of resources; must be ignored (determinism:
    # analysis must not depend on whether the repo was built).
    built = tmp_path / "target" / "classes"
    built.mkdir(parents=True)
    (built / "application-prod.yml").write_text((res / "application-prod.yml").read_text())

    result = analyze_repository(str(tmp_path))
    svc = next(c for c in result.components if (c.language or "").startswith("Java"))
    # No server.port -> Spring Boot embedded default 8080 (derived).
    assert svc.container_ports == [8080]
    assert any(f.subject == "app.default_port" and f.value == 8080 for f in result.networking)
    # External PostgreSQL from the prod-profile datasource URL, emitted exactly ONCE
    # (build-output copy under target/ is ignored -> no duplication).
    prod_dbs = [f for f in result.runtime_dependencies if f.subject == "database.prod"]
    assert len(prod_dbs) == 1 and "PostgreSQL" in prod_dbs[0].value
    # Datasource credentials + JWT secret -> Secret candidates (standard Spring env mapping).
    assert "SPRING_DATASOURCE_PASSWORD" in svc.secret_candidates
    assert "JHIPSTER_SECURITY_AUTHENTICATION_JWT_BASE64_SECRET" in svc.secret_candidates
    # URL -> ConfigMap candidate, NOT a Secret.
    assert "SPRING_DATASOURCE_URL" in svc.environment
    assert "SPRING_DATASOURCE_URL" not in svc.secret_candidates
    # A boolean CORS flag must NOT be mistaken for a secret.
    assert not any("CREDENTIALS" in s for s in svc.secret_candidates)
    # Test config excluded: no H2 leaked as a dependency.
    assert not any("H2" in (f.value or "") for f in result.runtime_dependencies)
    # YAML is parsed now, never flagged wholesale-unsupported.
    assert not any(u.construct_type == "spring_yaml_config" for u in result.unsupported_constructs)


def test_maven_war_without_compose(tmp_path):
    (tmp_path / "pom.xml").write_text(_WAR_POM)
    (tmp_path / "Dockerfile").write_text(
        "FROM tomcat:9-jre17\nCOPY target/app.war /usr/local/tomcat/webapps/app.war\n"
    )

    result = analyze_repository(str(tmp_path))
    # No compose, but a Maven app is present: do NOT emit no_compose.
    assert not any(w.code == "no_compose" for w in result.warnings)
    app = next(c for c in result.components if c.name == "app")
    assert app.packaging == "war"
    assert app.language == "Java 17"
    assert app.context_path == "/app"
    assert app.application_server is not None
    assert "external servlet container" in app.application_server.lower()
    mapping = next(w for w in result.workload_mappings if w.component == "app")
    assert "Deployment" in mapping.kubernetes_kind


def test_maven_prod_profile_build_command_from_readme(tmp_path):
    # jhipster-style: the production build is `./mvnw -Pprod clean verify` (verify,
    # not package). The prod profile flag must NOT be dropped from the build command.
    (tmp_path / "pom.xml").write_text(_BOOT_POM)
    (tmp_path / "Dockerfile").write_text(
        'FROM eclipse-temurin:21-jre\nCOPY target/svc.jar /app.jar\nCMD ["java","-jar","/app.jar"]\n'
    )
    (tmp_path / "README.md").write_text(
        "# svc\n\nTo build for production run:\n\n    ./mvnw -Pprod clean verify\n"
    )
    result = analyze_repository(str(tmp_path))
    svc = next(c for c in result.components if (c.language or "").startswith("Java"))
    assert svc.build_command == "./mvnw -Pprod clean verify"


_ACTUATOR_POM = _BOOT_POM.replace(
    "  </dependencies>",
    "    <dependency>\n"
    "      <groupId>org.springframework.boot</groupId>\n"
    "      <artifactId>spring-boot-starter-actuator</artifactId>\n"
    "      <version>3.3.0</version>\n"
    "    </dependency>\n"
    "  </dependencies>",
)

_JIB_POM = _BOOT_POM.replace(
    "<build><finalName>svc</finalName></build>",
    "<build><finalName>svc</finalName><plugins>\n"
    "    <plugin>\n"
    "      <groupId>com.google.cloud.tools</groupId>\n"
    "      <artifactId>jib-maven-plugin</artifactId>\n"
    "      <version>3.4.0</version>\n"
    "    </plugin>\n"
    "  </plugins></build>",
)


def test_maven_actuator_probes_from_pom(tmp_path):
    # spring-boot-starter-actuator in the POM is the readiness/liveness source; the
    # probe paths honour management.endpoints.web.base-path (jhipster uses /management).
    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (tmp_path / "pom.xml").write_text(_ACTUATOR_POM)
    (tmp_path / "Dockerfile").write_text(
        'FROM eclipse-temurin:21-jre\nCOPY target/svc.jar /app.jar\nCMD ["java","-jar","/app.jar"]\n'
    )
    (res / "application.yml").write_text(
        "management:\n"
        "  endpoints:\n"
        "    web:\n"
        "      base-path: /management\n"
        "      exposure:\n"
        "        include: health,info\n"
    )
    result = analyze_repository(str(tmp_path))
    hc = {f.subject: f for f in result.health_checks}
    assert hc["health.actuator"].value.startswith("spring-boot-starter-actuator")
    assert hc["health.actuator"].confidence == "explicit"
    assert hc["health.liveness_probe"].value == "/management/health/liveness"
    assert hc["health.readiness_probe"].value == "/management/health/readiness"
    assert hc["health.overall"].value == "/management/health"
    # Actuator present -> do NOT also claim "no health endpoint" as unresolved.
    assert "readiness_liveness_probe" not in {
        u.subject for u in result.unresolved_operational_inputs
    }


def test_maven_actuator_default_base_path(tmp_path):
    # No management.base-path -> Spring Boot default /actuator.
    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (tmp_path / "pom.xml").write_text(_ACTUATOR_POM)
    (res / "application.yml").write_text(
        "management:\n  endpoints:\n    web:\n      exposure:\n        include: '*'\n"
    )
    result = analyze_repository(str(tmp_path))
    hc = {f.subject: f for f in result.health_checks}
    assert hc["health.liveness_probe"].value == "/actuator/health/liveness"


def test_maven_without_actuator_keeps_probe_unresolved(tmp_path):
    # Regression guard: no actuator -> no health finding, probe stays unresolved.
    (tmp_path / "pom.xml").write_text(_BOOT_POM)
    result = analyze_repository(str(tmp_path))
    assert not any(f.subject == "health.actuator" for f in result.health_checks)
    assert "readiness_liveness_probe" in {
        u.subject for u in result.unresolved_operational_inputs
    }


def test_maven_jib_plugin_detected_without_dockerfile(tmp_path):
    # jib-maven-plugin builds an OCI image with no Dockerfile; it IS the image recipe.
    (tmp_path / "pom.xml").write_text(_JIB_POM)
    result = analyze_repository(str(tmp_path))
    jib = next(f for f in result.container_image if f.subject == "image.jib")
    assert "jib" in jib.value.lower()
    assert jib.evidence and jib.evidence[0].path == "pom.xml"
    assert not any(f.value == "no Dockerfile found" for f in result.container_image)


def test_empty_repo_still_reports_no_compose(tmp_path):
    # Regression guard: with neither compose nor Maven, the honest signal remains.
    result = analyze_repository(str(tmp_path))
    assert result.components == []
    assert any(w.code == "no_compose" for w in result.warnings)


def test_jpetstore_fixture_not_modified(jpetstore_repo, tmp_path):
    import hashlib
    import shutil

    def digest(root):
        sha = hashlib.sha256()
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            sha.update(path.relative_to(root).as_posix().encode())
            sha.update(path.read_bytes())
        return sha.hexdigest()

    copy = tmp_path / "repo"
    shutil.copytree(jpetstore_repo, copy)
    before = digest(copy)
    analyze_repository(str(copy))
    assert digest(copy) == before
