"""Spring Boot (Gradle) rules for the kubernetes-p0 profile.

Pure logic: parsed Gradle / Spring-properties / SQL facts in, mutations to the
shared ``AnalysisResult`` out. This is where explicit build facts (the Spring
Boot Gradle plugin, a Java toolchain, an embedded servlet container, per-profile
datasource placeholders, ``spring.sql.init`` locations, an Actuator dependency)
become *derived* Kubernetes conclusions, and where the things a repository cannot
decide (which external database to run in production, the buildpack image name,
whether to expose ``/livez``/``/readyz``) are recorded as ``unresolved``.

It never invents operational values, attaches real source lines to every
finding, and works with or without a compose file: the Spring Boot application is
synthesised from the Gradle build; any compose services (e.g. local databases)
remain their own components.
"""

from __future__ import annotations

import re

from ..inventory import Inventory, is_non_deployment_path
from ..models import (
    AnalysisResult,
    Component,
    Evidence,
    Finding,
    Unresolved,
    WorkloadMapping,
)
from ..parsers.common import Located
from ..parsers.compose import ComposeFile
from ..parsers.dockerfile import Dockerfile
from ..parsers.gradle import GradleBuild
from ..parsers.readme import ReadmeFile
from ..parsers.spring_properties import SpringProperties, SpringProperty
from ..parsers.sql_init import SqlInitScript

# Spring Boot starter artifact substring -> human framework label.
_STARTER_LABELS: tuple[tuple[str, str], ...] = (
    ("spring-boot-starter-webflux", "Spring WebFlux (reactive, embedded Netty)"),
    ("spring-boot-starter-webmvc", "Spring MVC (embedded servlet container)"),
    ("spring-boot-starter-web", "Spring MVC (embedded servlet container)"),
    ("spring-boot-starter-data-jpa", "Spring Data JPA"),
    ("spring-boot-starter-thymeleaf", "Thymeleaf"),
    ("spring-boot-starter-cache", "Spring Cache"),
    ("spring-boot-starter-validation", "Bean Validation"),
    ("spring-boot-starter-security", "Spring Security"),
)

# JDBC driver coordinate -> (label, jdbc scheme keyword).
_DB_DRIVERS: tuple[tuple[str, str, str], ...] = (
    ("com.h2database", "h2", "H2"),
    ("com.mysql", "mysql-connector", "MySQL"),
    ("mysql", "mysql-connector", "MySQL"),
    ("org.mariadb.jdbc", "mariadb", "MariaDB"),
    ("org.postgresql", "postgresql", "PostgreSQL"),
    ("com.microsoft.sqlserver", "mssql", "SQL Server"),
    ("com.oracle.database", "ojdbc", "Oracle"),
)

_DEFAULT_HTTP_PORT = 8080


def _ev(path: str, selector: str, start: int, end: int, symbol: str | None = None) -> Evidence:
    return Evidence(path=path, selector=selector, symbol=symbol, start_line=start, end_line=end)


def _ev_loc(loc: Located, path: str, symbol: str | None = None) -> Evidence:
    return Evidence(
        path=path, selector=loc.selector, symbol=symbol, start_line=loc.start_line, end_line=loc.end_line
    )


def _prop_ev(prop: SpringProperty, path: str) -> Evidence:
    return Evidence(path=path, selector=prop.key, symbol="property", start_line=prop.line, end_line=prop.line)


def _slug(label: str) -> str:
    base = label.split("(", 1)[0]
    return re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def analyze_spring_boot(
    *,
    result: AnalysisResult,
    inventory: Inventory,
    compose: ComposeFile | None,
    compose_path: str | None,
    gradle: GradleBuild,
    gradle_path: str,
    spring_props: dict[str, SpringProperties],
    sql_inits: dict[str, SqlInitScript],
    dockerfiles: dict[str, Dockerfile],
    readmes: dict[str, list[str]],
    readme_facts: dict[str, ReadmeFile] | None = None,
) -> None:
    readme_facts = readme_facts or {}
    name = _component_name(gradle)
    component = Component(name=name, workload_candidate="")
    result.components.append(component)

    default_props = _default_properties(spring_props)
    profile_props = _profile_properties(spring_props)
    # SQL-init scripts under documentation/examples/demo paths are samples, not the
    # deployable app's schema (e.g. kafka-ui's documentation/compose/postgres/data.sql).
    sql_inits = {p: s for p, s in sql_inits.items() if not is_non_deployment_path(p)}
    has_db = _has_db_evidence(gradle, default_props, profile_props, sql_inits)

    _fill_source_files(component, gradle, gradle_path, inventory, spring_props, sql_inits, readmes)
    _emit_build_system_stack(result, component, gradle, gradle_path, inventory)
    _emit_artifact_and_run(result, component, gradle, gradle_path, inventory)
    _emit_readme_commands(result, readme_facts)
    _emit_build_properties(result, gradle, gradle_path)
    _emit_port(result, component, gradle, gradle_path, spring_props, readmes)
    _emit_profiles_and_datasources(
        result, component, default_props, profile_props, gradle, gradle_path, has_db
    )
    _emit_sql_init(result, default_props, profile_props, sql_inits, gradle, gradle_path, has_db)
    _emit_actuator_and_probes(result, gradle, gradle_path, default_props)
    _emit_image_build(result, component, gradle, gradle_path, dockerfiles, inventory)
    _emit_storage_pvc(result, component, gradle_path)
    _emit_application_big_picture(
        result, component, gradle, gradle_path, sql_inits, profile_props, has_db, readme_facts
    )
    _emit_workload(result, component, gradle_path)
    _emit_unresolved(result, gradle, gradle_path, profile_props, has_db, _component_name(gradle))

    component.source_files.sort()
    component.environment = sorted(set(component.environment))
    component.secret_candidates = sorted(set(component.secret_candidates))


