"""Java / Maven web-application rules for the kubernetes-p0 profile.

Pure logic: parsed Maven/servlet/Spring facts in, mutations to the shared
``AnalysisResult`` out. This is where explicit build facts (WAR packaging, an
external servlet container via cargo profiles, an embedded in-memory database,
a non-root context path) become *derived* Kubernetes conclusions, and where the
things a repository cannot decide (probes, securityContext, scaling with an
in-process DB) are recorded as ``unresolved``.

The module never invents operational values and attaches real source lines to
every finding. It works whether or not a compose file is present: with compose
it enriches the matching service component; without one it synthesises a
component from the Maven project and its Dockerfile.
"""

from __future__ import annotations

import re
import shlex

from ..inventory import Inventory
from ..models import (
    AnalysisResult,
    Component,
    Evidence,
    Finding,
    Unresolved,
    Warning,
    WorkloadMapping,
)
from ..parsers.common import Located
from ..parsers.compose import ComposeFile
from ..parsers.dockerfile import Dockerfile, exec_form
from ..parsers.maven import MavenProfile, MavenProject
from ..parsers.spring_properties import SpringProperties, SpringProperty
from ..parsers.spring_xml import SpringContext
from ..parsers.webxml import WebApp

# Dependency (groupId prefix, artifactId substring) -> framework label. First
# match wins; ordered most specific first.
_FRAMEWORK_RULES: tuple[tuple[str, str, str], ...] = (
    ("org.springframework.boot", "", "Spring Boot"),
    ("org.springframework", "spring-webmvc", "Spring MVC"),
    ("org.springframework", "spring-web", "Spring Framework"),
    ("org.springframework", "spring-context", "Spring Framework"),
    ("org.mybatis", "mybatis-spring", "MyBatis-Spring"),
    ("org.mybatis", "mybatis", "MyBatis"),
    ("net.sourceforge.stripes", "stripes", "Stripes"),
    ("org.apache.struts", "", "Apache Struts"),
    ("com.vaadin", "", "Vaadin"),
    ("io.quarkus", "", "Quarkus"),
    ("io.micronaut", "", "Micronaut"),
    ("org.glassfish.jersey", "", "Jersey (JAX-RS)"),
)

# JDBC driver / client dependency -> external service it implies.
_EXTERNAL_SERVICE_RULES: tuple[tuple[str, str, str], ...] = (
    ("mysql", "", "External MySQL database (JDBC driver present)"),
    ("com.mysql", "", "External MySQL database (JDBC driver present)"),
    ("org.mariadb.jdbc", "", "External MariaDB database (JDBC driver present)"),
    ("org.postgresql", "postgresql", "External PostgreSQL database (JDBC driver present)"),
    ("com.microsoft.sqlserver", "", "External SQL Server database (JDBC driver present)"),
    ("com.oracle", "", "External Oracle database (JDBC driver present)"),
    ("org.apache.kafka", "", "Apache Kafka (message broker)"),
    ("org.springframework.kafka", "", "Apache Kafka (message broker)"),
    ("io.lettuce", "", "Redis (cache / data store)"),
    ("redis.clients", "", "Redis (cache / data store)"),
    ("org.springframework.amqp", "", "RabbitMQ (message broker)"),
    ("com.rabbitmq", "", "RabbitMQ (message broker)"),
)

_CONTAINER_FRIENDLY: tuple[tuple[str, str], ...] = (
    ("tomee", "Apache TomEE"),
    ("tomcat", "Apache Tomcat"),
    ("wildfly", "WildFly"),
    ("jetty", "Eclipse Jetty"),
    ("liberty", "WebSphere Liberty"),
    ("glassfish", "GlassFish"),
    ("payara", "Payara"),
    ("resin", "Resin"),
)

_EMBEDDED_SERVER_GROUPS = ("org.springframework.boot",)


# --------------------------------------------------------------------------- #
# Evidence helpers
# --------------------------------------------------------------------------- #
def _ev(loc: Located, path: str, symbol: str | None = None) -> Evidence:
    return Evidence(
        path=path,
        selector=loc.selector,
        symbol=symbol,
        start_line=loc.start_line,
        end_line=loc.end_line,
    )


def _ev_range(
    path: str, selector: str, span: tuple[int, int], symbol: str | None = None
) -> Evidence:
    return Evidence(
        path=path, selector=selector, symbol=symbol, start_line=span[0], end_line=span[1]
    )


def _prop_ev(prop: SpringProperty, path: str) -> Evidence:
    return Evidence(path=path, selector=prop.key, symbol="property", start_line=prop.line, end_line=prop.line)


