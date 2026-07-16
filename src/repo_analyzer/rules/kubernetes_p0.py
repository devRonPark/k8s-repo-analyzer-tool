"""kubernetes-p0 rule engine.

Pure function: parsed facts in, ``AnalysisResult`` out. No file or network I/O.
This is the only place ``explicit`` facts are combined into ``derived``
conclusions and where operational unknowns are recorded as ``unresolved``.
Nothing here invents a value the repository does not contain.
"""

from __future__ import annotations

import re

from ..inventory import Inventory
from ..models import (
    AnalysisResult,
    Component,
    Evidence,
    Finding,
    RepositoryMetadata,
    Unresolved,
    UnsupportedConstruct,
    Warning,
    WorkloadMapping,
)
from ..models import DetectedFile
from ..parsers.common import Located
from ..parsers.compose import ComposeFile, ComposeService
from ..parsers.dockerfile import Dockerfile, exec_form
from ..parsers.dotenv import DotenvFile
from ..parsers.maven import MavenProject
from ..parsers.nginx import NginxConfig
from ..parsers.python_settings import PythonSettings
from ..parsers.spring_xml import SpringContext
from ..parsers.webxml import WebApp
from .java_webapp import analyze_java_webapp

# Substrings (case-insensitive) that mark an env var as a Secret candidate.
_SECRET_PATTERNS = (
    "PASSWORD",
    "PASSWD",
    "SECRET",
    "TOKEN",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "API_KEY",
    "APIKEY",
    "CREDENTIAL",
    "DSN",
)
_PLACEHOLDER_VALUES = {"changethis", "change_this", "changeme", "secret", "password"}

_DB_IMAGE_RUNTIMES = {
    "postgres": ("PostgreSQL", 5432),
    "postgresql": ("PostgreSQL", 5432),
    "mysql": ("MySQL", 3306),
    "mariadb": ("MariaDB", 3306),
    "redis": ("Redis", 6379),
    "mongo": ("MongoDB", 27017),
}


def is_secret(name: str) -> bool:
    upper = name.upper()
    return any(pattern in upper for pattern in _SECRET_PATTERNS)


def _ev(loc: Located, path: str, symbol: str | None = None) -> Evidence:
    return Evidence(
        path=path,
        selector=loc.selector,
        symbol=symbol,
        start_line=loc.start_line,
        end_line=loc.end_line,
    )


def _env_name(entry: str) -> str:
    return entry.split("=", 1)[0].strip()


def _traefik_lb_port(labels: list[Located]) -> tuple[int, Located] | None:
    for label in labels:
        match = re.search(r"loadbalancer\.server\.port=(\d+)", str(label.value))
        if match:
            return int(match.group(1)), label
    return None


def _traefik_hosts(labels: list[Located]) -> list[tuple[str, Located]]:
    hosts: list[tuple[str, Located]] = []
    for label in labels:
        for match in re.finditer(r"Host\(`([^`]+)`\)", str(label.value)):
            hosts.append((match.group(1), label))
    return hosts


def _healthcheck_url(test_value: object) -> tuple[int | None, str | None]:
    tokens: list[str] = []
    if isinstance(test_value, list):
        tokens = [str(t) for t in test_value]
    elif isinstance(test_value, str):
        tokens = test_value.split()
    for token in tokens:
        match = re.search(r"https?://[^/\s]+:(\d+)(/\S*)?", token)
        if match:
            return int(match.group(1)), (match.group(2) or "/")
    return None, None


def _parse_workers(command: list[str]) -> int | None:
    for index, token in enumerate(command):
        if token == "--workers" and index + 1 < len(command):
            if command[index + 1].isdigit():
                return int(command[index + 1])
        match = re.fullmatch(r"--workers=(\d+)", token)
        if match:
            return int(match.group(1))
    return None


def _split_volume(spec: str) -> tuple[str, str] | None:
    parts = spec.split(":")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None