# --------------------------------------------------------------------------- #
# Selection / naming helpers
# --------------------------------------------------------------------------- #
def _component_name(gradle: GradleBuild) -> str:
    if gradle.root_project_name:
        return gradle.root_project_name
    if gradle.group:
        return gradle.group.rsplit(".", 1)[-1]
    return "app"


def _default_properties(spring_props: dict[str, SpringProperties]) -> SpringProperties | None:
    for props in spring_props.values():
        if props.profile is None:
            return props
    return None


def _profile_properties(spring_props: dict[str, SpringProperties]) -> list[SpringProperties]:
    return sorted(
        (p for p in spring_props.values() if p.profile is not None),
        key=lambda p: p.profile or "",
    )


def _wrapper_command(inventory: Inventory) -> tuple[str, bool]:
    has_gradlew = any(w.rsplit("/", 1)[-1] == "gradlew" for w in inventory.build_wrappers)
    return ("./gradlew", True) if has_gradlew else ("gradle", False)


def _module_dir(gradle_path: str) -> str:
    """Directory of the deployable build script, '' for the root build.gradle."""

    return gradle_path.rsplit("/", 1)[0] if "/" in gradle_path else ""


def _module_project_name(module_dir: str) -> str:
    """Gradle subproject name of a submodule: the module directory's basename
    (the default ``archiveBaseName`` for that project)."""

    return module_dir.rsplit("/", 1)[-1]


def _artifact_path(gradle: GradleBuild, gradle_path: str) -> tuple[str, str]:
    """``(bootJar artifact path, confidence)``.

    For a submodule the archive lives under ``<module-dir>/build/libs`` and the
    ``archiveBaseName`` defaults to the Gradle subproject name (the module
    directory's basename); the version is the module's own ``version`` when
    declared, else a wildcard — never invented. The root build keeps the
    project-name-derived path."""

    module_dir = _module_dir(gradle_path)
    if module_dir:
        name = _module_project_name(module_dir)
        filename = f"{name}-{gradle.version}.jar" if gradle.version else f"{name}-*.jar"
        return f"{module_dir}/build/libs/{filename}", "derived"
    base = gradle.artifact_base_name
    if base:
        return f"build/libs/{base}.jar", "derived"
    return "build/libs/*.jar", "explicit"


def _starter_frameworks(gradle: GradleBuild) -> list[tuple[str, Evidence]]:
    labels: list[tuple[str, Evidence]] = []
    seen: set[str] = set()
    for dep in gradle.dependencies:
        if dep.configuration.startswith("test"):
            continue
        artifact = dep.artifact or ""
        for substr, label in _STARTER_LABELS:
            if substr in artifact and label not in seen:
                seen.add(label)
                labels.append((label, _ev_loc(dep.location, gradle.path, "dependency")))
                break
    return labels


def _has_db_evidence(
    gradle: GradleBuild,
    default_props: SpringProperties | None,
    profile_props: list[SpringProperties],
    sql_inits: dict[str, SqlInitScript],
) -> bool:
    """True only if the repo actually has a relational database: a JDBC driver, a
    JPA/JDBC starter, a datasource/`database` property, or SQL-init scripts. Guards
    against inventing an H2/Postgres/MySQL story for DB-less apps (e.g. kafka-ui)."""

    if _db_drivers(gradle):
        return True
    for artifact in ("starter-data-jpa", "starter-jdbc", "starter-data-jdbc", "starter-data-r2dbc"):
        if gradle.has_dependency("org.springframework.boot", artifact):
            return True
    for props in ([default_props] if default_props is not None else []) + profile_props:
        if (
            props.get("spring.datasource.url") is not None
            or props.get("database") is not None
            or props.get("spring.sql.init.schema-locations") is not None
            or props.get("spring.sql.init.data-locations") is not None
        ):
            return True
    return bool(sql_inits)


def _db_drivers(gradle: GradleBuild) -> list[tuple[str, GradleBuild, Evidence]]:
    found: list[tuple[str, GradleBuild, Evidence]] = []
    seen: set[str] = set()
    for dep in gradle.dependencies:
        if dep.configuration.startswith("test"):
            continue
        group = dep.group or ""
        artifact = dep.artifact or ""
        for gprefix, asub, label in _DB_DRIVERS:
            if group.startswith(gprefix) and asub in artifact and label not in seen:
                seen.add(label)
                found.append((label, gradle, _ev_loc(dep.location, gradle.path, "dependency")))
                break
    return found


# --------------------------------------------------------------------------- #
# Emitters
# --------------------------------------------------------------------------- #
def _fill_source_files(
    component: Component,
    gradle: GradleBuild,
    gradle_path: str,
    inventory: Inventory,
    spring_props: dict[str, SpringProperties],
    sql_inits: dict[str, SqlInitScript],
    readmes: dict[str, list[str]],
) -> None:
    for path in (
        [gradle_path]
        + inventory.gradle_settings_files
        + inventory.gradle_wrapper_props
        + list(spring_props)
        + list(sql_inits)
        + list(readmes)
    ):
        if path not in component.source_files:
            component.source_files.append(path)


