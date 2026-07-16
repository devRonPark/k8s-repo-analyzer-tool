"""Build-system detection & selection tests.

Synthetic repositories (tmp_path) — nothing here depends on the spring-petclinic
fixture, so these assert the *generalized* selection behaviour, not a hardcoded
name.
"""

from __future__ import annotations

from repo_analyzer.analyzer import analyze_repository

_BOOT_GRADLE = """\
plugins {
  id 'java'
  id 'org.springframework.boot' version '3.4.1'
}
group = 'com.example'
version = '1.0.0'
java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }
dependencies {
  implementation 'org.springframework.boot:spring-boot-starter-web'
}
"""

_BOOT_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>1.0.0</version>
  <packaging>jar</packaging>
  <properties><java.version>21</java.version></properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
"""


def _build_system(result) -> str:
    return next(f.value for f in result.configuration if f.subject == "build.system")


def _selection(result) -> dict:
    return next(f.value for f in result.configuration if f.subject == "build.system.selection")


def test_gradle_only_selects_gradle(tmp_path):
    (tmp_path / "build.gradle").write_text(_BOOT_GRADLE)
    (tmp_path / "settings.gradle").write_text("rootProject.name = 'demo'\n")
    result = analyze_repository(str(tmp_path))
    assert _build_system(result) == "gradle"
    assert _selection(result)["detected"] == ["gradle"]
    assert not any(w.code == "multiple_build_systems" for w in result.warnings)


def test_maven_only_selects_maven(tmp_path):
    (tmp_path / "pom.xml").write_text(_BOOT_POM)
    result = analyze_repository(str(tmp_path))
    assert _build_system(result) == "maven"


def test_both_present_auto_selects_gradle_and_warns(tmp_path):
    (tmp_path / "build.gradle").write_text(_BOOT_GRADLE)
    (tmp_path / "settings.gradle").write_text("rootProject.name = 'demo'\n")
    (tmp_path / "pom.xml").write_text(_BOOT_POM)
    result = analyze_repository(str(tmp_path))
    sel = _selection(result)
    assert sel["detected"] == ["gradle", "maven"]
    assert sel["selected"] == "gradle"
    assert "maven" in sel["how_to_select_other"]
    assert any(w.code == "multiple_build_systems" for w in result.warnings)


def test_explicit_override_to_maven(tmp_path):
    (tmp_path / "build.gradle").write_text(_BOOT_GRADLE)
    (tmp_path / "settings.gradle").write_text("rootProject.name = 'demo'\n")
    (tmp_path / "pom.xml").write_text(_BOOT_POM)
    result = analyze_repository(str(tmp_path), build_system="maven")
    assert _build_system(result) == "maven"
    assert "requested" in _selection(result)["rationale"]


def test_requested_build_system_absent_falls_back(tmp_path):
    (tmp_path / "pom.xml").write_text(_BOOT_POM)
    result = analyze_repository(str(tmp_path), build_system="gradle")
    # No gradle build exists: fall back to what's there and say so.
    assert _build_system(result) == "maven"
    assert any(w.code == "build_system_not_found" for w in result.warnings)


def test_invalid_build_system_rejected(tmp_path):
    (tmp_path / "pom.xml").write_text(_BOOT_POM)
    try:
        analyze_repository(str(tmp_path), build_system="bazel")
    except ValueError as exc:
        assert "build_system" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unsupported build_system")