def _implicit_dockerfile(
    build_context: str, dockerfiles: dict[str, Dockerfile]
) -> tuple[str, Dockerfile] | None:
    """Resolve the default ``<context>/Dockerfile`` a compose build would use."""

    context = build_context.strip()
    if context in ("", "."):
        candidate = "Dockerfile"
    else:
        candidate = f"{context.rstrip('/')}/Dockerfile"
    candidate = candidate.lstrip("./") if candidate.startswith("./") else candidate
    obj = dockerfiles.get(candidate)
    if obj is not None:
        return candidate, obj
    return None


def _published_container_port(ports: list[Located]) -> tuple[int, Located] | None:
    """Container-side port of a ``host:container`` (or bare ``container``) mapping."""

    for port in ports:
        spec = str(port.value).strip()
        # Strip an optional protocol suffix (e.g. "8080:8080/tcp").
        spec = spec.split("/", 1)[0]
        segments = spec.split(":")
        container_side = segments[-1]
        if container_side.isdigit():
            return int(container_side), port
    return None


def analyze_kubernetes_p0(
    *,
    repo_name: str,
    profile: str,
    git_ref: str | None,
    inventory: Inventory,
    compose: ComposeFile | None,
    dockerfiles: dict[str, Dockerfile],
    dotenvs: dict[str, DotenvFile],
    nginx: dict[str, NginxConfig],
    settings: dict[str, PythonSettings],
    shell_scripts: dict[str, list[str]],
    mavens: dict[str, MavenProject] | None = None,
    webapps: dict[str, WebApp] | None = None,
    springs: dict[str, SpringContext] | None = None,
    readmes: dict[str, list[str]] | None = None,
    env_usage: dict[str, list[tuple[str, int]]],
) -> AnalysisResult:
    mavens = mavens or {}
    webapps = webapps or {}
    springs = springs or {}
    readmes = readmes or {}

    result = AnalysisResult(
        repository=RepositoryMetadata(
            name=repo_name,
            profile=profile,
            git_ref=git_ref,
            file_count=len(inventory.detected),
        ),
        detected_files=inventory.detected,
    )

    _collect_unsupported(result, compose, dockerfiles, dotenvs, nginx, settings)
    _register_spring_detected(result, springs)
    _warn_extra_compose(result, inventory)

    # Nothing to analyze at all: honestly report the absence and stop.
    if compose is None and not mavens:
        result.warnings.append(
            Warning(code="no_compose", message="no compose file found; component topology unavailable")
        )
        _emit_operational_unresolved(result, has_db=False)
        return result

    compose_path = inventory.compose_primary or (compose.path if compose else None)
    main_nginx = _main_nginx(nginx)

    if compose is not None:
        for service in compose.services:
            _analyze_service(
                result=result,
                service=service,
                compose_path=compose_path,
                dockerfiles=dockerfiles,
                main_nginx=main_nginx,
                env_usage=env_usage,
            )
        _analyze_config_and_secrets(result, dotenvs)
        _analyze_startup(result, compose, compose_path, inventory, shell_scripts)

    # Java/Maven web-application path (works with or without a compose file).
    if mavens:
        analyze_java_webapp(
            result=result,
            inventory=inventory,
            compose=compose,
            compose_path=compose_path,
            dockerfiles=dockerfiles,
            mavens=mavens,
            webapps=webapps,
            springs=springs,
            readmes=readmes,
        )

    has_db = _has_db(compose) if compose is not None else False
    _emit_operational_unresolved(result, has_db=has_db)
    return result


def _register_spring_detected(result: AnalysisResult, springs: dict[str, SpringContext]) -> None:
    if not springs:
        return
    existing = {d.path for d in result.detected_files}
    for path in springs:
        if path not in existing:
            result.detected_files.append(DetectedFile(path=path, kind="spring-context"))
    result.detected_files.sort(key=lambda d: d.path)
    result.repository.file_count = len(result.detected_files)