def _emit_build_system_stack(
    result: AnalysisResult,
    component: Component,
    gradle: GradleBuild,
    gradle_path: str,
    inventory: Inventory,
) -> None:
    wrapper_cmd, has_wrapper = _wrapper_command(inventory)
    gradle_ver = gradle.wrapper_gradle_version
    tool = "Gradle"
    if gradle_ver:
        tool += f" {gradle_ver}"
    if has_wrapper:
        tool += " (gradlew wrapper)"
    component.build_tool = tool

    # Java toolchain / language version.
    if gradle.java_version is not None:
        span = gradle.java_version_line or (1, 1)
        component.language = f"Java {gradle.java_version}"
        result.configuration.append(
            Finding(
                subject="runtime.java_version",
                value=f"Java {gradle.java_version}",
                confidence="explicit",
                kubernetes_effect="informs the container base image / buildpack JRE major version",
                evidence=[_ev(gradle_path, gradle.java_version_selector or "java", span[0], span[1], "toolchain")],
            )
        )

    # Spring Boot version from the plugin.
    boot = gradle.plugin_prefixed("org.springframework.boot")
    frameworks: list[str] = []
    if boot is not None:
        frameworks.append(f"Spring Boot {boot.version}" if boot.version else "Spring Boot")
        result.configuration.append(
            Finding(
                subject="framework.spring_boot",
                value=boot.version or "present",
                confidence="explicit",
                kubernetes_effect="Spring Boot app: self-contained executable JAR with an embedded server",
                evidence=[_ev_loc(boot.location, gradle_path, "plugin")],
            )
        )
    for label, ev in _starter_frameworks(gradle):
        frameworks.append(label)
        result.configuration.append(
            Finding(
                subject=f"framework.{_slug(label)}",
                value=label,
                confidence="explicit",
                kubernetes_effect="application framework (informs runtime behaviour; no direct K8s object)",
                evidence=[ev],
            )
        )
    component.frameworks = frameworks

    # Runtime summary for the component card.
    boot_label = f"Spring Boot {boot.version}" if boot and boot.version else "Spring Boot"
    servlet = gradle.find_dependency("org.springframework.boot", "starter-webflux") is None
    server = "embedded servlet container (Tomcat)" if servlet else "embedded reactive server (Netty)"
    component.runtime = f"{boot_label} application on an {server}; self-contained executable JAR"

    # Build tool + wrapper facts.
    wrapper_ev: list[Evidence] = []
    for wrel in inventory.build_wrappers:
        if wrel.rsplit("/", 1)[-1] == "gradlew":
            wrapper_ev.append(_ev(wrel, "gradlew", 1, 1, "wrapper-script"))
    if gradle.wrapper_location is not None and inventory.gradle_wrapper_props:
        wp = inventory.gradle_wrapper_props[0]
        wrapper_ev.append(_ev_loc(gradle.wrapper_location, wp, "distributionUrl"))
    result.configuration.append(
        Finding(
            subject="build.tool",
            value=tool,
            confidence="explicit",
            kubernetes_effect="build system that produces the deployable artifact (CI / image build)",
            evidence=wrapper_ev or [_ev(gradle_path, "plugins", 1, 1, "build.gradle")],
        )
    )
    if has_wrapper:
        result.configuration.append(
            Finding(
                subject="build.wrapper",
                value=wrapper_cmd,
                confidence="explicit",
                kubernetes_effect=(
                    "pinned Gradle wrapper makes the build reproducible in CI/image without a preinstalled Gradle"
                ),
                evidence=wrapper_ev or [_ev(gradle_path, "plugins", 1, 1)],
            )
        )


def _emit_artifact_and_run(
    result: AnalysisResult,
    component: Component,
    gradle: GradleBuild,
    gradle_path: str,
    inventory: Inventory,
) -> None:
    wrapper_cmd, _ = _wrapper_command(inventory)
    boot = gradle.plugin_prefixed("org.springframework.boot")

    # Build/run commands. In a multi-module repo the deployable app is a submodule,
    # so bootJar/bootRun must be qualified with the module path (e.g. `:api:bootJar`).
    module_dir = _module_dir(gradle_path)
    if module_dir:
        qualifier = f":{_module_project_name(module_dir)}:"
        bootjar_cmd = f"{wrapper_cmd} {qualifier}bootJar"
        bootrun_cmd = f"{wrapper_cmd} {qualifier}bootRun"
    else:
        bootjar_cmd = f"{wrapper_cmd} clean bootJar"
        bootrun_cmd = f"{wrapper_cmd} bootRun"

    component.build_command = bootjar_cmd
    for subject, value, effect in (
        ("build.command.bootjar", bootjar_cmd, "produces the executable Spring Boot JAR for the image"),
        ("build.command.bootrun", bootrun_cmd, "developer run (not used in the container image)"),
        ("build.command.test", f"{wrapper_cmd} test", "unit/integration tests (CI gate)"),
    ):
        result.configuration.append(
            Finding(
                subject=subject,
                value=value,
                confidence="derived",
                kubernetes_effect=effect,
                evidence=[_ev_loc(boot.location, gradle_path, "plugin")] if boot else [],
            )
        )

    # Executable JAR vs plain JAR.
    result.configuration.append(
        Finding(
            subject="build.artifact_type",
            value="executable-jar",
            confidence="derived",
            kubernetes_effect=(
                "the Spring Boot plugin's bootJar produces a self-contained, runnable fat JAR "
                "(java -jar). This differs from the plain `jar` task, which produces a thin library "
                "JAR that is NOT directly runnable."
            ),
            evidence=[_ev_loc(boot.location, gradle_path, "plugin")] if boot else [],
        )
    )

    # Artifact path derived from project metadata (never a hardcoded name). In a
    # multi-module repo the bootJar lives under the deployable submodule's build
    # dir (e.g. api/build/libs/api-*.jar), not the root project's.
    artifact_path, artifact_confidence = _artifact_path(gradle, gradle_path)
    component.build_artifact = artifact_path
    component.packaging = "jar (Spring Boot executable)"
    art_ev: list[Evidence] = []
    if module_dir:
        # The submodule's own build.gradle (its Spring Boot plugin) is what makes
        # this the deployable module and fixes the archive location.
        if boot is not None:
            art_ev.append(_ev_loc(boot.location, gradle_path, "plugin"))
    elif gradle.root_project_name_location is not None and inventory.gradle_settings_files:
        art_ev.append(_ev_loc(gradle.root_project_name_location, inventory.gradle_settings_files[0], "rootProject.name"))
    result.configuration.append(
        Finding(
            subject="build.artifact",
            value=artifact_path,
            confidence=artifact_confidence,
            kubernetes_effect="the runnable JAR to copy into the image / run with `java -jar`",
            evidence=art_ev or ([_ev_loc(boot.location, gradle_path, "plugin")] if boot else []),
        )
    )
    result.configuration.append(
        Finding(
            subject="runtime.exec_command",
            value=f"java -jar {artifact_path}",
            confidence="derived",
            kubernetes_effect="container command for the Deployment (exec form; JVM is PID 1 for clean SIGTERM)",
            evidence=art_ev or ([_ev_loc(boot.location, gradle_path, "plugin")] if boot else []),
        )
    )