def _dirname(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _norm_context(context: str | None) -> str:
    if context is None:
        return ""
    value = context.strip().lstrip("./").rstrip("/")
    return "" if value == "." else value


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def analyze_java_webapp(
    *,
    result: AnalysisResult,
    inventory: Inventory,
    compose: ComposeFile | None,
    compose_path: str | None,
    dockerfiles: dict[str, Dockerfile],
    mavens: dict[str, MavenProject],
    webapps: dict[str, WebApp],
    springs: dict[str, SpringContext],
    spring_props: dict[str, SpringProperties],
    readmes: dict[str, list[str]],
) -> None:
    pom_rel = _primary_pom(mavens)
    maven = mavens[pom_rel]
    if maven.artifact_id is None and maven.packaging == "jar" and not maven.profiles:
        # Almost certainly a parent/aggregator or non-app POM; nothing to map.
        return
    pom_dir = _dirname(pom_rel)

    dockerfile_rel, dockerfile = _select_dockerfile(pom_dir, dockerfiles)
    component = _match_or_create_component(result, pom_dir, maven, dockerfile_rel)

    # Source provenance.
    for src in (pom_rel, dockerfile_rel):
        if src and src not in component.source_files:
            component.source_files.append(src)
    webapp = _primary(webapps)
    if webapp is not None and webapp.path not in component.source_files:
        component.source_files.append(webapp.path)
    for spath in springs:
        if spath not in component.source_files:
            component.source_files.append(spath)
    for cpath in spring_props:
        if cpath not in component.source_files:
            component.source_files.append(cpath)
    for rpath in readmes:
        if rpath not in component.source_files:
            component.source_files.append(rpath)
    component.source_files.sort()

    build_tool = _build_tool(inventory)
    embedded_server = any(
        maven.has_dependency(group) for group in _EMBEDDED_SERVER_GROUPS
    ) or any(p.artifact_id.startswith("spring-boot-maven-plugin") for p in maven.build_plugins)
    needs_external = maven.packaging == "war" or (
        _has_provided_servlet_api(maven) and not embedded_server
    )

    # --- Component summary fields ------------------------------------------- #
    component.language = f"Java {maven.java_version}" if maven.java_version else "Java"
    component.build_tool = build_tool
    component.packaging = maven.packaging
    if maven.artifact_file_name:
        component.build_artifact = f"target/{maven.artifact_file_name}"

    frameworks = _frameworks(maven)
    component.frameworks = [label if not ver else f"{label} {ver}" for label, ver, _ in frameworks]

    _emit_language_and_frameworks(result, pom_rel, maven, frameworks)
    _emit_build_facts(result, component, pom_rel, maven, dockerfile_rel, dockerfile, readmes, build_tool)

    app_server = None
    if needs_external:
        app_server = _emit_application_server(
            result, component, pom_rel, maven, dockerfile_rel, dockerfile, readmes
        )
    component.application_server = app_server
    component.runtime = _runtime_summary(maven, needs_external, app_server, embedded_server)

    _emit_start_command(result, component, dockerfile_rel, dockerfile, maven, readmes)
    _emit_context_and_routes(result, component, pom_rel, maven, webapp, readmes)
    _emit_datastores(result, component, springs, maven)
    _emit_spring_config_facts(result, component, maven, spring_props)
    _emit_image_findings(result, component, dockerfile_rel, dockerfile, maven)
    _emit_workload(result, component, pom_rel, maven, needs_external, app_server, compose_path, dockerfile_rel)
    _emit_java_unresolved(result, springs)


# --------------------------------------------------------------------------- #
# Selection helpers
# --------------------------------------------------------------------------- #
def _primary_pom(mavens: dict[str, MavenProject]) -> str:
    # Shallowest path wins (root module), then lexicographic for stability.
    return sorted(mavens, key=lambda p: (p.count("/"), p))[0]


def _primary(mapping: dict):
    if not mapping:
        return None
    return mapping[sorted(mapping, key=lambda p: (p.count("/"), p))[0]]


def _select_dockerfile(
    pom_dir: str, dockerfiles: dict[str, Dockerfile]
) -> tuple[str | None, Dockerfile | None]:
    preferred = f"{pom_dir}/Dockerfile" if pom_dir else "Dockerfile"
    if preferred in dockerfiles:
        return preferred, dockerfiles[preferred]
    if dockerfiles:
        rel = sorted(dockerfiles, key=lambda p: (p.count("/"), p))[0]
        return rel, dockerfiles[rel]
    return None, None


def _match_or_create_component(
    result: AnalysisResult, pom_dir: str, maven: MavenProject, dockerfile_rel: str | None
) -> Component:
    for comp in result.components:
        # Only match a component that actually builds (has a build context); an
        # image-only compose service such as a database must not absorb the app's
        # build facts just because both resolve to the repo root ("").
        if comp.build_context is not None and _norm_context(comp.build_context) == pom_dir:
            return comp
        if dockerfile_rel is not None and comp.dockerfile == dockerfile_rel:
            return comp
    component = Component(name=maven.artifact_id or "app", workload_candidate="")
    if dockerfile_rel is not None:
        component.dockerfile = dockerfile_rel
        component.build_context = pom_dir or "."
    result.components.append(component)
    return component


# --------------------------------------------------------------------------- #
# Fact helpers
# --------------------------------------------------------------------------- #
def _build_tool(inventory: Inventory) -> str:
    if any(w.rsplit("/", 1)[-1] == "mvnw" for w in inventory.build_wrappers):
        return "Maven (mvnw wrapper)"
    if any(w.rsplit("/", 1)[-1] == "gradlew" for w in inventory.build_wrappers):
        return "Gradle (gradlew wrapper)"
    return "Maven"


def _has_provided_servlet_api(maven: MavenProject) -> bool:
    for dep in maven.dependencies:
        if "servlet-api" in dep.artifact_id and dep.scope == "provided":
            return True
    return False


def _frameworks(maven: MavenProject) -> list[tuple[str, str | None, Located]]:
    seen: set[str] = set()
    collected: list[tuple[str, str | None, Located]] = []
    for dep in maven.dependencies:
        if dep.scope == "test":
            continue
        for group_prefix, artifact_sub, label in _FRAMEWORK_RULES:
            if dep.group_id.startswith(group_prefix) and artifact_sub in dep.artifact_id:
                if label in seen:
                    break
                seen.add(label)
                collected.append((label, dep.version, dep.location))
                break
    return collected


def _friendly_container(container_id: str | None) -> str | None:
    if not container_id:
        return None
    lower = container_id.lower()
    for token, friendly in _CONTAINER_FRIENDLY:
        if token in lower:
            return friendly
    return container_id


def _profile_version(profile: MavenProfile) -> str | None:
    for key, value in profile.properties.items():
        if key.endswith(".version") and not key.startswith("cargo"):
            return value
    return None


def _server_label(profile: MavenProfile) -> str:
    friendly = _friendly_container(profile.container_id) or profile.id
    version = _profile_version(profile)
    return f"{friendly} {version}" if version else friendly


def _runtime_summary(
    maven: MavenProject, needs_external: bool, app_server: str | None, embedded: bool
) -> str:
    java = f"Java {maven.java_version}" if maven.java_version else "Java"
    stack = "web application"
    if embedded:
        return f"{java} {stack} with an embedded server (self-contained)"
    if needs_external:
        return f"{java} {stack} ({maven.packaging.upper()}) — requires an external servlet container"
    return f"{java} {stack} ({maven.packaging})"


# --------------------------------------------------------------------------- #
# Emitters
# --------------------------------------------------------------------------- #
def _emit_language_and_frameworks(
    result: AnalysisResult,
    pom_rel: str,
    maven: MavenProject,
    frameworks: list[tuple[str, str | None, Located]],
) -> None:
    if maven.java_version is not None:
        span = maven.java_version_line or maven.packaging_line or (1, 1)
        result.configuration.append(
            Finding(
                subject="runtime.language",
                value=f"Java {maven.java_version}",
                confidence="explicit",
                kubernetes_effect="informs the container base image (JRE/JDK major version)",
                evidence=[_ev_range(pom_rel, "properties.java.version", span, "java.version")],
            )
        )
    for label, version, loc in frameworks:
        result.configuration.append(
            Finding(
                subject=f"framework.{label.lower().replace(' ', '_')}",
                value=version or label,
                confidence="explicit",
                kubernetes_effect="application framework (no direct K8s object; informs runtime behaviour)",
                evidence=[_ev(loc, pom_rel, "dependency")],
            )
        )


def _emit_build_facts(
    result: AnalysisResult,
    component: Component,
    pom_rel: str,
    maven: MavenProject,
    dockerfile_rel: str | None,
    dockerfile: Dockerfile | None,
    readmes: dict[str, list[str]],
    build_tool: str,
) -> None:
    # Build command: prefer the Dockerfile RUN, corroborate with the README.
    build_cmd, evidence = _find_build_command(dockerfile_rel, dockerfile, readmes)
    if build_cmd is None:
        build_cmd = "./mvnw clean package" if "mvnw" in build_tool else "mvn clean package"
    component.build_command = build_cmd

    if maven.packaging_line is not None:
        result.configuration.append(
            Finding(
                subject="build.tool",
                value=build_tool,
                confidence="explicit",
                kubernetes_effect="build system that produces the deployable artifact (build image / CI)",
                evidence=[_ev_range(pom_rel, "packaging", maven.packaging_line, "packaging")],
            )
        )
    if evidence:
        result.container_image.append(
            Finding(
                subject="image.build_command",
                value=build_cmd,
                confidence="derived",
                kubernetes_effect="produces the artifact during image build; needs network for dependency resolution",
                evidence=evidence,
            )
        )
    if component.build_artifact is not None:
        art_ev: list[Evidence] = []
        if maven.final_name_line is not None:
            art_ev.append(_ev_range(pom_rel, "build.finalName", maven.final_name_line, "finalName"))
        if maven.packaging_line is not None:
            art_ev.append(_ev_range(pom_rel, "packaging", maven.packaging_line, "packaging"))
        result.configuration.append(
            Finding(
                subject="build.artifact",
                value=component.build_artifact,
                confidence="derived",
                kubernetes_effect="the WAR/JAR that must be present in (or built into) the container image",
                evidence=art_ev,
            )
        )


def _emit_application_server(
    result: AnalysisResult,
    component: Component,
    pom_rel: str,
    maven: MavenProject,
    dockerfile_rel: str | None,
    dockerfile: Dockerfile | None,
    readmes: dict[str, list[str]],
) -> str | None:
    profiles = [p for p in maven.profiles if p.container_id]
    default_profile = maven.default_profile()
    if default_profile is None and profiles:
        default_profile = profiles[0]

    # Surface every selectable server profile as a config finding.
    for profile in profiles:
        result.configuration.append(
            Finding(
                subject=f"profile.{profile.id}",
                value=_server_label(profile),
                confidence="explicit",
                kubernetes_effect="Maven profile selecting the servlet container at run time (changes runtime image)",
                evidence=[_ev(profile.location, pom_rel, "profile")],
            )
        )

    default_label = _server_label(default_profile) if default_profile else None
    others = [
        _friendly_container(p.container_id) or p.id
        for p in profiles
        if default_profile is None or p.id != default_profile.id
    ]
    if default_label is None:
        summary = "External servlet container required (WAR packaging); server not pinned in the repo"
    else:
        alt = f"; alternatives via Maven profiles: {', '.join(others)}" if others else ""
        summary = f"External servlet container — {default_label} by default (Maven profile '{default_profile.id}'){alt}"

    evidence: list[Evidence] = []
    if default_profile is not None:
        evidence.append(_ev(default_profile.location, pom_rel, "profile.default"))
    cmd_ev = _dockerfile_cmd_evidence(dockerfile_rel, dockerfile)
    if cmd_ev is not None:
        evidence.append(cmd_ev)
    readme_ev = _readme_evidence(readmes, lambda t: "cargo:run" in t)
    if readme_ev is not None:
        evidence.append(readme_ev)

    result.configuration.append(
        Finding(
            subject="runtime.application_server",
            value=summary,
            confidence="derived",
            kubernetes_effect=(
                "the app is NOT self-contained: it needs a servlet container. For K8s, bake the WAR "
                "into a fixed server image (e.g. tomcat:9-jre17) rather than downloading a server at runtime."
            ),
            evidence=evidence,
        )
    )
    return summary


def _emit_start_command(
    result: AnalysisResult,
    component: Component,
    dockerfile_rel: str | None,
    dockerfile: Dockerfile | None,
    maven: MavenProject,
    readmes: dict[str, list[str]],
) -> None:
    if dockerfile is None:
        return
    cmd = dockerfile.last("CMD")
    if cmd is None:
        return
    argv = exec_form(cmd.argument)
    shell_form = argv is None
    if argv is None:
        try:
            argv = shlex.split(cmd.argument)
        except ValueError:
            argv = cmd.argument.split()
    component.command = argv
    result.container_image.append(
        Finding(
            subject="image.start_command",
            value=cmd.argument,
            confidence="explicit",
            kubernetes_effect="container entrypoint/command (Deployment container.command/args)",
            evidence=[
                Evidence(
                    path=dockerfile_rel or dockerfile.path,
                    selector="CMD",
                    symbol="CMD" + (" (shell form)" if shell_form else " (exec form)"),
                    start_line=cmd.start_line,
                    end_line=cmd.end_line,
                )
            ],
        )
    )

    # Cross-check the referenced Maven profile against the POM's defined profiles.
    defined = {p.id for p in maven.profiles}
    referenced = _referenced_profiles(cmd.argument)
    for readme_lines in readmes.values():
        for line in readme_lines:
            referenced |= _referenced_profiles(line)
    undefined = sorted(p for p in referenced if p not in defined)
    for name in undefined:
        result.warnings.append(
            Warning(
                code="run_profile_undefined",
                message=(
                    f"run command activates Maven profile '{name}', which is not defined in the POM "
                    f"(defined: {', '.join(sorted(defined)) or 'none'}). It resolves only because the "
                    "default profile stays active; verify the intended server."
                ),
                path=dockerfile_rel or dockerfile.path,
            )
        )


def _emit_context_and_routes(
    result: AnalysisResult,
    component: Component,
    pom_rel: str,
    maven: MavenProject,
    webapp: WebApp | None,
    readmes: dict[str, list[str]],
) -> None:
    final_name = maven.final_name
    if final_name and maven.packaging == "war":
        context = "/" + final_name if final_name.lower() != "root" else "/"
        evidence: list[Evidence] = []
        if maven.final_name_line is not None:
            evidence.append(_ev_range(pom_rel, "build.finalName", maven.final_name_line, "finalName"))
        # Match the served context path as a real URL path segment: `/<name>`
        # followed by a segment boundary. Avoids false matches like a
        # `.../jpetstore-6/...` project link in a README badge.
        ctx_pattern = re.compile(r"/" + re.escape(final_name) + r"(?:/|\s|$|['\")>])")
        readme_ev = _readme_evidence(readmes, lambda t: bool(ctx_pattern.search(t)))
        if readme_ev is not None:
            evidence.append(readme_ev)
        component.context_path = context
        result.networking.append(
            Finding(
                subject="app.context_path",
                value=context,
                confidence="derived",
                kubernetes_effect=(
                    f"the app is served under '{context}', not '/'. Ingress must route this path "
                    "(or rename the WAR to ROOT); Service targetPort is unaffected."
                ),
                evidence=evidence,
            )
        )

    if webapp is not None:
        for mapping in webapp.servlet_mappings:
            ctx = component.context_path or ""
            result.networking.append(
                Finding(
                    subject=f"servlet.{mapping.servlet_name}",
                    value=mapping.url_pattern,
                    confidence="explicit",
                    kubernetes_effect=(
                        f"HTTP route handled by the app (full path e.g. '{ctx}/...{mapping.url_pattern}')"
                    ),
                    evidence=[_ev(mapping.location, webapp.path, "servlet-mapping")],
                )
            )


def _emit_datastores(
    result: AnalysisResult,
    component: Component,
    springs: dict[str, SpringContext],
    maven: MavenProject,
) -> None:
    for path, ctx in springs.items():
        for embedded in ctx.embedded_databases:
            component.runtime_dependencies.append(
                f"Embedded {embedded.db_type} in-memory database (no external DB by default)"
            )
            evidence = [_ev(embedded.location, path, "jdbc:embedded-database")]
            result.runtime_dependencies.append(
                Finding(
                    subject="database.embedded",
                    value=f"embedded {embedded.db_type} (in-memory, in-process)",
                    confidence="derived",
                    kubernetes_effect=(
                        "no external database is required by default. Data lives in the pod and is "
                        "ephemeral; each replica has its own isolated copy. Externalise the DB (with "
                        "JDBC config as ConfigMap/Secret) before scaling past 1 replica or needing durability."
                    ),
                    evidence=evidence,
                )
            )
            for script in embedded.scripts:
                result.startup_order.append(
                    Finding(
                        subject="startup.db_init",
                        value=script.value,
                        confidence="explicit",
                        kubernetes_effect=(
                            "schema/seed SQL executed in-process at application startup; re-runs on "
                            "every pod start (no separate migration Job for the embedded DB)."
                        ),
                        evidence=[_ev(script, path, "jdbc:script")],
                    )
                )
        for external in ctx.external_datasources:
            component.runtime_dependencies.append(
                f"External datasource ({external.bean_class.rsplit('.', 1)[-1]})"
            )
            result.runtime_dependencies.append(
                Finding(
                    subject="database.external",
                    value=external.jdbc_url or external.bean_class.rsplit(".", 1)[-1],
                    confidence="explicit",
                    kubernetes_effect=(
                        "external database dependency; provide the JDBC URL/credentials via "
                        "ConfigMap/Secret and ensure network reachability from the cluster."
                    ),
                    evidence=[_ev(external.location, path, "bean.dataSource")],
                )
            )

    # JDBC driver / broker dependencies imply external services too.
    for dep in maven.dependencies:
        if dep.scope == "test":
            continue
        for group_prefix, artifact_sub, label in _EXTERNAL_SERVICE_RULES:
            if dep.group_id.startswith(group_prefix) and artifact_sub in dep.artifact_id:
                summary = label
                if summary not in component.runtime_dependencies:
                    component.runtime_dependencies.append(summary)
                    result.runtime_dependencies.append(
                        Finding(
                            subject="dependency.external_service",
                            value=label,
                            confidence="derived",
                            kubernetes_effect="implies an external service the workload must reach (Service/NetworkPolicy, config)",
                            evidence=[_ev(dep.location, maven.path, "dependency")],
                        )
                    )
                break


# --------------------------------------------------------------------------- #
# Spring application*.yml / .properties config facts (Maven path)
# --------------------------------------------------------------------------- #
_SPRING_DEFAULT_PORT = 8080

# JDBC vendor token -> (label, is_external_by_default).
_JDBC_VENDORS: tuple[tuple[str, str, bool], ...] = (
    ("postgresql", "PostgreSQL", True),
    ("mysql", "MySQL", True),
    ("mariadb", "MariaDB", True),
    ("oracle", "Oracle", True),
    ("sqlserver", "SQL Server", True),
    ("h2", "H2", False),
    ("hsqldb", "HSQLDB", False),
    ("derby", "Derby", False),
)

# Flattened key substrings that mark a value as a credential (Secret candidate).
# Kept precise: broad words like "credential(s)" would wrongly flag booleans such
# as CORS ``allow-credentials``.
_SECRET_KEY_HINTS: tuple[str, ...] = (
    "password",
    "secret",
    "private-key",
    "access-key",
)


def _is_test_config(path: str) -> bool:
    """Exclude test-scoped Spring config from deployment analysis."""

    parts = path.split("/")
    return "test" in parts or "src/test" in path


def _spring_env_name(key: str) -> str:
    """Spring Boot relaxed-binding env var for a property key (a standard mapping)."""

    return key.upper().replace(".", "_").replace("-", "_")


def _db_from_url(url: str) -> tuple[str, bool]:
    low = url.lower()
    for token, label, external in _JDBC_VENDORS:
        if f"jdbc:{token}" in low or f":{token}:" in low:
            if token == "h2":
                # h2:tcp is a remote server; mem/file are in-process.
                return label, "h2:tcp" in low
            return label, external
    return "SQL database", True


def _add_spring_config(
    result: AnalysisResult, component: Component, env: str, entry: SpringProperty, path: str, tag: str
) -> None:
    if env not in component.environment:
        component.environment.append(env)
    result.configuration.append(
        Finding(
            subject=f"config.{env}",
            value=f"{entry.key} ({tag} profile)",
            confidence="derived",
            kubernetes_effect=f"ConfigMap key candidate (non-secret connection detail); Spring env var {env}",
            evidence=[_prop_ev(entry, path)],
        )
    )


def _add_spring_secret(
    result: AnalysisResult, component: Component, env: str, entry: SpringProperty, path: str, tag: str
) -> None:
    if env in component.secret_candidates:
        return
    component.secret_candidates.append(env)
    if env not in component.environment:
        component.environment.append(env)
    result.secrets.append(
        Finding(
            subject=f"secret.{env}",
            value="<redacted>",
            confidence="derived",
            kubernetes_effect=f"Kubernetes Secret key candidate ({entry.key}, {tag} profile); Spring env var {env}",
            evidence=[_prop_ev(entry, path)],
        )
    )


def _emit_spring_port(
    result: AnalysisResult,
    component: Component,
    maven: MavenProject,
    ordered: list[SpringProperties],
    is_spring_boot: bool,
) -> None:
    for props in ordered:
        entry = props.get("server.port")
        if entry is not None and entry.value and entry.value.isdigit():
            port = int(entry.value)
            component.container_ports = [port]
            result.networking.append(
                Finding(
                    subject="app.server_port",
                    value=port,
                    confidence="explicit",
                    kubernetes_effect="containerPort and Service targetPort",
                    evidence=[_prop_ev(entry, props.path)],
                )
            )
            return
    if not is_spring_boot or component.container_ports:
        return
    evidence: list[Evidence] = []
    for dep in maven.dependencies:
        if dep.scope == "test":
            continue
        if dep.group_id.startswith("org.springframework.boot"):
            evidence = [_ev(dep.location, maven.path, "dependency")]
            break
    component.container_ports = [_SPRING_DEFAULT_PORT]
    result.networking.append(
        Finding(
            subject="app.default_port",
            value=_SPRING_DEFAULT_PORT,
            confidence="derived",
            kubernetes_effect=(
                "no server.port is set, so Spring Boot's embedded server listens on 8080. "
                "Service targetPort=8080, containerPort=8080."
            ),
            evidence=evidence,
        )
    )


def _emit_spring_datasource(result: AnalysisResult, component: Component, props: SpringProperties) -> None:
    url = props.get("spring.datasource.url")
    user = props.get("spring.datasource.username")
    pwd = props.get("spring.datasource.password")
    tag = props.profile or "default"
    if url is not None and url.value:
        label, external = _db_from_url(url.value)
        if external:
            dep = f"External {label} ({tag} profile)"
            summary = f"External {label}"
            effect = (
                f"'{tag}' profile connects to an external {label}. Provide the JDBC URL via ConfigMap and "
                "credentials via Secret; ensure network reachability from the cluster."
            )
            confidence = "explicit"
        else:
            dep = f"Embedded {label} ({tag} profile, in-process)"
            summary = f"Embedded {label} (in-process)"
            effect = (
                f"'{tag}' profile uses an in-process {label}. Data is ephemeral and per-replica (dev/demo only); "
                "externalise the DB before scaling past 1 replica or needing durability."
            )
            confidence = "derived"
        if dep not in component.runtime_dependencies:
            component.runtime_dependencies.append(dep)
        result.runtime_dependencies.append(
            Finding(
                subject=f"database.{tag}",
                value=summary,
                confidence=confidence,
                kubernetes_effect=effect,
                evidence=[_prop_ev(url, props.path)],
            )
        )
        env = url.placeholders[0].name if url.placeholders else _spring_env_name(url.key)
        _add_spring_config(result, component, env, url, props.path, tag)
    for entry in (user, pwd):
        if entry is None:
            continue
        env = entry.placeholders[0].name if entry.placeholders else _spring_env_name(entry.key)
        _add_spring_secret(result, component, env, entry, props.path, tag)


def _emit_spring_secrets(
    result: AnalysisResult, component: Component, ordered: list[SpringProperties]
) -> None:
    for props in ordered:
        tag = props.profile or "default"
        for entry in props.entries:
            key = entry.key.lower()
            if any(hint in key for hint in _SECRET_KEY_HINTS):
                env = entry.placeholders[0].name if entry.placeholders else _spring_env_name(entry.key)
                _add_spring_secret(result, component, env, entry, props.path, tag)


def _emit_spring_config_facts(
    result: AnalysisResult,
    component: Component,
    maven: MavenProject,
    spring_props: dict[str, SpringProperties],
) -> None:
    """Derive port, datasource dependency, and ConfigMap/Secret candidates from
    Spring ``application*.yml``/``.properties`` on the Maven path. Test-scoped
    config is excluded; the analysis never invents values (env-var names use the
    standard Spring relaxed-binding mapping, cited to the source property)."""

    usable = {rel: p for rel, p in spring_props.items() if not _is_test_config(rel)}
    if not usable:
        return
    default_props = next((p for p in usable.values() if p.profile is None), None)
    profile_props = sorted(
        (p for p in usable.values() if p.profile is not None), key=lambda p: p.profile or ""
    )
    ordered = ([default_props] if default_props is not None else []) + profile_props

    is_spring_boot = maven.has_dependency("org.springframework.boot")
    _emit_spring_port(result, component, maven, ordered, is_spring_boot)
    for props in ordered:
        _emit_spring_datasource(result, component, props)
    _emit_spring_secrets(result, component, ordered)


def _emit_image_findings(
    result: AnalysisResult,
    component: Component,
    dockerfile_rel: str | None,
    dockerfile: Dockerfile | None,
    maven: MavenProject,
) -> None:
    if dockerfile is None:
        result.container_image.append(
            Finding(
                subject="image.buildable",
                value="no Dockerfile found",
                confidence="explicit",
                kubernetes_effect="no container image recipe in the repo; one must be authored before deploying",
                evidence=[],
            )
        )
        return
    path = dockerfile_rel or dockerfile.path
    base = dockerfile.final_base_image

    if base is not None:
        result.container_image.append(
            Finding(
                subject="image.base",
                value=base.image,
                confidence="explicit",
                kubernetes_effect="container base image",
                evidence=[
                    Evidence(path=path, selector="FROM", symbol="FROM",
                             start_line=base.start_line, end_line=base.end_line)
                ],
            )
        )
        _check_jdk_mismatch(result, path, base.image, maven, base.start_line, base.end_line)

    cmd = dockerfile.last("CMD")
    if cmd is not None:
        argument = cmd.argument
        shell_form = exec_form(argument) is None
        if "cargo:run" in argument or "cargo run" in argument:
            result.container_image.append(
                Finding(
                    subject="image.runtime_server_download",
                    value="server downloaded at container start (cargo:run)",
                    confidence="derived",
                    kubernetes_effect=(
                        "the servlet container is fetched from the internet on every start; pods need "
                        "egress and startup is slow/non-reproducible. Build a fixed WAR-on-Tomcat image instead."
                    ),
                    evidence=[Evidence(path=path, selector="CMD", symbol="CMD",
                                       start_line=cmd.start_line, end_line=cmd.end_line)],
                )
            )
        if shell_form and ("mvn" in argument or "mvnw" in argument):
            result.container_image.append(
                Finding(
                    subject="image.signal_handling",
                    value="Maven runs as PID 1 (shell form CMD)",
                    confidence="derived",
                    kubernetes_effect=(
                        "SIGTERM goes to the mvn/mvnw wrapper, not the JVM, so graceful shutdown and fast "
                        "pod termination are not guaranteed. Use exec form / tini, or run the server directly."
                    ),
                    evidence=[Evidence(path=path, selector="CMD", symbol="CMD",
                                       start_line=cmd.start_line, end_line=cmd.end_line)],
                )
            )

    if not dockerfile.find("USER"):
        anchor = base.start_line if base is not None else 1
        anchor_end = base.end_line if base is not None else 1
        result.container_image.append(
            Finding(
                subject="image.runs_as_root",
                value="no USER instruction",
                confidence="derived",
                kubernetes_effect=(
                    "the container runs as root by default; set securityContext.runAsNonRoot / runAsUser "
                    "and a non-root USER in the image."
                ),
                evidence=[Evidence(path=path, selector="USER", symbol="(absent)",
                                   start_line=anchor, end_line=anchor_end)],
            )
        )


def _emit_workload(
    result: AnalysisResult,
    component: Component,
    pom_rel: str,
    maven: MavenProject,
    needs_external: bool,
    app_server: str | None,
    compose_path: str | None,
    dockerfile_rel: str | None,
) -> None:
    ctx = component.context_path
    kind = "Deployment + ClusterIP Service"
    if ctx and ctx != "/":
        kind += f" + Ingress (context path {ctx})"

    ephemeral = any("in-memory" in dep for dep in component.runtime_dependencies)
    rationale = (
        "Stateless "
        + ("Java web application (WAR) on an external servlet container" if needs_external else "Java web application")
        + "; horizontally scalable behind a Service."
    )
    if ephemeral:
        rationale += (
            " Uses an in-process in-memory database, so replicas do NOT share state — externalise the "
            "database before running more than one replica."
        )

    unresolved = ["replica count", "CPU/memory", "readiness/liveness probe", "securityContext (runAsNonRoot)"]
    if ctx and ctx != "/":
        unresolved.append("ingress class & host")
    if ephemeral:
        unresolved.append("externalize database for >1 replica")

    span = maven.packaging_line or (1, 1)
    evidence = [_ev_range(pom_rel, "packaging", span, "packaging")]
    if dockerfile_rel is not None:
        evidence.append(
            Evidence(path=dockerfile_rel, selector="Dockerfile", symbol="build", start_line=1, end_line=1)
        )

    component.workload_candidate = kind
    for mapping in result.workload_mappings:
        if mapping.component == component.name:
            mapping.kubernetes_kind = kind
            mapping.confidence = "derived"
            mapping.rationale = rationale
            mapping.evidence = evidence
            mapping.unresolved = unresolved
            return
    result.workload_mappings.append(
        WorkloadMapping(
            component=component.name,
            kubernetes_kind=kind,
            confidence="derived",
            rationale=rationale,
            evidence=evidence,
            unresolved=unresolved,
        )
    )


def _emit_java_unresolved(result: AnalysisResult, springs: dict[str, SpringContext]) -> None:
    existing = {u.subject for u in result.unresolved_operational_inputs}
    additions = [
        Unresolved(
            subject="readiness_liveness_probe",
            reason="the repository defines no health/readiness endpoint (no Spring Boot Actuator, no compose healthcheck)",
            needed_input="an HTTP path or TCP port to probe (e.g. TCP 8080, or GET the context root once warm)",
            kubernetes_effect="container readinessProbe / livenessProbe",
        ),
        Unresolved(
            subject="security_context_run_as_non_root",
            reason="the image sets no USER; running as root is a deployment decision, not stated in the repo",
            needed_input="target UID/GID and runAsNonRoot policy",
            kubernetes_effect="Pod/container securityContext",
        ),
        Unresolved(
            subject="graceful_shutdown",
            reason="start command runs a shell/Maven wrapper as PID 1; signal propagation to the JVM is not guaranteed",
            needed_input="an exec-form entrypoint (or tini) and the app's termination behaviour",
            kubernetes_effect="terminationGracePeriodSeconds, preStop hook, container.command",
        ),
    ]
    if any(ctx.embedded_databases for ctx in springs.values()):
        additions.append(
            Unresolved(
                subject="external_database_for_scaling",
                reason="the app uses an in-process in-memory database; replicas cannot share state and data is ephemeral",
                needed_input="whether to externalise to a managed/in-cluster DB, and its connection details",
                kubernetes_effect="external DB Service + ConfigMap/Secret; enables replicas>1 and durability",
            )
        )
    for item in additions:
        if item.subject not in existing:
            result.unresolved_operational_inputs.append(item)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _find_build_command(
    dockerfile_rel: str | None,
    dockerfile: Dockerfile | None,
    readmes: dict[str, list[str]],
) -> tuple[str | None, list[Evidence]]:
    evidence: list[Evidence] = []
    command: str | None = None
    if dockerfile is not None:
        for instr in dockerfile.find("RUN"):
            arg = instr.argument
            if ("mvn" in arg or "mvnw" in arg or "gradle" in arg) and (
                "package" in arg or "install" in arg or "build" in arg
            ):
                command = arg.strip()
                evidence.append(
                    Evidence(
                        path=dockerfile_rel or dockerfile.path,
                        selector="RUN",
                        symbol="RUN",
                        start_line=instr.start_line,
                        end_line=instr.end_line,
                    )
                )
                break
    # A Maven build line: `package` (jpetstore) or a profile-driven `verify`/`install`
    # (jhipster's `./mvnw -Pprod clean verify`). The whole line is captured so a
    # production `-P<profile>` flag is never dropped from the build command.
    def _is_maven_build(t: str) -> bool:
        return ("mvnw" in t or "mvn " in t) and any(
            goal in t for goal in ("package", "verify", "install")
        )

    readme_ev = _readme_evidence(readmes, _is_maven_build)
    if readme_ev is not None:
        evidence.append(readme_ev)
        if command is None:
            command = _readme_line(readmes, _is_maven_build)
    return command, evidence


def _dockerfile_cmd_evidence(
    dockerfile_rel: str | None, dockerfile: Dockerfile | None
) -> Evidence | None:
    if dockerfile is None:
        return None
    cmd = dockerfile.last("CMD")
    if cmd is None:
        return None
    return Evidence(
        path=dockerfile_rel or dockerfile.path,
        selector="CMD",
        symbol="CMD",
        start_line=cmd.start_line,
        end_line=cmd.end_line,
    )


def _referenced_profiles(text: str) -> set[str]:
    profiles: set[str] = set()
    for match in re.finditer(r"(?:-P|--activate-profiles)[=\s]+([A-Za-z0-9_,\-]+)", text):
        for name in match.group(1).split(","):
            name = name.strip()
            if name:
                profiles.add(name)
    return profiles


def _check_jdk_mismatch(
    result: AnalysisResult,
    path: str,
    base_image: str,
    maven: MavenProject,
    start: int,
    end: int,
) -> None:
    if maven.java_version is None:
        return
    target = _major_int(maven.java_version)
    tag = base_image.split(":", 1)[1] if ":" in base_image else ""
    image_major = _major_int(tag)
    if target is None or image_major is None or image_major == target:
        return
    result.warnings.append(
        Warning(
            code="jdk_version_mismatch",
            message=(
                f"Dockerfile base image '{base_image}' targets Java {image_major}, but the POM builds "
                f"for Java {target}. Align the runtime JDK to the build target to avoid class-version surprises."
            ),
            path=path,
        )
    )


def _major_int(value: str) -> int | None:
    match = re.match(r"(\d+)", value.strip())
    return int(match.group(1)) if match else None


def _readme_evidence(readmes: dict[str, list[str]], predicate) -> Evidence | None:
    for rel in sorted(readmes):
        for index, line in enumerate(readmes[rel]):
            if predicate(line):
                return Evidence(
                    path=rel,
                    selector="README",
                    symbol="run-instructions",
                    start_line=index + 1,
                    end_line=index + 1,
                )
    return None


def _readme_line(readmes: dict[str, list[str]], predicate) -> str | None:
    for rel in sorted(readmes):
        for line in readmes[rel]:
            if predicate(line):
                return line.strip().lstrip("$").strip()
    return None