# --------------------------------------------------------------------------- #
# Per-service analysis
# --------------------------------------------------------------------------- #
def _analyze_service(
    *,
    result: AnalysisResult,
    service: ComposeService,
    compose_path: str,
    dockerfiles: dict[str, Dockerfile],
    main_nginx: tuple[str, NginxConfig] | None,
    env_usage: dict[str, list[tuple[str, int]]],
) -> None:
    component = Component(name=service.name, workload_candidate="")
    component.source_files.append(compose_path)

    image_value = service.image.value if service.image else None
    component.image = image_value

    dockerfile_obj: Dockerfile | None = None
    if service.build_dockerfile:
        component.dockerfile = str(service.build_dockerfile.value)
        dockerfile_obj = dockerfiles.get(component.dockerfile)
        if component.dockerfile not in component.source_files and dockerfile_obj:
            component.source_files.append(component.dockerfile)
    if service.build_context:
        component.build_context = str(service.build_context.value)
    # Resolve the implicit `<context>/Dockerfile` when compose omits `dockerfile`.
    if dockerfile_obj is None and component.build_context is not None:
        implicit = _implicit_dockerfile(component.build_context, dockerfiles)
        if implicit is not None:
            rel, dockerfile_obj = implicit
            component.dockerfile = rel
            if rel not in component.source_files:
                component.source_files.append(rel)
    component.build_args = [_env_name(a.value) for a in service.build_args]

    # Command resolution: compose command wins, else Dockerfile CMD (exec form).
    command_list, command_ev = _resolve_command(service, dockerfile_obj, compose_path)
    component.command = command_list
    if command_list is not None:
        component.workers = _parse_workers(command_list)

    component.runtime = _resolve_runtime(service, dockerfile_obj, image_value)

    # Environment / secrets referenced by this service.
    for entry in service.environment:
        name = _env_name(entry.value)
        if name and name not in component.environment:
            component.environment.append(name)
    component.secret_candidates = [n for n in component.environment if is_secret(n)]

    # Ports.
    port, port_conf, port_ev = _resolve_port(service, dockerfile_obj, main_nginx, compose_path)
    if port is not None:
        component.container_ports.append(port)
        result.networking.append(
            Finding(
                subject=f"{service.name}.container_port",
                value=port,
                confidence=port_conf,
                kubernetes_effect=f"{service.name} Service targetPort candidate",
                evidence=port_ev,
            )
        )
    component.published_ports = [str(p.value) for p in service.ports]

    # Ingress host candidates from Traefik router labels (deduplicated by host).
    seen_hosts: set[str] = set()
    for host, label in _traefik_hosts(service.labels):
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        result.networking.append(
            Finding(
                subject=f"{service.name}.ingress_host",
                value=host,
                confidence="derived",
                kubernetes_effect="Ingress host rule candidate (currently routed by Traefik labels)",
                evidence=[_ev(label, compose_path, "traefik.host")],
            )
        )

    # Health check.
    _service_healthcheck(result, service, compose_path, component)

    # Storage.
    _service_storage(result, service, compose_path, component)

    # Build-time constraint: build args baked into the image (e.g. VITE_API_URL).
    _service_build_time(result, service, dockerfile_obj, compose_path, component, env_usage)

    # Workload mapping.
    _service_workload(result, service, compose_path, component)

    result.components.append(component)


def _resolve_command(
    service: ComposeService, dockerfile: Dockerfile | None, compose_path: str
) -> tuple[list[str] | None, list[Evidence]]:
    if service.command is not None:
        return list(service.command.value), [_ev(service.command, compose_path)]
    if dockerfile is not None:
        cmd = dockerfile.last("CMD")
        if cmd is not None:
            argv = exec_form(cmd.argument)
            if argv is not None:
                return argv, [
                    Evidence(
                        path=dockerfile.path,
                        selector="CMD",
                        symbol="CMD",
                        start_line=cmd.start_line,
                        end_line=cmd.end_line,
                    )
                ]
    return None, []


def _resolve_runtime(
    service: ComposeService, dockerfile: Dockerfile | None, image: str | None
) -> str | None:
    if dockerfile is not None and dockerfile.final_base_image is not None:
        base = dockerfile.final_base_image.image.lower()
        if base.startswith("nginx"):
            return "Nginx (static assets)"
        if base.startswith(("python", "oven/bun", "node")):
            cmd = dockerfile.last("CMD")
            if cmd and "fastapi" in cmd.argument.lower():
                return "FastAPI"
    if service.command is not None and "prestart" in " ".join(service.command.value):
        return "init job (bash script)"
    if image:
        key = image.split(":", 1)[0].split("/")[-1].lower()
        if key in _DB_IMAGE_RUNTIMES:
            return _DB_IMAGE_RUNTIMES[key][0]
        if key == "adminer":
            return "Adminer (DB admin UI)"
        return key
    return None