def _emit_build_properties(
    result: AnalysisResult,
    gradle: GradleBuild,
    gradle_path: str,
) -> None:
    """Surface ``-P`` build properties the script references (e.g.
    ``include-frontend``, ``prod``). Each gates the build output, so the default
    ``bootJar`` may not produce the production artifact. We record the property as
    a build-time constraint and leave *whether* to enable it ``unresolved`` — the
    repository does not state which value the production build needs."""

    if not gradle.build_properties:
        return
    names: list[str] = []
    for name, loc in gradle.build_properties:
        names.append(name)
        result.build_time_constraints.append(
            Finding(
                subject=f"build.property.{name}",
                value="build-time",
                confidence="derived",
                kubernetes_effect=(
                    f"the build gates behaviour on the '{name}' Gradle property; pass `-P{name}` "
                    f"(e.g. `-P{name}=true`) at build time to change the produced artifact. It cannot "
                    "be set at runtime via env/ConfigMap."
                ),
                evidence=[_ev_loc(loc, gradle_path, "build.property")],
            )
        )
    result.unresolved_operational_inputs.append(
        Unresolved(
            subject="build_profile_properties",
            reason=(
                "the build references `-P` properties ("
                + ", ".join(names)
                + ") that change the produced artifact; which values the production build needs is "
                "not stated in the repository (e.g. bundling the frontend, a prod profile)"
            ),
            needed_input="the `-P` flags the production build requires (e.g. -Pinclude-frontend=true, -Pprod)",
            kubernetes_effect="the build/CI command that produces the deployable image artifact",
        )
    )


def _emit_readme_commands(result: AnalysisResult, readme_facts: dict[str, ReadmeFile]) -> None:
    wanted = {
        "./gradlew bootRun": "run.command.gradle",
        "./mvnw spring-boot:run": "run.command.maven",
        "./mvnw spring-boot:build-image": "image.build_command.maven",
    }
    seen: set[str] = set()
    for path, readme in sorted(readme_facts.items()):
        for command in readme.commands:
            value = str(command.value)
            subject = wanted.get(value)
            if subject is None or subject in seen:
                continue
            seen.add(subject)
            result.configuration.append(
                Finding(
                    subject=subject,
                    value=value,
                    confidence="explicit",
                    kubernetes_effect=(
                        "README-declared developer/build command; recorded as repository fact, "
                        "not selected as the production build path"
                    ),
                    evidence=[_ev_loc(command, path, "command")],
                )
            )


def _emit_port(
    result: AnalysisResult,
    component: Component,
    gradle: GradleBuild,
    gradle_path: str,
    spring_props: dict[str, SpringProperties],
    readmes: dict[str, list[str]],
) -> None:
    # An explicit server.port anywhere wins.
    for props in spring_props.values():
        entry = props.get("server.port")
        if entry is not None and entry.value:
            port = int(entry.value) if entry.value.isdigit() else _DEFAULT_HTTP_PORT
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
            result.networking.append(
                Finding(
                    subject="service.target_port",
                    value=port,
                    confidence="explicit",
                    kubernetes_effect=f"Service targetPort = {port} (the Service `port` itself is an operational choice)",
                    evidence=[_prop_ev(entry, props.path)],
                )
            )
            _emit_app_service_candidate(result, port, [_prop_ev(entry, props.path)])
            return

    # Otherwise the Spring Boot embedded-server default (8080), corroborated by
    # the web starter dependency and any README reference.
    web = gradle.find_dependency("org.springframework.boot", "starter-web")
    evidence: list[Evidence] = []
    if web is not None:
        evidence.append(_ev_loc(web.location, gradle_path, "dependency"))
    readme_ev = _readme_evidence(readmes, lambda t: ":8080" in t)
    if readme_ev is not None:
        evidence.append(readme_ev)
    component.container_ports = [_DEFAULT_HTTP_PORT]
    result.networking.append(
        Finding(
            subject="app.default_port",
            value=_DEFAULT_HTTP_PORT,
            confidence="derived",
            kubernetes_effect=(
                "no server.port is set, so Spring Boot's embedded server listens on 8080. "
                "Service targetPort=8080, containerPort=8080."
            ),
            evidence=evidence,
        )
    )
    result.networking.append(
        Finding(
            subject="service.target_port",
            value=_DEFAULT_HTTP_PORT,
            confidence="derived",
            kubernetes_effect="Service targetPort = 8080 (the Service `port` itself is an operational choice)",
            evidence=evidence,
        )
    )
    _emit_app_service_candidate(result, _DEFAULT_HTTP_PORT, evidence)


def _emit_app_service_candidate(result: AnalysisResult, target_port: int, evidence: list[Evidence]) -> None:
    result.networking.append(
        Finding(
            subject="service.app",
            value={
                "kind": "Service",
                "target_port": target_port,
                "port": "unresolved",
                "type": "unresolved",
            },
            confidence="derived",
            kubernetes_effect=(
                "Kubernetes Service is needed for the app; targetPort is repository-derived, while "
                "Service port/type are operational choices."
            ),
            evidence=evidence,
        )
    )


