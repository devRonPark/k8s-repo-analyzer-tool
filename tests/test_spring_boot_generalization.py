"""Category-level regression tests for the Spring Boot (Gradle) analysis.

These use synthetic repositories with names, ports and env vars that differ from
the spring-petclinic fixture, proving the facts are derived from parsed content
rather than any fixture-specific hardcoding.
"""

from __future__ import annotations

from repo_analyzer.analyzer import analyze_repository

_GRADLE = """\
plugins {
  id 'java'
  id 'org.springframework.boot' version '3.4.1'
  id 'io.spring.dependency-management' version '1.1.7'
}
group = 'com.acme'
version = '9.9.9'
java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }
dependencies {
  implementation 'org.springframework.boot:spring-boot-starter-web'
  runtimeOnly 'org.springframework.boot:spring-boot-starter-actuator'
  runtimeOnly 'com.h2database:h2'
  runtimeOnly 'org.postgresql:postgresql'
}
"""

_APP_PROPS = """\
database=h2
spring.sql.init.schema-locations=classpath*:db/${database}/schema.sql
management.endpoints.web.exposure.include=*
"""

_APP_POSTGRES = """\
database=postgres
spring.datasource.url=${DB_URL:jdbc:postgresql://localhost/orders}
spring.datasource.username=${DB_USER:orders}
spring.datasource.password=${DB_PASSWORD:orders}
spring.sql.init.mode=always
"""


def _make_repo(tmp_path, *, name="orders-service", app_props=_APP_PROPS, extra=None):
    (tmp_path / "build.gradle").write_text(_GRADLE)
    (tmp_path / "settings.gradle").write_text(f"rootProject.name = '{name}'\n")
    (tmp_path / "gradlew").write_text("#!/bin/sh\n")
    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.properties").write_text(app_props)
    (res / "application-postgres.properties").write_text(_APP_POSTGRES)
    if extra:
        for rel, content in extra.items():
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    return analyze_repository(str(tmp_path))


_CATALOG = """\
[versions]
spring-boot = "3.5.0"

[libraries]
spring-starter-webflux = { module = "org.springframework.boot:spring-boot-starter-webflux", version.ref = "spring-boot" }
spring-starter-actuator = { module = "org.springframework.boot:spring-boot-starter-actuator", version.ref = "spring-boot" }

[plugins]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }
"""

_ROOT_GRADLE = "plugins {\n  id 'base'\n}\n"

_API_GRADLE = """\
plugins {
  alias(libs.plugins.spring.boot)
}
group = 'io.acme'
version = '2.1.0'
java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }
dependencies {
  implementation libs.spring.starter.webflux
  implementation libs.spring.starter.actuator
}
"""


def test_version_catalog_resolves_reactive_app_with_no_invented_db(tmp_path):
    # Multi-module Gradle repo: the app lives in api/, deps come via a version
    # catalog, and there is NO database anywhere.
    (tmp_path / "build.gradle").write_text(_ROOT_GRADLE)
    (tmp_path / "settings.gradle").write_text("rootProject.name = 'events-ui'\ninclude 'api'\n")
    (tmp_path / "gradlew").write_text("#!/bin/sh\n")
    (tmp_path / "gradle").mkdir()
    (tmp_path / "gradle" / "libs.versions.toml").write_text(_CATALOG)
    api = tmp_path / "api"
    api.mkdir()
    (api / "build.gradle").write_text(_API_GRADLE)
    res = api / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "management:\n  endpoints:\n    web:\n      exposure:\n        include: health,info\n"
    )
    # A demo SQL init under documentation/ must NOT be treated as the app's DB.
    demo = tmp_path / "documentation" / "compose" / "postgres"
    demo.mkdir(parents=True)
    (demo / "data.sql").write_text("INSERT INTO x VALUES (1);\n")

    result = analyze_repository(str(tmp_path))
    comp = next(c for c in result.components if c.name == "events-ui")
    # Catalog resolved -> the api module (not root) is analysed; WebFlux/Actuator visible.
    assert "api/build.gradle" in comp.source_files
    assert "Netty" in (comp.runtime or "")
    assert any("WebFlux" in f for f in comp.frameworks)
    assert any(h.subject == "health.actuator" and "present" in h.value for h in result.health_checks)
    # No database -> no invented H2/Postgres/MySQL story.
    assert not any(f.subject == "config.SPRING_PROFILES_ACTIVE" for f in result.configuration)
    assert not any(f.subject == "startup.migration_tool" for f in result.startup_order)
    assert "production_database_selection" not in {
        u.subject for u in result.unresolved_operational_inputs
    }
    # Image-name example uses the real project name, never a hardcoded fixture name.
    img = next(u for u in result.unresolved_operational_inputs if u.subject == "container_image_name")
    assert "events-ui" in img.needed_input and "petclinic" not in img.needed_input