def _resolve_port(
    service: ComposeService,
    dockerfile: Dockerfile | None,
    main_nginx: tuple[str, NginxConfig] | None,
    compose_path: str,
) -> tuple[int | None, str, list[Evidence]]:
    evidence: list[Evidence] = []
    lb = _traefik_lb_port(service.labels)

    # Health check URL is a strong explicit signal.
    if service.healthcheck_test is not None:
        hc_port, _ = _healthcheck_url(service.healthcheck_test.value)
        if hc_port is not None:
            evidence.append(_ev(service.healthcheck_test, compose_path, "healthcheck.url"))
            if lb is not None and lb[0] == hc_port:
                evidence.append(_ev(lb[1], compose_path, "traefik.port"))
            return hc_port, "derived", evidence

    # Nginx runtime: listen directive + LB label.
    if dockerfile is not None and dockerfile.final_base_image is not None:
        if dockerfile.final_base_image.image.lower().startswith("nginx") and main_nginx is not None:
            nginx_path, cfg = main_nginx
            listens = cfg.find("listen")
            if listens:
                directive = listens[0]
                evidence.append(
                    Evidence(
                        path=nginx_path,
                        selector="listen",
                        symbol="listen",
                        start_line=directive.start_line,
                        end_line=directive.end_line,
                    )
                )
                port = int(directive.args[0]) if directive.args and directive.args[0].isdigit() else None
                if port is not None:
                    if lb is not None and lb[0] == port:
                        evidence.append(_ev(lb[1], compose_path, "traefik.port"))
                    return port, "derived", evidence

    # Database image default + declared client port from env is handled by caller
    # via image; here fall back to Traefik LB label alone.
    if lb is not None:
        return lb[0], "explicit", [_ev(lb[1], compose_path, "traefik.port")]

    # Known database image default port.
    if service.image is not None:
        key = str(service.image.value).split(":", 1)[0].split("/")[-1].lower()
        if key in _DB_IMAGE_RUNTIMES:
            return (
                _DB_IMAGE_RUNTIMES[key][1],
                "derived",
                [_ev(service.image, compose_path, "image.default_port")],
            )

    # Final fallback: the container side of a published `host:container` mapping.
    published = _published_container_port(service.ports)
    if published is not None:
        port_value, located = published
        return port_value, "explicit", [_ev(located, compose_path, "ports.published")]
    return None, "explicit", []


def _service_healthcheck(
    result: AnalysisResult, service: ComposeService, compose_path: str, component: Component
) -> None:
    if service.healthcheck is None:
        return
    test_value = service.healthcheck_test.value if service.healthcheck_test else None
    _, path = _healthcheck_url(test_value)
    if path is not None:
        component.healthcheck = f"HTTP GET {path}"
        result.health_checks.append(
            Finding(
                subject=f"{service.name}.health_path",
                value=path,
                confidence="explicit",
                kubernetes_effect="readiness/liveness probe httpGet.path candidate",
                evidence=[_ev(service.healthcheck, compose_path)],
            )
        )
    else:
        summary = " ".join(str(t) for t in test_value) if isinstance(test_value, list) else str(test_value)
        component.healthcheck = f"exec: {summary}"
        result.health_checks.append(
            Finding(
                subject=f"{service.name}.health_exec",
                value=summary,
                confidence="explicit",
                kubernetes_effect="readiness probe exec.command candidate",
                evidence=[_ev(service.healthcheck, compose_path)],
            )
        )


def _service_storage(
    result: AnalysisResult, service: ComposeService, compose_path: str, component: Component
) -> None:
    for vol in service.volumes:
        parsed = _split_volume(str(vol.value))
        if parsed is None:
            continue
        source, mount = parsed
        # A named volume (not a host bind path) implies persistent data.
        is_named = "/" not in source and not source.startswith(".")
        component.volumes.append(f"{source} -> {mount}")
        if is_named:
            result.storage.append(
                Finding(
                    subject=f"{service.name}.persistent_volume",
                    value={"volume": source, "mount_path": mount},
                    confidence="explicit",
                    kubernetes_effect="PersistentVolumeClaim + volumeMount (StatefulSet volumeClaimTemplate candidate)",
                    evidence=[_ev(vol, compose_path)],
                )
            )
            component.unresolved.append("PVC size")