def _emit_profiles_and_datasources(
    result: AnalysisResult,
    component: Component,
    default_props: SpringProperties | None,
    profile_props: list[SpringProperties],
    gradle: GradleBuild,
    gradle_path: str,
    has_db: bool,
) -> None:
    # Default database (embedded H2) — never recommended for production.
    if default_props is not None:
        db_entry = default_props.get("database")
        if db_entry is not None:
            component.runtime_dependencies.append(f"Embedded {db_entry.value.upper()} (default profile, in-memory)")
            result.runtime_dependencies.append(
                Finding(
                    subject="database.default",
                    value=f"{db_entry.value} (embedded, in-memory)",
                    confidence="explicit",
                    kubernetes_effect=(
                        "default profile uses an in-process, in-memory database. Data is ephemeral and "
                        "per-replica; suitable for dev/demo only. Do NOT run this in production — choose an "
                        "external database (postgres/mysql profile)."
                    ),
                    evidence=[_prop_ev(db_entry, default_props.path)],
                )
            )

    # SPRING_PROFILES_ACTIVE selects the runtime database — only meaningful when
    # the repo actually has a database (never invent an H2/Postgres/MySQL story).
    if has_db:
        result.configuration.append(
            Finding(
                subject="config.SPRING_PROFILES_ACTIVE",
                value="(unset → default/h2)",
                confidence="derived",
                kubernetes_effect=(
                    "ConfigMap key candidate. Set SPRING_PROFILES_ACTIVE=postgres or =mysql to switch "
                    "to an external database; unset means the embedded H2 default."
                ),
                evidence=_profile_evidence(profile_props),
            )
        )
        if "SPRING_PROFILES_ACTIVE" not in component.environment:
            component.environment.append("SPRING_PROFILES_ACTIVE")

    # Per-profile external datasource + required env classification.
    for props in profile_props:
        profile = props.profile or ""
        db_label = _profile_db_label(props, gradle)
        url = props.get("spring.datasource.url")
        user = props.get("spring.datasource.username")
        pwd = props.get("spring.datasource.password")
        required_env: list[str] = []

        if url is not None:
            component.runtime_dependencies.append(f"External {db_label} ({profile} profile)")
            result.runtime_dependencies.append(
                Finding(
                    subject=f"database.profile.{profile}",
                    value=f"External {db_label}",
                    confidence="explicit",
                    kubernetes_effect=(
                        f"'{profile}' profile connects to an external {db_label}. Provide the JDBC URL via "
                        "ConfigMap and credentials via Secret; ensure network reachability from the cluster."
                    ),
                    evidence=[_prop_ev(url, props.path)],
                )
            )
        # URL env → ConfigMap; username/password env → Secret.
        for entry, role in ((url, "config"), (user, "secret"), (pwd, "secret")):
            if entry is None or not entry.placeholders:
                continue
            env_name = entry.placeholders[0].name
            required_env.append(env_name)
            if role == "config":
                if env_name not in component.environment:
                    component.environment.append(env_name)
                result.configuration.append(
                    Finding(
                        subject=f"config.{env_name}",
                        value=f"{entry.key} ({profile} profile)",
                        confidence="explicit",
                        kubernetes_effect="ConfigMap key candidate (non-secret connection detail)",
                        evidence=[_prop_ev(entry, props.path)],
                    )
                )
            else:
                if env_name not in component.secret_candidates:
                    component.secret_candidates.append(env_name)
                if env_name not in component.environment:
                    component.environment.append(env_name)
                result.secrets.append(
                    Finding(
                        subject=f"secret.{env_name}",
                        value="<redacted>",
                        confidence="explicit",
                        kubernetes_effect=f"Kubernetes Secret key candidate ({entry.key}, {profile} profile)",
                        evidence=[_prop_ev(entry, props.path)],
                    )
                )
        if required_env:
            result.configuration.append(
                Finding(
                    subject=f"profile.{profile}.required_env",
                    value=required_env,
                    confidence="derived",
                    kubernetes_effect=(
                        f"environment variables the '{profile}' profile needs (URL→ConfigMap, "
                        "USER/PASS→Secret), sourced from datasource property placeholders"
                    ),
                    evidence=[
                        _prop_ev(e, props.path)
                        for e in (url, user, pwd)
                        if e is not None
                    ],
                )
            )
            result.configuration.append(
                Finding(
                    subject=f"profile.{profile}.kubernetes_inputs",
                    value={
                        "configmap_keys": ["SPRING_PROFILES_ACTIVE"]
                        + [name for name in required_env if name.endswith("_URL")],
                        "secret_keys": [name for name in required_env if not name.endswith("_URL")],
                    },
                    confidence="derived",
                    kubernetes_effect=f"complete env input set to run the '{profile}' profile in Kubernetes",
                    evidence=[
                        _prop_ev(e, props.path)
                        for e in (url, user, pwd)
                        if e is not None
                    ],
                )
            )


def _emit_sql_init(
    result: AnalysisResult,
    default_props: SpringProperties | None,
    profile_props: list[SpringProperties],
    sql_inits: dict[str, SqlInitScript],
    gradle: GradleBuild,
    gradle_path: str,
    has_db: bool,
) -> None:
    if default_props is not None:
        schema = default_props.get("spring.sql.init.schema-locations")
        data = default_props.get("spring.sql.init.data-locations")
        if schema is not None or data is not None:
            locs = [x for x in (schema, data) if x is not None]
            result.startup_order.append(
                Finding(
                    subject="startup.sql_init",
                    value="; ".join(f"{x.key}={x.value}" for x in locs),
                    confidence="explicit",
                    kubernetes_effect=(
                        "Spring SQL init runs schema/data scripts in-process at application startup "
                        "(basic script init), NOT a separate migration Job."
                    ),
                    evidence=[_prop_ev(x, default_props.path) for x in locs],
                )
            )

    # Distinguish Spring SQL init from Flyway/Liquibase — but only when the repo
    # actually has a database (a DB-less app has no migration story to describe).
    has_migration_tool = gradle.has_dependency("org.flywaydb") or gradle.has_dependency("org.liquibase")
    if has_db and not has_migration_tool:
        result.startup_order.append(
            Finding(
                subject="startup.migration_tool",
                value="spring.sql.init (no Flyway/Liquibase)",
                confidence="derived",
                kubernetes_effect=(
                    "no versioned migration tool (Flyway/Liquibase) is on the classpath, so there is no "
                    "dedicated migration Job/initContainer; schema/data are applied in-process at startup."
                ),
                evidence=[_ev(gradle_path, "dependencies", 1, 1, "no flyway/liquibase")],
            )
        )

    # spring.sql.init.mode=always for external-DB profiles.
    for props in profile_props:
        mode = props.get("spring.sql.init.mode")
        if mode is not None:
            result.startup_order.append(
                Finding(
                    subject=f"startup.sql_init.mode.{props.profile}",
                    value=mode.value,
                    confidence="explicit",
                    kubernetes_effect=(
                        f"'{props.profile}' profile forces SQL init to run even against the external DB "
                        "(mode=always); it re-runs on every pod start."
                    ),
                    evidence=[_prop_ev(mode, props.path)],
                )
            )

    # Idempotency evidence from the schema scripts.
    idempotent = sorted(
        (path, s) for path, s in sql_inits.items() if s.has_create_tables and s.is_idempotent
    )
    if idempotent:
        ev: list[Evidence] = []
        for path, s in idempotent[:3]:
            marker = s.idempotency_marker_line or 1
            ev.append(_ev(path, "schema.sql", marker, marker, "idempotent-guard"))
        result.startup_order.append(
            Finding(
                subject="startup.sql_init.idempotent",
                value=f"{len(idempotent)} schema script(s) use IF (NOT) EXISTS guards",
                confidence="derived",
                kubernetes_effect=(
                    "schema DDL is guarded (CREATE TABLE IF NOT EXISTS / DROP TABLE IF EXISTS), so startup "
                    "SQL init re-runs safely on each pod start; no one-shot migration Job is required."
                ),
                evidence=ev,
            )
        )


