from __future__ import annotations

from repo_analyzer.parsers.maven import parse_maven

_POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>shop</artifactId>
  <version>1.2.3</version>
  <packaging>war</packaging>
  <properties>
    <java.version>17</java.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-web</artifactId>
      <version>${spring.version}</version>
    </dependency>
    <dependency>
      <groupId>jakarta.servlet</groupId>
      <artifactId>jakarta.servlet-api</artifactId>
      <version>4.0.4</version>
      <scope>provided</scope>
    </dependency>
  </dependencies>
  <build>
    <finalName>shop</finalName>
  </build>
  <profiles>
    <profile>
      <id>tomcat9</id>
      <activation><activeByDefault>true</activeByDefault></activation>
      <properties>
        <tomcat.version>9.0.120</tomcat.version>
        <cargo.maven.containerId>tomcat9x</cargo.maven.containerId>
      </properties>
    </profile>
  </profiles>
</project>
"""


def test_core_coordinates_and_packaging():
    pom = parse_maven(_POM, "pom.xml")
    assert pom.group_id == "com.example"
    assert pom.artifact_id == "shop"
    assert pom.version == "1.2.3"
    assert pom.packaging == "war"
    assert pom.final_name == "shop"
    assert pom.artifact_file_name == "shop.war"
    assert pom.issues == []


def test_java_version_with_source_line():
    pom = parse_maven(_POM, "pom.xml")
    assert pom.java_version == "17"
    assert pom.java_version_line is not None
    start, _ = pom.java_version_line
    assert _POM.splitlines()[start - 1].strip() == "<java.version>17</java.version>"


def test_dependency_scope_preserved():
    pom = parse_maven(_POM, "pom.xml")
    servlet = next(d for d in pom.dependencies if d.artifact_id == "jakarta.servlet-api")
    assert servlet.scope == "provided"
    spring = next(d for d in pom.dependencies if d.artifact_id == "spring-web")
    assert spring.scope == "compile"
    # Unresolved ${spring.version} is left verbatim, never guessed.
    assert spring.version == "${spring.version}"


def test_default_profile_and_container_id():
    pom = parse_maven(_POM, "pom.xml")
    default = pom.default_profile()
    assert default is not None and default.id == "tomcat9"
    assert default.container_id == "tomcat9x"
    assert default.location.start_line < default.location.end_line


def test_artifact_file_name_falls_back_to_artifact_and_version():
    pom = parse_maven(
        _POM.replace("<finalName>shop</finalName>", ""), "pom.xml"
    )
    assert pom.artifact_file_name == "shop-1.2.3.war"


def test_malformed_pom_is_reported_not_raised():
    pom = parse_maven("<project><unclosed>", "pom.xml")
    assert any(i.construct == "xml_parse_error" for i in pom.issues)