def _service_build_time(
    result: AnalysisResult,
    service: ComposeService,
    dockerfile: Dockerfile | None,
    compose_path: str,
    component: Component,
    env_usage: dict[str, list[tuple[str, int]]],
) -> None:
    for arg in service.build_args:
        name = _env_name(arg.value)
        if not name.startswith("VITE_") and "API_URL" not in name.upper():
            continue
        evidence = [_ev(arg, compose_path, "build.arg")]
        if dockerfile is not None:
            for instr in dockerfile.find("ARG"):
                if instr.argument.split("=", 1)[0].strip() == name:
                    evidence.append(
                        Evidence(
                            path=dockerfile.path,
                            selector="ARG",
                            symbol=name,
                            start_line=instr.start_line,
                            end_line=instr.end_line,
                        )
                    )
        for used_path, line in env_usage.get(name, []):
            evidence.append(
                Evidence(
                    path=used_path,
                    selector=name,
                    symbol="import.meta.env",
                    start_line=line,
                    end_line=line,
                )
            )
        result.build_time_constraints.append(
            Finding(
                subject=f"{service.name}.{name.lower()}_binding",
                value="build-time",
                confidence="derived",
                kubernetes_effect=(
                    f"{name} is baked into the image at build time; it cannot be changed via "
                    "runtime env/ConfigMap. Rebuild per environment or introduce runtime config."
                ),
                evidence=evidence,
            )
        )


def _service_workload(
    result: AnalysisResult, service: ComposeService, compose_path: str, component: Component
) -> None:
    name = service.name
    image_key = ""
    if service.image is not None:
        image_key = str(service.image.value).split(":", 1)[0].split("/")[-1].lower()
    has_persistent = any("PVC size" == u for u in component.unresolved)

    base_ev = [
        Evidence(
            path=compose_path,
            selector=service.selector,
            symbol="service",
            start_line=service.image.start_line if service.image else 0,
            end_line=service.image.end_line if service.image else 0,
        )
    ]

    if image_key in _DB_IMAGE_RUNTIMES or has_persistent:
        kind = "StatefulSet + headless Service (or external managed database)"
        rationale = "Stateful component with persistent data; not a stateless Deployment."
        unresolved = ["replica count", "CPU/memory", "PVC size", "StorageClass", "DB HA & backup policy"]
    elif str(service.command.value if service.command else "").find("prestart") != -1 or (
        service.command is not None and "prestart" in " ".join(service.command.value)
    ):
        kind = "Job (pre-deploy / init hook)"
        rationale = "Runs migrations and seeding then exits; a run-once workload, not long-running."
        unresolved = ["backoffLimit", "CPU/memory"]
    elif image_key == "adminer":
        kind = "Deployment + ClusterIP Service (optional admin tool)"
        rationale = "Optional developer/admin UI; deploy only if needed, keep internal."
        unresolved = ["whether to deploy at all", "replica count", "CPU/memory"]
    elif component.runtime == "Nginx (static assets)":
        kind = "Deployment + ClusterIP Service (static assets via Nginx)"
        rationale = "Stateless static-asset server; horizontally scalable."
        unresolved = ["replica count", "CPU/memory"]
    else:
        kind = "Deployment + ClusterIP Service"
        rationale = "Stateless HTTP application; horizontally scalable behind a Service."
        unresolved = ["replica count", "CPU/memory"]

    component.workload_candidate = kind
    result.workload_mappings.append(
        WorkloadMapping(
            component=name,
            kubernetes_kind=kind,
            confidence="derived",
            rationale=rationale,
            evidence=base_ev,
            unresolved=unresolved,
        )
    )