def _emit_actuator_and_probes(
    result: AnalysisResult,
    gradle: GradleBuild,
    gradle_path: str,
    default_props: SpringProperties | None,
) -> None:
    actuator = gradle.find_dependency("org.springframework.boot", "actuator")
    if actuator is None:
        result.health_checks.append(
            Finding(
                subject="health.actuator",
                value="not present",
                confidence="explicit",
                kubernetes_effect=(
                    "no Spring Boot Actuator dependency; there is no built-in health endpoint to probe. "
                    "Add spring-boot-starter-actuator or probe the TCP port."
                ),
                evidence=[_ev(gradle_path, "dependencies", 1, 1, "no actuator")],
            )
        )
        return

    result.health_checks.append(
        Finding(
            subject="health.actuator",
            value="spring-boot-starter-actuator present",
            confidence="explicit",
            kubernetes_effect="exposes /actuator/health and the Kubernetes liveness/readiness health groups",
            evidence=[_ev_loc(actuator.location, gradle_path, "dependency")],
        )
    )

    exposure = default_props.get("management.endpoints.web.exposure.include") if default_props else None
    if exposure is not None:
        result.health_checks.append(
            Finding(
                subject="health.exposure",
                value=exposure.value,
                confidence="explicit",
                kubernetes_effect="controls which /actuator/* endpoints are reachable over HTTP",
                evidence=[_prop_ev(exposure, default_props.path)],
            )
        )

    base_ev = [_ev_loc(actuator.location, gradle_path, "dependency")]
    if exposure is not None and default_props is not None:
        base_ev.append(_prop_ev(exposure, default_props.path))

    for subject, path in (
        ("health.liveness_probe", "/actuator/health/liveness"),
        ("health.readiness_probe", "/actuator/health/readiness"),
    ):
        kind = "liveness" if "liveness" in subject else "readiness"
        result.health_checks.append(
            Finding(
                subject=subject,
                value=path,
                confidence="derived",
                kubernetes_effect=(
                    f"{kind}Probe httpGet path candidate on port 8080. Spring Boot auto-enables the "
                    f"{kind} health group when running under Kubernetes."
                ),
                evidence=base_ev,
            )
        )
    result.health_checks.append(
        Finding(
            subject="health.overall",
            value="/actuator/health",
            confidence="derived",
            kubernetes_effect="overall health endpoint (aggregate) on port 8080",
            evidence=base_ev,
        )
    )

    # /livez, /readyz are only valid if add-additional-paths is enabled — not in repo.
    add_paths = None
    if default_props is not None:
        add_paths = default_props.get("management.endpoint.health.probes.add-additional-paths")
    if add_paths is not None and add_paths.value.lower() == "true":
        for subject, path in (("health.livez", "/livez"), ("health.readyz", "/readyz")):
            result.health_checks.append(
                Finding(
                    subject=subject,
                    value=path,
                    confidence="explicit",
                    kubernetes_effect="additional short probe path enabled via add-additional-paths=true",
                    evidence=[_prop_ev(add_paths, default_props.path)],
                )
            )
    else:
        result.health_checks.append(
            Finding(
                subject="health.additional_paths",
                value="/livez, /readyz require management.endpoint.health.probes.add-additional-paths=true (NOT set in repo)",
                confidence="unresolved",
                kubernetes_effect=(
                    "use /actuator/health/liveness and /actuator/health/readiness by default. Only probe "
                    "/livez and /readyz if you enable add-additional-paths=true (e.g. via env/ConfigMap)."
                ),
                evidence=base_ev,
            )
        )


