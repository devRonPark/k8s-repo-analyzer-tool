"""Unit tests for the Gradle build-script parser."""

from __future__ import annotations

from repo_analyzer.parsers.gradle import (
    parse_gradle,
    parse_gradle_wrapper,
    parse_settings,
)

_GROOVY = """\
plugins {
  id 'java'
  id 'org.springframework.boot' version '3.4.1'
  id 'io.spring.dependency-management' version '1.1.7'
}

group = 'com.example'
version = '2.1.0'

java {
  toolchain {
    languageVersion = JavaLanguageVersion.of(21)
  }
}

dependencies {
  implementation 'org.springframework.boot:spring-boot-starter-web'
  runtimeOnly 'org.postgresql:postgresql'
  testImplementation 'org.springframework.boot:spring-boot-starter-test'
}
"""

_KOTLIN = """\
plugins {
    java
    id("org.springframework.boot") version "3.3.0"
}

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-webflux")
}
"""


def test_parses_plugins_with_versions_and_lines():
    build = parse_gradle(_GROOVY, "build.gradle")
    boot = build.plugin_prefixed("org.springframework.boot")
    assert boot is not None
    assert boot.version == "3.4.1"
    # Line is located from the real source, not hardcoded.
    assert boot.location.start_line == 3
    assert build.plugin("java") is not None


def test_parses_java_toolchain_version():
    build = parse_gradle(_GROOVY, "build.gradle")
    assert build.java_version == "21"
    assert build.java_version_selector == "java.toolchain.languageVersion"
    assert build.java_version_line == (12, 12)


def test_parses_group_and_version():
    build = parse_gradle(_GROOVY, "build.gradle")
    assert build.group == "com.example"
    assert build.version == "2.1.0"


def test_parses_dependencies_with_configuration_and_split_coordinate():
    build = parse_gradle(_GROOVY, "build.gradle")
    web = build.find_dependency("org.springframework.boot", "starter-web")
    assert web is not None
    assert web.configuration == "implementation"
    assert web.group == "org.springframework.boot"
    assert web.artifact == "spring-boot-starter-web"
    pg = build.find_dependency("org.postgresql")
    assert pg is not None and pg.configuration == "runtimeOnly"
    test_dep = build.find_dependency("org.springframework.boot", "starter-test")
    assert test_dep is not None and test_dep.configuration == "testImplementation"


def test_no_spurious_issue_from_block_braces():
    build = parse_gradle(_GROOVY, "build.gradle")
    assert build.issues == []


def test_kotlin_dsl_plugins_and_dependencies():
    build = parse_gradle(_KOTLIN, "build.gradle.kts")
    assert build.is_kotlin is True
    boot = build.plugin_prefixed("org.springframework.boot")
    assert boot is not None and boot.version == "3.3.0"
    assert build.find_dependency("org.springframework.boot", "starter-webflux") is not None


def test_catalog_alias_plugin_is_captured_not_dropped():
    # alias(libs...) is no longer "unsupported" — it is captured for resolution.
    text = "plugins {\n  alias(libs.plugins.spring.boot)\n}\n"
    build = parse_gradle(text, "build.gradle")
    assert build.plugin_alias_refs and build.plugin_alias_refs[0][0] == "libs.plugins.spring.boot"
    assert not any(i.construct == "gradle_plugin" for i in build.issues)


def test_unresolved_catalog_alias_is_reported():
    from repo_analyzer.parsers.gradle import apply_version_catalog
    from repo_analyzer.parsers.version_catalog import parse_version_catalog

    build = parse_gradle("plugins {\n  alias(libs.plugins.missing)\n}\n", "build.gradle")
    apply_version_catalog(build, parse_version_catalog("", "gradle/libs.versions.toml"))
    assert any(i.construct == "gradle_catalog_plugin" for i in build.issues)


def test_settings_root_project_name():
    parsed = parse_settings("rootProject.name = 'my-app'\n", "settings.gradle")
    assert parsed is not None
    name, loc = parsed
    assert name == "my-app"
    assert loc.start_line == 1


def test_wrapper_distribution_version():
    text = "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.11.1-bin.zip\n"
    parsed = parse_gradle_wrapper(text, "gradle/wrapper/gradle-wrapper.properties")
    assert parsed is not None
    version, loc = parsed
    assert version == "8.11.1"
    assert loc.start_line == 1


_WITH_PROPS = """\
plugins {
  id 'org.springframework.boot' version '3.4.1'
}
if (project.hasProperty("include-frontend")) {
  apply from: 'frontend.gradle'
}
def prod = findProperty('prod') ?: 'false'
tasks.register('x') {
  onlyIf { providers.gradleProperty("skipTests").isPresent() }
}
"""


def test_build_properties_detected_with_lines():
    build = parse_gradle(_WITH_PROPS, "build.gradle")
    names = [name for name, _ in build.build_properties]
    # hasProperty / findProperty / gradleProperty accessors are all captured.
    assert names == ["include-frontend", "prod", "skipTests"]
    # Located to the real source line, deduped, sorted by name for determinism.
    by_name = dict(build.build_properties)
    assert by_name["include-frontend"].start_line == 4
    assert by_name["prod"].start_line == 7


def test_no_build_properties_when_absent():
    build = parse_gradle(_GROOVY, "build.gradle")
    assert build.build_properties == []