# --------------------------------------------------------------------------- #
# Cross-cutting analysis
# --------------------------------------------------------------------------- #
def _analyze_config_and_secrets(result: AnalysisResult, dotenvs: dict[str, DotenvFile]) -> None:
    dotenv = _primary_dotenv(dotenvs)
    if dotenv is None:
        return
    for entry in dotenv.entries:
        ev = [
            Evidence(
                path=dotenv.path,
                selector=entry.name,
                symbol="env",
                start_line=entry.line,
                end_line=entry.line,
            )
        ]
        if is_secret(entry.name):
            result.secrets.append(
                Finding(
                    subject=f"secret.{entry.name}",
                    value="<redacted>",
                    confidence="explicit",
                    kubernetes_effect="Kubernetes Secret key candidate",
                    evidence=ev,
                )
            )
            if entry.value.lower() in _PLACEHOLDER_VALUES:
                result.warnings.append(
                    Warning(
                        code="placeholder_secret",
                        message=f"{entry.name} uses a placeholder value; must be overridden before deploy",
                        path=dotenv.path,
                    )
                )
        else:
            result.configuration.append(
                Finding(
                    subject=f"config.{entry.name}",
                    value="" if entry.is_empty else entry.value,
                    confidence="explicit",
                    kubernetes_effect="ConfigMap key candidate",
                    evidence=ev,
                )
            )


def _analyze_startup(
    result: AnalysisResult,
    compose: ComposeFile,
    compose_path: str,
    inventory: Inventory,
    shell_scripts: dict[str, list[str]],
) -> None:
    order: list[str] = []

    # DB readiness gates dependents (depends_on condition service_healthy).
    for service in compose.services:
        for dep in service.depends_on:
            if isinstance(dep.value, dict) and dep.value.get("condition") == "service_healthy":
                result.startup_order.append(
                    Finding(
                        subject=f"{service.name}.waits_for.{dep.value['service']}",
                        value="service_healthy",
                        confidence="explicit",
                        kubernetes_effect="ordering: gate via initContainer/readiness on the dependency",
                        evidence=[_ev(dep, compose_path)],
                    )
                )
    if any(_has_db_service(compose)):
        order.append("database becomes ready")

    # Prestart / migration steps from the init shell script.
    for rel, lines in sorted(shell_scripts.items()):
        for offset, raw in enumerate(lines):
            text = raw.strip()
            line_no = offset + 1
            if "alembic" in text and "upgrade" in text:
                order.append("run DB migrations")
                result.startup_order.append(
                    Finding(
                        subject="startup.migration",
                        value=text,
                        confidence="explicit",
                        kubernetes_effect="run as a pre-deploy Job / initContainer before app starts",
                        evidence=[Evidence(path=rel, selector="alembic upgrade", symbol="shell", start_line=line_no, end_line=line_no)],
                    )
                )
            elif "initial_data" in text or "init_data" in text or "seed" in text:
                order.append("create initial data")
                result.startup_order.append(
                    Finding(
                        subject="startup.initial_data",
                        value=text,
                        confidence="explicit",
                        kubernetes_effect="run once after migrations (same Job), before serving traffic",
                        evidence=[Evidence(path=rel, selector="initial data", symbol="shell", start_line=line_no, end_line=line_no)],
                    )
                )

    # Backend waits for prestart completion.
    for service in compose.services:
        for dep in service.depends_on:
            if isinstance(dep.value, dict) and dep.value.get("condition") == "service_completed_successfully":
                order.append(f"{service.name} starts")
                result.startup_order.append(
                    Finding(
                        subject=f"{service.name}.waits_for.{dep.value['service']}",
                        value="service_completed_successfully",
                        confidence="explicit",
                        kubernetes_effect="app Deployment must start only after the init Job completes",
                        evidence=[_ev(dep, compose_path)],
                    )
                )

    if order:
        result.startup_order.insert(
            0,
            Finding(
                subject="startup.order",
                value=_dedupe(order),
                confidence="derived",
                kubernetes_effect="overall ordering: DB -> migration Job -> seed -> application Deployments",
                evidence=[],
            ),
        )