def _emit_image_build(
    result: AnalysisResult,
    component: Component,
    gradle: GradleBuild,
    gradle_path: str,
    dockerfiles: dict[str, Dockerfile],
    inventory: Inventory,
) -> None:
    boot = gradle.plugin_prefixed("org.springframework.boot")
    wrapper_cmd, _ = _wrapper_command(inventory)

    if dockerfiles:
        df = sorted(dockerfiles)[0]
        result.container_image.append(
            Finding(
                subject="image.dockerfile",
                value=df,
                confidence="explicit",
                kubernetes_effect="an application Dockerfile is present; it can build the container image",
                evidence=[_ev(df, "Dockerfile", 1, 1)],
            )
        )
    else:
        result.container_image.append(
            Finding(
                subject="image.dockerfile",
                value="none (no application Dockerfile)",
                confidence="explicit",
                kubernetes_effect=(
                    "no Dockerfile — but this does NOT mean the app cannot be containerised (see bootBuildImage)"
                ),
                evidence=[],
            )
        )

    if boot is not None:
        result.container_image.append(
            Finding(
                subject="image.buildpack_support",
                value=True,
                confidence="derived",
                kubernetes_effect=(
                    "the Spring Boot Gradle plugin provides `bootBuildImage`, which builds an OCI image with "
                    "Cloud Native Buildpacks — no Dockerfile needed."
                ),
                evidence=[_ev_loc(boot.location, gradle_path, "plugin")],
            )
        )
        result.container_image.append(
            Finding(
                subject="image.build_command",
                value=f"{wrapper_cmd} bootBuildImage",
                confidence="derived",
                kubernetes_effect="builds the container image via buildpacks (requires a Docker daemon or rootless builder)",
                evidence=[_ev_loc(boot.location, gradle_path, "plugin")],
            )
        )
        result.container_image.append(
            Finding(
                subject="image.build_strategy",
                value="buildpack (bootBuildImage) vs Dockerfile",
                confidence="derived",
                kubernetes_effect=(
                    "buildpacks auto-detect the JDK/JRE and layer the app for you (reproducible, maintained "
                    "base images); a Dockerfile gives full control but you own the base image and CVE patching."
                ),
                evidence=[_ev_loc(boot.location, gradle_path, "plugin")],
            )
        )
        result.container_image.append(
            Finding(
                subject="image.runs_as_nonroot",
                value="buildpack image runs as non-root by default",
                confidence="derived",
                kubernetes_effect=(
                    "Paketo/Spring buildpack images run as the non-root `cnb` user, so "
                    "securityContext.runAsNonRoot is satisfied when built via bootBuildImage (still set it explicitly)."
                ),
                evidence=[_ev_loc(boot.location, gradle_path, "plugin")],
            )
        )


def _emit_storage_pvc(result: AnalysisResult, component: Component, gradle_path: str) -> None:
    result.storage.append(
        Finding(
            subject="storage.application_pvc",
            value="not required",
            confidence="derived",
            kubernetes_effect=(
                "the application is stateless: it writes no local persistent files and keeps all state in "
                "the database. The Deployment needs no PVC/volumeMount. Database persistence is a SEPARATE "
                "concern handled by the (external/managed) DB, not the app."
            ),
            evidence=[_ev(gradle_path, "dependencies", 1, 1, "no volume/persistent-file config")],
        )
    )


def _emit_application_big_picture(
    result: AnalysisResult,
    component: Component,
    gradle: GradleBuild,
    gradle_path: str,
    sql_inits: dict[str, SqlInitScript],
    profile_props: list[SpringProperties],
    has_db: bool,
    readme_facts: dict[str, ReadmeFile],
) -> None:
    table_names, table_evidence = _sql_table_names(sql_inits)
    web = (
        gradle.find_dependency("org.springframework.boot", "starter-web")
        or gradle.find_dependency("org.springframework.boot", "starter-webmvc")
        or gradle.find_dependency("org.springframework.boot", "starter-webflux")
    )
    readme_title, readme_desc, readme_evidence = _readme_summary(readme_facts)
    summary_evidence = readme_evidence
    if web is not None:
        summary_evidence.append(_ev_loc(web.location, gradle_path, "dependency"))
    summary_evidence.extend(table_evidence[:5])
    runtime_summary = "Spring Boot web application" if web is not None else "Spring Boot application"
    if readme_title and readme_desc:
        summary = f"{readme_title} - {readme_desc}. Runtime: {runtime_summary}"
    elif readme_title:
        summary = f"{readme_title}. Runtime: {runtime_summary}"
    else:
        summary = f"{runtime_summary} named {component.name}"
    if table_names:
        summary += " backed by relational tables: " + ", ".join(table_names)
    result.configuration.append(
        Finding(
            subject="application.summary",
            value=summary,
            confidence="derived",
            kubernetes_effect=(
                "high-level application shape for migration planning, derived from build dependencies and "
                "repository schema files; it is not a generated manifest."
            ),
            evidence=summary_evidence or [_ev(gradle_path, "plugins", 1, 1, "spring-boot")],
        )
    )
    if table_names:
        result.configuration.append(
            Finding(
                subject="application.data_model",
                value=table_names,
                confidence="explicit",
                kubernetes_effect=(
                    "repository SQL init declares these relational tables; use them as the source-level "
                    "data-domain inventory when planning database migration."
                ),
                evidence=table_evidence,
            )
        )
    if has_db and table_names:
        profiles = sorted(p.profile for p in profile_props if p.profile)
        result.storage.append(
            Finding(
                subject="storage.database_persistence",
                value={"profiles": profiles, "tables": table_names},
                confidence="derived",
                kubernetes_effect=(
                    "application state is stored in the selected external database profile. The database "
                    "needs durable storage or a managed database service; the application Deployment still "
                    "does not need its own PVC."
                ),
                evidence=table_evidence,
            )
        )


def _emit_workload(result: AnalysisResult, component: Component, gradle_path: str) -> None:
    kind = "Deployment + ClusterIP Service"
    component.workload_candidate = kind
    unresolved = [
        "replica count",
        "CPU/memory requests/limits",
        "external database selection (postgres vs mysql) for production",
        "startupProbe thresholds",
        "container image name/registry",
    ]
    result.workload_mappings.append(
        WorkloadMapping(
            component=component.name,
            kubernetes_kind=kind,
            confidence="derived",
            rationale=(
                "Stateless Spring Boot application on an embedded server; horizontally scalable behind a "
                "ClusterIP Service (targetPort 8080). No application PVC. Needs a ConfigMap (profile, DB URL) "
                "and a Secret (DB credentials) when using an external database, plus liveness/readiness probes."
            ),
            evidence=[_ev(gradle_path, "plugins", 1, 1, "spring-boot")],
            unresolved=unresolved,
        )
    )