def _app(result, name="orders-service"):
    return next(c for c in result.components if c.name == name)


def _find(result, section, subject):
    return next(f for f in getattr(result, section) if f.subject == subject)


def test_component_named_from_settings_not_hardcoded(tmp_path):
    result = _make_repo(tmp_path, name="orders-service")
    assert any(c.name == "orders-service" for c in result.components)


def test_build_facts_are_generalized(tmp_path):
    result = _make_repo(tmp_path)
    app = _app(result)
    assert app.build_tool.startswith("Gradle")
    assert app.build_command == "./gradlew clean bootJar"
    assert app.language == "Java 21"
    assert app.build_artifact == "build/libs/orders-service-9.9.9.jar"
    assert app.packaging == "jar (Spring Boot executable)"
    assert _find(result, "configuration", "build.artifact_type").value == "executable-jar"
    assert _find(result, "configuration", "build.wrapper").value == "./gradlew"


def test_default_port_8080_when_unset(tmp_path):
    result = _make_repo(tmp_path)
    port = _find(result, "networking", "app.default_port")
    assert port.value == 8080
    assert port.confidence == "derived"


def test_explicit_server_port_overrides_default(tmp_path):
    props = _APP_PROPS + "server.port=8888\n"
    result = _make_repo(tmp_path, app_props=props)
    port = _find(result, "networking", "app.server_port")
    assert port.value == 8888
    assert port.confidence == "explicit"
    assert _app(result).container_ports == [8888]


def test_datasource_env_classified_from_placeholders(tmp_path):
    result = _make_repo(tmp_path)
    app = _app(result)
    # URL -> ConfigMap; USER/PASSWORD -> Secret (names come from the placeholders).
    assert "DB_URL" in app.environment
    assert "DB_USER" in app.secret_candidates
    assert "DB_PASSWORD" in app.secret_candidates
    assert "DB_URL" not in app.secret_candidates
    required = _find(result, "configuration", "profile.postgres.required_env").value
    assert required == ["DB_URL", "DB_USER", "DB_PASSWORD"]


def test_bootbuildimage_supported_without_dockerfile(tmp_path):
    result = _make_repo(tmp_path)
    assert _find(result, "container_image", "image.buildpack_support").value is True
    assert _find(result, "container_image", "image.dockerfile").value.startswith("none")


def test_actuator_probes_derived(tmp_path):
    result = _make_repo(tmp_path)
    assert _find(result, "health_checks", "health.liveness_probe").value == "/actuator/health/liveness"
    assert _find(result, "health_checks", "health.readiness_probe").value == "/actuator/health/readiness"
    # /livez,/readyz are NOT asserted unless add-additional-paths is enabled.
    assert _find(result, "health_checks", "health.additional_paths").confidence == "unresolved"


def test_livez_readyz_confirmed_only_when_enabled(tmp_path):
    props = _APP_PROPS + "management.endpoint.health.probes.add-additional-paths=true\n"
    result = _make_repo(tmp_path, app_props=props)
    subjects = {f.subject: f for f in result.health_checks}
    assert "health.livez" in subjects and subjects["health.livez"].value == "/livez"
    assert "health.readyz" in subjects and subjects["health.readyz"].value == "/readyz"
    assert subjects["health.livez"].confidence == "explicit"


def test_no_actuator_means_no_probe_paths(tmp_path):
    gradle_no_actuator = _GRADLE.replace(
        "  runtimeOnly 'org.springframework.boot:spring-boot-starter-actuator'\n", ""
    )
    (tmp_path / "build.gradle").write_text(gradle_no_actuator)
    (tmp_path / "settings.gradle").write_text("rootProject.name = 'orders-service'\n")
    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.properties").write_text(_APP_PROPS)
    result = analyze_repository(str(tmp_path))
    actuator = _find(result, "health_checks", "health.actuator")
    assert actuator.value == "not present"
    assert not any(f.subject == "health.liveness_probe" for f in result.health_checks)


def test_application_pvc_not_required(tmp_path):
    result = _make_repo(tmp_path)
    pvc = _find(result, "storage", "storage.application_pvc")
    assert pvc.value == "not required"


def test_sql_init_distinguished_from_flyway(tmp_path):
    result = _make_repo(
        tmp_path,
        extra={"src/main/resources/db/h2/schema.sql": "CREATE TABLE IF NOT EXISTS t (id INT);\n"},
    )
    tool = _find(result, "startup_order", "startup.migration_tool")
    assert "no Flyway/Liquibase" in tool.value
    idem = _find(result, "startup_order", "startup.sql_init.idempotent")
    assert idem.confidence == "derived"