def _emit_operational_unresolved(result: AnalysisResult, *, has_db: bool) -> None:
    items = [
        Unresolved(
            subject="replica_count",
            reason="desired availability/throughput is an operational decision, not in the repo",
            needed_input="target replicas per Deployment (SLO / load expectations)",
            kubernetes_effect="Deployment.spec.replicas",
        ),
        Unresolved(
            subject="resource_requests_limits",
            reason="repo contains no CPU/memory sizing information",
            needed_input="measured or estimated CPU/memory per component",
            kubernetes_effect="container resources.requests / resources.limits",
        ),
        Unresolved(
            subject="ingress_class",
            reason="cluster ingress controller is environment-specific and not declared in the repo",
            needed_input="target IngressClass in the destination cluster",
            kubernetes_effect="Ingress.spec.ingressClassName",
        ),
        Unresolved(
            subject="horizontal_pod_autoscaler",
            reason="no scaling policy is expressed in the repo",
            needed_input="scaling metric and min/max replicas",
            kubernetes_effect="HorizontalPodAutoscaler",
        ),
        Unresolved(
            subject="pod_disruption_budget",
            reason="availability tolerance during disruptions is an operational decision",
            needed_input="minAvailable/maxUnavailable policy",
            kubernetes_effect="PodDisruptionBudget",
        ),
    ]
    if has_db:
        items.extend(
            [
                Unresolved(
                    subject="pvc_size",
                    reason="database volume size is not declared in the repo",
                    needed_input="expected data volume / growth for the database PVC",
                    kubernetes_effect="PersistentVolumeClaim.spec.resources.requests.storage",
                ),
                Unresolved(
                    subject="storage_class",
                    reason="storage backend is cluster-specific",
                    needed_input="target StorageClass in the destination cluster",
                    kubernetes_effect="PersistentVolumeClaim.spec.storageClassName",
                ),
                Unresolved(
                    subject="database_ha_and_backup",
                    reason="repo runs a single-container DB; HA and backup are operational policy",
                    needed_input="managed DB vs in-cluster HA, and backup/restore policy",
                    kubernetes_effect="operator/StatefulSet topology, backup CronJobs",
                ),
            ]
        )
    result.unresolved_operational_inputs.extend(items)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _collect_unsupported(
    result: AnalysisResult,
    compose: ComposeFile | None,
    dockerfiles: dict[str, Dockerfile],
    dotenvs: dict[str, DotenvFile],
    nginx: dict[str, NginxConfig],
    settings: dict[str, PythonSettings],
) -> None:
    def add(path: str, issues: list) -> None:
        for issue in issues:
            result.unsupported_constructs.append(
                UnsupportedConstruct(path=path, construct_type=issue.construct, detail=issue.detail)
            )

    if compose is not None:
        add(compose.path, compose.issues)
    for df in dockerfiles.values():
        add(df.path, df.issues)
    for env in dotenvs.values():
        add(env.path, env.issues)
    for cfg in nginx.values():
        add(cfg.path, cfg.issues)
    for st in settings.values():
        add(st.path, st.issues)
    result.unsupported_constructs.sort(key=lambda u: (u.path, u.construct_type, u.detail))


def _warn_extra_compose(result: AnalysisResult, inventory: Inventory) -> None:
    for extra in inventory.compose_extra:
        result.warnings.append(
            Warning(
                code="compose_override_not_merged",
                message="additional compose file detected but NOT merged in kubernetes-p0; analysis is based on the primary compose file",
                path=extra,
            )
        )


def _main_nginx(nginx: dict[str, NginxConfig]) -> tuple[str, NginxConfig] | None:
    candidates = [(path, cfg) for path, cfg in nginx.items() if cfg.find("listen")]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0].rsplit("/", 1)[-1] != "nginx.conf", item[0]))
    return candidates[0]


def _primary_dotenv(dotenvs: dict[str, DotenvFile]) -> DotenvFile | None:
    if not dotenvs:
        return None
    for path, env in sorted(dotenvs.items()):
        if path.rsplit("/", 1)[-1] == ".env":
            return env
    return sorted(dotenvs.items())[0][1]


def _has_db(compose: ComposeFile) -> bool:
    return any(_has_db_service(compose))


def _has_db_service(compose: ComposeFile) -> list[bool]:
    flags: list[bool] = []
    for service in compose.services:
        if service.image is None:
            continue
        key = str(service.image.value).split(":", 1)[0].split("/")[-1].lower()
        flags.append(key in _DB_IMAGE_RUNTIMES)
    return [f for f in flags if f]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
