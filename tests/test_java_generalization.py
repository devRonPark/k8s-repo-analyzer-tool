"""Category-level regression tests for the generalized analysis behaviours.

These do not depend on the jpetstore fixture; they assert the reusable rules the
Java/WAR work introduced: implicit compose Dockerfile resolution, deriving a
container port from a published mapping, and analysing a Maven web app that has
no compose file at all.
"""

from __future__ import annotations

from repo_analyzer.analyzer import analyze_repository

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