def _emit_unresolved(
    result: AnalysisResult,
    gradle: GradleBuild,
    gradle_path: str,
    profile_props: list[SpringProperties],
    has_db: bool,
    app_name: str,
) -> None:
    profiles = sorted(p.profile for p in profile_props if p.profile)
    existing = {u.subject for u in result.unresolved_operational_inputs}
    additions: list[Unresolved] = []
    if has_db:
        additions.append(
            Unresolved(
                subject="production_database_selection",
                reason=(
                    "the repo supports an embedded H2 default plus external "
                    + (", ".join(profiles) if profiles else "database")
                    + " profiles; which one to run in production is not decided by the repository"
                ),
                needed_input="choose a profile (e.g. postgres or mysql) and supply the JDBC URL + credentials",
                kubernetes_effect="SPRING_PROFILES_ACTIVE (ConfigMap) + datasource ConfigMap/Secret; external DB Service",
            )
        )
        additions.append(
            Unresolved(
                subject="database_service_endpoint",
                reason=(
                    "the repo declares datasource placeholders but does not decide the destination database "
                    "host/service name, JDBC URL value, or Secret key mapping for the selected profile"
                ),
                needed_input="the database service endpoint/JDBC URL and the Secret keys to map into datasource env vars",
                kubernetes_effect="ConfigMap datasource URL + Secret-backed datasource username/password env",
            )
        )
    additions += [
        Unresolved(
            subject="service_port_and_type",
            reason=(
                "the repository determines the container/service targetPort but not how the app is exposed "
                "inside or outside the destination cluster"
            ),
            needed_input="Service port/type and, if externally exposed, the Ingress/Gateway route",
            kubernetes_effect="Service.spec.ports[].port, Service.spec.type, and optional Ingress/Gateway",
        ),
        Unresolved(
            subject="container_image_name",
            reason="bootBuildImage's image name/registry is not pinned in the repo",
            needed_input=f"target image coordinates, e.g. registry/namespace/{app_name}:<tag>",
            kubernetes_effect="Deployment.spec.template.spec.containers[].image",
        ),
        Unresolved(
            subject="health_probe_additional_paths",
            reason="the repo does not enable management.endpoint.health.probes.add-additional-paths",
            needed_input="decide whether to expose /livez,/readyz or use /actuator/health/{liveness,readiness}",
            kubernetes_effect="livenessProbe/readinessProbe httpGet.path",
        ),
        Unresolved(
            subject="startup_probe",
            reason="JVM/Spring Boot cold-start time is environment-dependent and not stated in the repo",
            needed_input="expected startup duration to size startupProbe failureThreshold/periodSeconds",
            kubernetes_effect="container.startupProbe (protects a slow-starting JVM from liveness restarts)",
        ),
        Unresolved(
            subject="graceful_shutdown",
            reason="server.shutdown=graceful is not set in the repo (Spring Boot defaults to immediate shutdown)",
            needed_input="whether to enable graceful shutdown and the drain timeout",
            kubernetes_effect="server.shutdown + spring.lifecycle.timeout-per-shutdown-phase; terminationGracePeriodSeconds",
        ),
        Unresolved(
            subject="security_context_run_as_non_root",
            reason="runAsNonRoot/UID is a deployment policy; buildpack images default to non-root but it is not pinned",
            needed_input="target UID/GID and runAsNonRoot policy",
            kubernetes_effect="Pod/container securityContext",
        ),
    ]
    for item in additions:
        if item.subject not in existing:
            result.unresolved_operational_inputs.append(item)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _profile_db_label(props: SpringProperties, gradle: GradleBuild) -> str:
    url = props.get("spring.datasource.url")
    if url is not None:
        low = url.value.lower()
        if "postgresql" in low or "postgres" in low:
            return "PostgreSQL"
        if "mysql" in low:
            return "MySQL"
        if "mariadb" in low:
            return "MariaDB"
        if "sqlserver" in low:
            return "SQL Server"
        if "oracle" in low:
            return "Oracle"
    return (props.profile or "database").capitalize()


def _profile_evidence(profile_props: list[SpringProperties]) -> list[Evidence]:
    ev: list[Evidence] = []
    for props in profile_props:
        entry = props.get("spring.datasource.url") or (props.entries[0] if props.entries else None)
        if entry is not None:
            ev.append(_prop_ev(entry, props.path))
    return ev


def _sql_table_names(sql_inits: dict[str, SqlInitScript]) -> tuple[list[str], list[Evidence]]:
    names: set[str] = set()
    evidence: list[Evidence] = []
    seen_ev: set[tuple[str, str, int]] = set()
    for path, script in sorted(sql_inits.items()):
        for table in script.table_names:
            name = str(table.value)
            names.add(name)
            key = (path, name, table.start_line)
            if key in seen_ev:
                continue
            seen_ev.add(key)
            evidence.append(
                Evidence(
                    path=path,
                    selector=table.selector,
                    symbol="table",
                    start_line=table.start_line,
                    end_line=table.end_line,
                )
            )
    return sorted(names), evidence


def _readme_summary(readme_facts: dict[str, ReadmeFile]) -> tuple[str | None, str | None, list[Evidence]]:
    for path, readme in sorted(readme_facts.items()):
        evidence: list[Evidence] = []
        title = None
        desc = None
        if readme.title is not None:
            title = _plain_markdown(str(readme.title.value))
            evidence.append(_ev_loc(readme.title, path, "readme-title"))
        if readme.application_description is not None:
            desc = _plain_markdown(str(readme.application_description.value)).rstrip(".")
            evidence.append(_ev_loc(readme.application_description, path, "readme-description"))
        if title or desc:
            return title, desc, evidence
    return None, None, []


def _plain_markdown(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _readme_evidence(readmes: dict[str, list[str]], predicate) -> Evidence | None:
    for rel in sorted(readmes):
        for index, line in enumerate(readmes[rel]):
            if predicate(line):
                return Evidence(
                    path=rel, selector="README", symbol="run-instructions", start_line=index + 1, end_line=index + 1
                )
    return None
