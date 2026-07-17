"""Unit tests for the Gradle version-catalog (libs.versions.toml) parser."""

from __future__ import annotations

from repo_analyzer.parsers.version_catalog import parse_version_catalog

_CATALOG = """\
[versions]
spring-boot = "3.5.14"

[libraries]
spring-starter-webflux = { module = "org.springframework.boot:spring-boot-starter-webflux", version.ref = "spring-boot" }
spring-starter-actuator = { module = "org.springframework.boot:spring-boot-starter-actuator", version.ref = "spring-boot" }
bouncycastle-bcpkix = { group = "org.bouncycastle", name = "bcpkix-jdk18on", version = "1.80" }
snappy = "org.xerial.snappy:snappy-java:1.1.10.7"

[plugins]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }
node-gradle = { id = "com.github.node-gradle.node", version = "7.0.1" }
"""


def test_library_module_resolution_module_form():
    cat = parse_version_catalog(_CATALOG, "gradle/libs.versions.toml")
    assert cat.library("libs.spring.starter.webflux") == "org.springframework.boot:spring-boot-starter-webflux"
    assert cat.library("libs.spring.starter.actuator") == "org.springframework.boot:spring-boot-starter-actuator"


def test_library_group_name_and_string_forms():
    cat = parse_version_catalog(_CATALOG, "gradle/libs.versions.toml")
    assert cat.library("libs.bouncycastle.bcpkix") == "org.bouncycastle:bcpkix-jdk18on"
    assert cat.library("libs.snappy") == "org.xerial.snappy:snappy-java"


def test_plugin_id_resolution():
    cat = parse_version_catalog(_CATALOG, "gradle/libs.versions.toml")
    assert cat.plugin("libs.plugins.spring.boot") == "org.springframework.boot"
    assert cat.plugin("libs.plugins.node.gradle") == "com.github.node-gradle.node"


def test_version_ref_resolved():
    cat = parse_version_catalog(_CATALOG, "gradle/libs.versions.toml")
    assert cat.versions["spring-boot"] == "3.5.14"
    assert cat.library_version("libs.spring.starter.webflux") == "3.5.14"
    assert cat.library_version("libs.bouncycastle.bcpkix") == "1.80"


def test_unknown_alias_is_none():
    cat = parse_version_catalog(_CATALOG, "gradle/libs.versions.toml")
    assert cat.library("libs.does.not.exist") is None
    assert cat.plugin("libs.plugins.missing") is None


def test_malformed_toml_is_reported_not_raised():
    cat = parse_version_catalog("[libraries\nbad = ", "gradle/libs.versions.toml")
    assert any(i.construct == "toml_parse_error" for i in cat.issues)
    assert cat.libraries == {}
