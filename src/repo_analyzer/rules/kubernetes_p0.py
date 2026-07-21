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
    AnswerBasis,
    Component,
    Evidence,
    ExposureCandidate,
    Finding,
    ImageBuildProfile,
    KubernetesObjectCandidate,
    MigrationQuestionAnswer,
    ProbeCandidateProfile,
    RepositoryMetadata,
    RuntimeDeploymentProfile,
    SourceCoverage,
    Unresolved,
    UnsupportedConstruct,
    Warning,
    WorkloadMapping,
    WorkloadProfile,
)
from ..models import DetectedFile
from ..parsers.common import Located
from ..parsers.compose import ComposeFile, ComposeService
from ..parsers.dockerfile import Dockerfile, exec_form
from ..parsers.dotenv import DotenvFile
from ..parsers.gradle import GradleBuild
from ..parsers.kubernetes_yaml import KubernetesManifest
from ..parsers.maven import MavenProject
from ..parsers.nginx import NginxConfig
from ..parsers.python_settings import PythonSettings
from ..parsers.readme import ReadmeFile
from ..parsers.spring_properties import SpringProperties
from ..parsers.spring_xml import SpringContext
from ..parsers.sql_init import SqlInitScript
from ..parsers.webxml import WebApp
from .build_system import emit_build_system_findings, resolve_build_system
from .java_webapp import analyze_java_webapp
from .spring_boot import analyze_spring_boot

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

# Substrings (case-insensitive) that mark a name as *metadata about* a secret
# (its expiry/rotation policy, length, or a boolean toggle) rather than the
# secret value itself. Such names carry a non-sensitive scalar and must not be
# classified as Secret candidates, even when they contain a secret substring
# (e.g. JWT_RESET_PASSWORD_EXPIRATION_MINUTES=10).
_SECRET_NEGATIVE_PATTERNS = (
    "EXPIRATION",
    "EXPIRE",
    "EXPIRY",
    "_TTL",
    "TIMEOUT",
    "_MINUTES",
    "_SECONDS",
    "_DAYS",
    "_HOURS",
    "_LENGTH",
    "_ROTATION",
    "_ENABLED",
    "_ALGORITHM",
)

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
    if not any(pattern in upper for pattern in _SECRET_PATTERNS):
        return False
    if any(pattern in upper for pattern in _SECRET_NEGATIVE_PATTERNS):
        return False
    return True


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


def _is_worker_command(command: list[str] | None) -> bool:
    """True when the command runs a background queue worker (Celery/taskiq/arq/
    dramatiq/rq). Such a process consumes a broker and exposes no inbound port,
    so it maps to a Deployment with NO Service. `celery beat`/`flower` (scheduler/
    UI) are deliberately excluded — only the `worker` role matches for Celery."""

    if not command:
        return False
    tokens = [t.lower() for t in command]
    if "celery" in tokens and "worker" in tokens:
        return True
    if "taskiq" in tokens and "worker" in tokens:
        return True
    if "dramatiq" in tokens:
        return True
    if "arq" in tokens:
        return True
    if "rq" in tokens and "worker" in tokens:
        return True
    return False


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


def _select_gradle_module(gradles: dict[str, GradleBuild]) -> str:
    """Pick the deployable Gradle module: the one applying the Spring Boot plugin
    (multi-module repos keep the app in a submodule, e.g. ``api/``, not root),
    else the shortest-path build script."""

    boot_modules = [
        path
        for path, build in gradles.items()
        if any(pl.id.startswith("org.springframework.boot") for pl in build.plugins)
    ]
    pool = boot_modules or list(gradles)
    return sorted(pool, key=lambda p: (p.count("/"), p))[0]


def analyze_kubernetes_p0(
    *,
    repo_name: str,
    profile: str,
    git_ref: str | None,
    build_system: str = "auto",
    inventory: Inventory,
    compose: ComposeFile | None,
    dockerfiles: dict[str, Dockerfile],
    dotenvs: dict[str, DotenvFile],
    nginx: dict[str, NginxConfig],
    settings: dict[str, PythonSettings],
    shell_scripts: dict[str, list[str]],
    mavens: dict[str, MavenProject] | None = None,
    gradles: dict[str, GradleBuild] | None = None,
    spring_props: dict[str, SpringProperties] | None = None,
    sql_inits: dict[str, SqlInitScript] | None = None,
    webapps: dict[str, WebApp] | None = None,
    kubernetes_manifests: dict[str, KubernetesManifest] | None = None,
    springs: dict[str, SpringContext] | None = None,
    readmes: dict[str, list[str]] | None = None,
    readme_facts: dict[str, ReadmeFile] | None = None,
    env_usage: dict[str, list[tuple[str, int]]],
) -> AnalysisResult:
    mavens = mavens or {}
    gradles = gradles or {}
    spring_props = spring_props or {}
    sql_inits = sql_inits or {}
    webapps = webapps or {}
    kubernetes_manifests = kubernetes_manifests or {}
    springs = springs or {}
    readmes = readmes or {}
    readme_facts = readme_facts or {}

    result = AnalysisResult(
        repository=RepositoryMetadata(
            name=repo_name,
            profile=profile,
            git_ref=git_ref,
            file_count=len(inventory.detected),
        ),
        detected_files=inventory.detected,
    )

    _emit_source_coverage(result, inventory, readmes)
    _collect_unsupported(result, compose, dockerfiles, dotenvs, nginx, settings)
    _collect_spring_unsupported(result, gradles, spring_props)
    _register_spring_detected(result, springs)
    _warn_extra_compose(result, inventory)
    _emit_kubernetes_manifest_findings(result, kubernetes_manifests)

    # No deployment compose and no Java build system. If a Dockerfile exists,
    # synthesize a component from it (image/port/config); otherwise honestly
    # report the absence and stop.
    if compose is None and not mavens and not gradles:
        if dockerfiles:
            _analyze_dockerfile_component(result, repo_name, dockerfiles)
            _analyze_config_and_secrets(result, dotenvs)
            _emit_alembic_init(result, inventory)
            _emit_operational_unresolved(result, has_db=False)
            return _finalize_result(result)
        result.warnings.append(
            Warning(code="no_compose", message="no compose file found; component topology unavailable")
        )
        _emit_operational_unresolved(result, has_db=False)
        return _finalize_result(result)

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
        _emit_compose_image_facts(result, dockerfiles)

    # Java build path: pick the build system deliberately (never "first pom.xml").
    selection, bs_warnings = resolve_build_system(
        requested=build_system, gradles=gradles, mavens=mavens
    )
    result.warnings.extend(bs_warnings)
    if selection is not None:
        emit_build_system_findings(result, selection)
        if selection.selected == "gradle":
            gradle_path = _select_gradle_module(gradles)
            analyze_spring_boot(
                result=result,
                inventory=inventory,
                compose=compose,
                compose_path=compose_path,
                gradle=gradles[gradle_path],
                gradle_path=gradle_path,
                spring_props=spring_props,
                sql_inits=sql_inits,
                dockerfiles=dockerfiles,
                readmes=readmes,
                readme_facts=readme_facts,
            )
        elif selection.selected == "maven":
            analyze_java_webapp(
                result=result,
                inventory=inventory,
                compose=compose,
                compose_path=compose_path,
                dockerfiles=dockerfiles,
                mavens=mavens,
                webapps=webapps,
                springs=springs,
                spring_props=spring_props,
                readmes=readmes,
            )

    has_db = _has_db(compose) if compose is not None else False
    _emit_operational_unresolved(result, has_db=has_db)
    return _finalize_result(result)


def _finalize_result(result: AnalysisResult) -> AnalysisResult:
    _emit_source_conflict_warnings(result)
    _emit_workload_profiles(result)
    _emit_migration_questions(result)
    return result


def _emit_workload_profiles(result: AnalysisResult) -> None:
    """Project existing component facts into provenance-bearing profiles."""

    mappings = {mapping.component: mapping for mapping in result.workload_mappings}
    profile_count = len(result.components)
    result.workload_profiles = [
        _workload_profile(component, mappings.get(component.name), result, profile_count)
        for component in result.components
    ]


def _workload_profile(
    component: Component,
    mapping: WorkloadMapping | None,
    result: AnalysisResult,
    profile_count: int,
) -> WorkloadProfile:
    mapping_evidence = list(mapping.evidence) if mapping else []
    component_findings = _component_findings(component, result)
    dockerfile_evidence = _dockerfile_evidence(component, result.container_image)

    image_evidence = _dedupe_evidence(mapping_evidence + dockerfile_evidence)
    runtime_evidence = _dedupe_evidence(
        mapping_evidence
        + _finding_evidence(component_findings["networking"])
        + _finding_evidence(component_findings["health"])
        + _finding_evidence(component_findings["storage"])
        + _finding_evidence(component_findings["configuration"])
        + _finding_evidence(component_findings["secrets"])
    )
    image_unresolved = list(mapping.unresolved) if mapping else []
    runtime_unresolved = _dedupe(component.unresolved + (mapping.unresolved if mapping else []))

    image_profile = ImageBuildProfile(
        build_tool=component.build_tool,
        build_command=component.build_command,
        build_context=component.build_context,
        dockerfile=component.dockerfile,
        build_args=list(component.build_args),
        build_artifact=component.build_artifact,
        packaging=component.packaging,
        image=component.image,
        base_image=_base_image_for_component(component, result.container_image, profile_count),
        image_source="local_build" if component.build_context or component.dockerfile else None,
        evidence=image_evidence,
        unresolved=image_unresolved,
    )
    runtime_profile = RuntimeDeploymentProfile(
        runtime=component.runtime,
        language=component.language,
        frameworks=list(component.frameworks),
        application_server=component.application_server,
        command=list(component.command) if component.command is not None else None,
        workers=component.workers,
        container_ports=list(component.container_ports),
        published_ports=list(component.published_ports),
        context_path=component.context_path,
        environment=list(component.environment),
        configmap_candidates=[
            name for name in component.environment if name not in component.secret_candidates
        ],
        secret_candidates=list(component.secret_candidates),
        volumes=list(component.volumes),
        exposure_candidates=_exposure_candidates(component, component_findings["networking"], mapping_evidence),
        probe_candidates=_probe_candidates(component, component_findings["health"], mapping_evidence),
        kubernetes_candidates=_kubernetes_candidates(
            component, mapping, component_findings, mapping_evidence
        ),
        relationships=[],
        evidence=runtime_evidence,
        unresolved=runtime_unresolved,
    )
    return WorkloadProfile(
        name=component.name,
        role=component.workload_candidate or None,
        source_files=list(component.source_files),
        image_build_profile=image_profile,
        runtime_deployment_profile=runtime_profile,
    )


def _component_findings(component: Component, result: AnalysisResult) -> dict[str, list[Finding]]:
    prefix = f"{component.name}."
    single_component = len(result.components) == 1

    def is_component_health_finding(finding: Finding) -> bool:
        return finding.subject in {
            f"{component.name}.health_path",
            f"{component.name}.health_exec",
        }

    def is_generic_application_health_finding(finding: Finding) -> bool:
        return finding.subject in {"health.liveness_probe", "health.readiness_probe"}

    return {
        # Compose services share the compose file, so its path cannot establish
        # component ownership. Only a single-component result can safely own
        # unqualified application and service findings.
        "networking": [
            finding
            for finding in result.networking
            if finding.subject.startswith(prefix)
            or (single_component and finding.subject.startswith(("app.", "service.")))
        ],
        "health": [
            finding
            for finding in result.health_checks
            if is_component_health_finding(finding)
            or (single_component and is_generic_application_health_finding(finding))
        ],
        "storage": [finding for finding in result.storage if finding.subject.startswith(prefix)],
        "configuration": [
            finding
            for finding in result.configuration
            if finding.subject.removeprefix("config.") in component.environment
        ],
        "secrets": [
            finding
            for finding in result.secrets
            if finding.subject.removeprefix("secret.") in component.secret_candidates
        ],
    }


def _dockerfile_evidence(component: Component, findings: list[Finding]) -> list[Evidence]:
    if component.dockerfile is None:
        return []
    return _finding_evidence(
        [finding for finding in findings if any(ev.path == component.dockerfile for ev in finding.evidence)]
    )


def _base_image_for_component(
    component: Component, findings: list[Finding], profile_count: int
) -> str | None:
    for finding in findings:
        if finding.subject != "image.base" or not isinstance(finding.value, str):
            continue
        if profile_count == 1 or (
            component.dockerfile is not None
            and any(evidence.path == component.dockerfile for evidence in finding.evidence)
        ):
            return finding.value
    return None


def _exposure_candidates(
    component: Component, networking: list[Finding], mapping_evidence: list[Evidence]
) -> list[ExposureCandidate]:
    candidates: list[ExposureCandidate] = []
    service_candidate = _service_candidate_allowed(component)
    for port in component.container_ports:
        finding = next(
            (
                finding
                for subject in (
                    f"{component.name}.container_port",
                    "app.server_port",
                    "app.default_port",
                    "service.target_port",
                )
                for finding in networking
                if finding.subject == subject and finding.value == port
            ),
            None,
        )
        evidence = list(finding.evidence) if finding else list(mapping_evidence)
        candidates.append(
            ExposureCandidate(
                port=port,
                source="container_port",
                evidence_type=_evidence_type(evidence, "component_source"),
                confidence=finding.confidence if finding else "derived",
                service_candidate=service_candidate,
                description=f"{component.name} container port candidate",
                evidence=evidence,
            )
        )
    for published in component.published_ports:
        port = _published_port_number(published)
        if port is None:
            continue
        candidates.append(
            ExposureCandidate(
                port=port,
                source="published_port",
                evidence_type="compose_port",
                confidence="explicit",
                service_candidate=service_candidate,
                description=f"{component.name} published compose port candidate",
                evidence=list(mapping_evidence),
            )
        )
    return candidates


def _probe_candidates(
    component: Component, health_checks: list[Finding], mapping_evidence: list[Evidence]
) -> list[ProbeCandidateProfile]:
    candidates: list[ProbeCandidateProfile] = []
    for finding in health_checks:
        probe_type = "liveness" if "liveness" in finding.subject else "readiness"
        candidates.append(
            ProbeCandidateProfile(
                probe_type=probe_type,
                value=str(finding.value),
                evidence_type=_evidence_type(finding.evidence, "compose_healthcheck"),
                confidence=finding.confidence,
                evidence=list(finding.evidence),
            )
        )
    if not candidates and component.healthcheck is not None:
        candidates.append(
            ProbeCandidateProfile(
                probe_type="readiness",
                value=component.healthcheck,
                evidence_type="component_source",
                confidence="derived",
                evidence=list(mapping_evidence),
            )
        )
    return candidates


def _kubernetes_candidates(
    component: Component,
    mapping: WorkloadMapping | None,
    findings: dict[str, list[Finding]],
    mapping_evidence: list[Evidence],
) -> list[KubernetesObjectCandidate]:
    candidates: list[KubernetesObjectCandidate] = []
    kind_text = mapping.kubernetes_kind if mapping else component.workload_candidate
    confidence = mapping.confidence if mapping else "derived"
    rationale = mapping.rationale if mapping else "component workload candidate"
    if "StatefulSet" in kind_text:
        candidates.append(_kubernetes_candidate("StatefulSet", "workload_controller", "component_source", confidence, rationale, mapping_evidence))
    elif kind_text.startswith("Job"):
        candidates.append(_kubernetes_candidate("Job", "workload_controller", "component_source", confidence, rationale, mapping_evidence))
    elif "Deployment" in kind_text:
        candidates.append(_kubernetes_candidate("Deployment", "workload_controller", "component_source", confidence, rationale, mapping_evidence))

    if "Service" in kind_text and "no service" not in kind_text.lower() and _service_candidate_allowed(component):
        evidence = _finding_evidence(findings["networking"]) or mapping_evidence
        candidates.append(_kubernetes_candidate("Service", "companion_object", _evidence_type(evidence, "component_source"), confidence, "inbound port evidence supports a Service candidate", evidence))
    for finding in findings["storage"]:
        if finding.subject.endswith("persistent_volume"):
            candidates.append(_kubernetes_candidate("PVC", "companion_object", "compose_volume", finding.confidence, "persistent compose volume requires a PVC candidate", finding.evidence))
            break
    config_names = [name for name in component.environment if name not in component.secret_candidates]
    if config_names:
        evidence = _finding_evidence(findings["configuration"]) or mapping_evidence
        candidates.append(_kubernetes_candidate("ConfigMap", "companion_object", "configuration_reference", "derived", "non-secret environment entries are ConfigMap key candidates", evidence))
    if component.secret_candidates:
        evidence = _finding_evidence(findings["secrets"]) or mapping_evidence
        candidates.append(_kubernetes_candidate("Secret", "companion_object", "configuration_reference", "derived", "secret-like environment entries are Secret key candidates", evidence))
    for finding in findings["networking"]:
        if finding.subject.endswith("ingress_host"):
            candidates.append(_kubernetes_candidate("Ingress", "companion_object", "component_source", finding.confidence, "repository routing host is an Ingress candidate", finding.evidence))
            break
    return candidates


def _kubernetes_candidate(
    kind: str,
    candidate_role: str,
    evidence_type: str,
    confidence: str,
    rationale: str,
    evidence: list[Evidence],
) -> KubernetesObjectCandidate:
    return KubernetesObjectCandidate(
        kind=kind,
        candidate_role=candidate_role,
        evidence_type=evidence_type,
        confidence=confidence,
        rationale=rationale,
        evidence=list(evidence),
    )


def _service_candidate_allowed(component: Component) -> bool:
    workload = component.workload_candidate.lower()
    return not (
        workload.startswith("job")
        or "prestart" in workload
        or (_is_worker_command(component.command) and not component.container_ports)
    )


def _published_port_number(spec: str) -> int | None:
    segments = spec.split("/", 1)[0].split(":")
    token = segments[-2] if len(segments) > 1 else segments[-1]
    return int(token) if token.isdigit() else None


def _evidence_type(evidence: list[Evidence], fallback: str) -> str:
    if any(e.path.endswith(("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")) for e in evidence):
        return "compose_port" if fallback == "component_source" else fallback
    return fallback


def _finding_evidence(findings: list[Finding]) -> list[Evidence]:
    return [evidence for finding in findings for evidence in finding.evidence]


def _dedupe_evidence(evidence: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, str, str | None, int, int]] = set()
    deduped: list[Evidence] = []
    for item in evidence:
        key = (item.path, item.selector, item.symbol, item.start_line, item.end_line)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


_MIGRATION_QUESTIONS = [
    ("application_identity", "어떤 애플리케이션인가?"),
    ("build_and_run", "어떻게 빌드하고 실행하는가?"),
    ("ports_and_services", "어떤 Port와 Service가 필요한가?"),
    ("external_dependencies", "어떤 외부 의존성이 있는가?"),
    ("configmaps_and_secrets", "어떤 ConfigMap과 Secret이 필요한가?"),
    ("persistent_data", "어떤 데이터가 영속되어야 하는가?"),
    ("repository_unknowns", "Repository만으로 결정할 수 없는 값은 무엇인가?"),
]


def _basis(source_section: str, subject: str, evidence: list[Evidence] | None = None) -> AnswerBasis:
    return AnswerBasis(source_section=source_section, subject=subject, evidence=evidence or [])


def _emit_migration_questions(result: AnalysisResult) -> None:
    result.migration_questions = [
        _question_application_identity(result),
        _question_build_and_run(result),
        _question_ports_and_services(result),
        _question_external_dependencies(result),
        _question_configmaps_and_secrets(result),
        _question_persistent_data(result),
        _question_repository_unknowns(result),
    ]


def _question_application_identity(result: AnalysisResult) -> MigrationQuestionAnswer:
    question = _MIGRATION_QUESTIONS[0][1]
    if not result.components:
        return MigrationQuestionAnswer(
            id="application_identity",
            question=question,
            status="not_detected",
            answer="No deployable application component was detected from repository facts.",
            missing=["deployable build file, Dockerfile, Compose service, or web application descriptor"],
        )
    answer = "; ".join(
        f"{component.name}: {component.runtime or component.language or 'runtime not detected'}"
        for component in result.components
    )
    has_runtime = any(component.runtime or component.language for component in result.components)
    return MigrationQuestionAnswer(
        id="application_identity",
        question=question,
        status="answered" if has_runtime else "partial",
        answer=answer,
        basis=[_basis("components", component.name) for component in result.components],
        missing=[] if has_runtime else ["application runtime/framework summary"],
    )


def _question_build_and_run(result: AnalysisResult) -> MigrationQuestionAnswer:
    question = _MIGRATION_QUESTIONS[1][1]
    parts: list[str] = []
    basis: list[AnswerBasis] = []
    missing: list[str] = []
    build_findings = [
        finding
        for finding in result.configuration
        if finding.subject.startswith("build.")
        or finding.subject.startswith("runtime.")
        or finding.subject.startswith("profile.")
    ]
    image_findings = [
        finding
        for finding in result.container_image
        if finding.subject in {"image.dockerfile", "image.build_command", "image.start_command", "image.base"}
    ]
    for component in result.components:
        bits: list[str] = []
        if component.build_tool:
            bits.append(component.build_tool)
        if component.build_command:
            bits.append(f"build `{component.build_command}`")
        if component.command:
            bits.append(f"run `{' '.join(component.command)}`")
        if component.dockerfile:
            bits.append(f"Dockerfile `{component.dockerfile}`")
        if bits:
            parts.append(f"{component.name}: {', '.join(bits)}")
            basis.append(_basis("components", component.name))
        else:
            missing.append(f"{component.name} build/run command")
    status = "answered" if parts and not missing else ("partial" if parts else "unresolved")
    return MigrationQuestionAnswer(
        id="build_and_run",
        question=question,
        status=status,
        answer="; ".join(parts) if parts else "Build and run commands were not detected.",
        basis=basis
        + [_basis("configuration", finding.subject, finding.evidence) for finding in build_findings]
        + [_basis("container_image", finding.subject, finding.evidence) for finding in image_findings],
        missing=missing or (["build file, Dockerfile, Compose command, or README run command"] if not parts else []),
    )


def _question_ports_and_services(result: AnalysisResult) -> MigrationQuestionAnswer:
    question = _MIGRATION_QUESTIONS[2][1]
    findings = [
        finding
        for finding in result.networking
        if "port" in finding.subject.lower() or "context_path" in finding.subject
    ]
    parts = [
        f"{component.name} targetPort {', '.join(str(port) for port in component.container_ports)}"
        for component in result.components
        if component.container_ports
    ]
    if result.workload_mappings:
        parts.append(
            "; ".join(
                f"{mapping.component} -> {mapping.kubernetes_kind}"
                for mapping in result.workload_mappings
            )
        )
    if findings:
        parts.extend(f"{finding.subject}: {finding.value}" for finding in findings if finding.subject.startswith("k8s."))
    missing = [] if parts else ["container port or Service targetPort"]
    status = "answered" if parts and not missing else ("partial" if parts else "unresolved")
    return MigrationQuestionAnswer(
        id="ports_and_services",
        question=question,
        status=status,
        answer="; ".join(parts) if parts else "No port or Service candidate was detected.",
        basis=[_basis("networking", finding.subject, finding.evidence) for finding in findings]
        + [_basis("workload_mappings", mapping.component, mapping.evidence) for mapping in result.workload_mappings],
        missing=missing,
    )


def _question_external_dependencies(result: AnalysisResult) -> MigrationQuestionAnswer:
    question = _MIGRATION_QUESTIONS[3][1]
    if not result.runtime_dependencies:
        return MigrationQuestionAnswer(
            id="external_dependencies",
            question=question,
            status="not_detected",
            answer="No external runtime dependency was detected.",
            missing=["external service evidence may be absent from scanned file classes"],
        )
    return MigrationQuestionAnswer(
        id="external_dependencies",
        question=question,
        status="answered",
        answer="; ".join(f"{finding.subject}: {finding.value}" for finding in result.runtime_dependencies),
        basis=[
            _basis("runtime_dependencies", finding.subject, finding.evidence)
            for finding in result.runtime_dependencies
        ],
    )


def _question_configmaps_and_secrets(result: AnalysisResult) -> MigrationQuestionAnswer:
    question = _MIGRATION_QUESTIONS[4][1]
    config = [
        finding
        for finding in result.configuration
        if "ConfigMap key candidate" in finding.kubernetes_effect
        or finding.subject.startswith("k8s.configmap_ref.")
    ]
    secrets = result.secrets
    if not config and not secrets:
        return MigrationQuestionAnswer(
            id="configmaps_and_secrets",
            question=question,
            status="not_detected",
            answer="No ConfigMap or Secret candidates were detected.",
            missing=["ConfigMap/Secret candidates were not detected in scanned repository facts"],
        )
    return MigrationQuestionAnswer(
        id="configmaps_and_secrets",
        question=question,
        status="answered",
        answer=f"ConfigMap candidates: {len(config)}; Secret candidates: {len(secrets)}",
        basis=[_basis("configuration", finding.subject, finding.evidence) for finding in config]
        + [_basis("secrets", finding.subject, finding.evidence) for finding in secrets],
    )


def _question_persistent_data(result: AnalysisResult) -> MigrationQuestionAnswer:
    question = _MIGRATION_QUESTIONS[5][1]
    db_deps = [
        finding
        for finding in result.runtime_dependencies
        if "database" in finding.subject.lower()
    ]
    basis = [_basis("storage", finding.subject, finding.evidence) for finding in result.storage]
    basis += [_basis("runtime_dependencies", finding.subject, finding.evidence) for finding in db_deps]
    if result.storage:
        return MigrationQuestionAnswer(
            id="persistent_data",
            question=question,
            status="answered",
            answer="; ".join(f"{finding.subject}: {finding.value}" for finding in result.storage),
            basis=basis,
        )
    if db_deps:
        answer = (
            "No application PVC was detected. Database state exists or is implied by runtime dependency: "
            + "; ".join(f"{finding.subject}: {finding.value}" for finding in db_deps)
        )
        return MigrationQuestionAnswer(
            id="persistent_data",
            question=question,
            status="partial",
            answer=answer,
            basis=basis,
            missing=["external database persistence decision or managed database policy"],
        )
    return MigrationQuestionAnswer(
        id="persistent_data",
        question=question,
        status="not_detected",
        answer="No application volume, database, or SQL persistence evidence was detected.",
        missing=["persistence evidence may be absent from scanned file classes"],
    )


def _question_repository_unknowns(result: AnalysisResult) -> MigrationQuestionAnswer:
    question = _MIGRATION_QUESTIONS[6][1]
    if not result.unresolved_operational_inputs:
        return MigrationQuestionAnswer(
            id="repository_unknowns",
            question=question,
            status="answered",
            answer="No unresolved operational input was recorded.",
            missing=["no unresolved operational inputs were recorded"],
        )
    return MigrationQuestionAnswer(
        id="repository_unknowns",
        question=question,
        status="answered",
        answer="; ".join(item.subject for item in result.unresolved_operational_inputs),
        basis=[
            _basis("unresolved_operational_inputs", item.subject)
            for item in result.unresolved_operational_inputs
        ],
        missing=[item.needed_input for item in result.unresolved_operational_inputs],
    )


def _emit_source_coverage(
    result: AnalysisResult, inventory: Inventory, readmes: dict[str, list[str]]
) -> None:
    def add(
        source_class: str,
        paths: list[str],
        detection: str,
        role: str = "primary",
        status: str | None = None,
    ) -> None:
        resolved_status = status or ("present" if paths else "missing")
        result.source_coverage.append(
            SourceCoverage(
                source_class=source_class,
                status=resolved_status,
                paths=sorted(paths),
                role=role,
                detection=detection,
            )
        )

    compose_paths = []
    if inventory.compose_primary:
        compose_paths.append(inventory.compose_primary)
    compose_paths.extend(inventory.compose_extra)
    selected_ignored = [
        path for path in inventory.compose_ignored if _path_referenced_by_readme(path, readmes)
    ]
    if compose_paths:
        add(
            "compose",
            compose_paths,
            "compose*.yml/yaml or docker-compose*.yml/yaml filename pattern",
        )
    elif selected_ignored:
        add(
            "compose",
            selected_ignored,
            "compose file under documentation/example path selected by README reference",
            role="selected_primary",
            status="present",
        )
    elif inventory.compose_ignored:
        add(
            "compose",
            inventory.compose_ignored,
            "compose filename pattern under documentation/example/test path",
            role="sample_or_documented_deployment",
            status="ignored",
        )
    else:
        add("compose", [], "compose filename pattern")

    add("dockerfile", inventory.dockerfiles, "Dockerfile, Dockerfile.*, or *.Dockerfile filename pattern")
    add(
        "app_config",
        inventory.spring_property_files + inventory.spring_yaml_files,
        "application*.properties/yml/yaml filename pattern",
    )
    add("sql", inventory.sql_init_files, ".sql extension plus SQL parser classification")
    add("kubernetes", inventory.kubernetes_yaml_files, "YAML apiVersion/kind content sniff")
    if inventory.skipped_large_candidates:
        add(
            "skipped_large_candidates",
            inventory.skipped_large_candidates,
            "candidate exceeded 10 MiB parse limit",
            role="supplemental",
            status="error",
        )
    add("web_xml", inventory.web_descriptors, "web.xml filename")
    add("build_file", inventory.maven_files + inventory.gradle_files, "pom.xml or build.gradle(.kts)")
    add("readme", inventory.readme_files, "README* filename")


def _path_referenced_by_readme(path: str, readmes: dict[str, list[str]]) -> bool:
    for lines in readmes.values():
        if any(path in line for line in lines):
            return True
    return False


def _emit_kubernetes_manifest_findings(
    result: AnalysisResult,
    kubernetes_manifests: dict[str, KubernetesManifest],
) -> None:
    for path, manifest in kubernetes_manifests.items():
        for resource in manifest.resources:
            name = resource.name.value if resource.name else "unnamed"
            if resource.kind.value == "Service":
                for port in resource.ports:
                    result.networking.append(
                        Finding(
                            subject=f"k8s.service_port.{name}",
                            value=port.value,
                            confidence="explicit",
                            kubernetes_effect="existing Kubernetes Service port evidence",
                            evidence=[
                                Evidence(
                                    path=path,
                                    selector=port.selector,
                                    symbol="k8s.service.port",
                                    start_line=port.start_line,
                                    end_line=port.end_line,
                                )
                            ],
                        )
                    )
            if resource.kind.value in {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}:
                for port in resource.ports:
                    result.networking.append(
                        Finding(
                            subject=f"k8s.container_port.{name}",
                            value=port.value,
                            confidence="explicit",
                            kubernetes_effect="existing Kubernetes workload container port evidence",
                            evidence=[
                                Evidence(
                                    path=path,
                                    selector=port.selector,
                                    symbol="k8s.container.port",
                                    start_line=port.start_line,
                                    end_line=port.end_line,
                                )
                            ],
                        )
                    )
            for ref in resource.configmap_refs:
                result.configuration.append(
                    Finding(
                        subject=f"k8s.configmap_ref.{ref.value}",
                        value=ref.value,
                        confidence="explicit",
                        kubernetes_effect="existing Kubernetes ConfigMap reference",
                        evidence=[
                            Evidence(
                                path=path,
                                selector=ref.selector,
                                symbol="k8s.configmap_ref",
                                start_line=ref.start_line,
                                end_line=ref.end_line,
                            )
                        ],
                    )
                )
            for ref in resource.secret_refs:
                result.secrets.append(
                    Finding(
                        subject=f"k8s.secret_ref.{ref.value}",
                        value=ref.value,
                        confidence="explicit",
                        kubernetes_effect="existing Kubernetes Secret reference",
                        evidence=[
                            Evidence(
                                path=path,
                                selector=ref.selector,
                                symbol="k8s.secret_ref",
                                start_line=ref.start_line,
                                end_line=ref.end_line,
                            )
                        ],
                    )
                )


def _emit_source_conflict_warnings(result: AnalysisResult) -> None:
    component_ports = {port for component in result.components for port in component.container_ports}
    manifest_ports = {
        int(f.value)
        for f in result.networking
        if f.subject.startswith("k8s.container_port.") and isinstance(f.value, int)
    }
    if component_ports and manifest_ports and component_ports.isdisjoint(manifest_ports):
        result.warnings.append(
            Warning(
                code="source_conflict",
                message=(
                    "Kubernetes manifest container ports do not match component/container port evidence; "
                    f"component ports={sorted(component_ports)}, manifest ports={sorted(manifest_ports)}"
                ),
                path=None,
            )
        )


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
    elif _is_worker_command(component.command) and not component.container_ports:
        kind = "Deployment (background worker; no Service)"
        rationale = (
            "Background queue worker (Celery/taskiq/arq-style): consumes a broker and exposes no "
            "inbound port, so it needs a Deployment but NO Service. Scale replicas for throughput; "
            "readiness is a process/broker-connection check, not an HTTP probe."
        )
        unresolved = ["replica count", "CPU/memory"]
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
# Compose-less discovery: synthesize a component from a Dockerfile
# --------------------------------------------------------------------------- #
_MIGRATION_TOKENS = ("alembic", "flyway", "liquibase", "migrate")


def _pick_primary_dockerfile(dockerfiles: dict[str, Dockerfile]) -> str:
    return sorted(dockerfiles, key=lambda p: (p.count("/"), p))[0]


def _root_base_image(df: Dockerfile) -> str | None:
    """Follow multi-stage ``FROM <alias>`` chains to the real root base image."""

    by_alias = {s.alias: s for s in df.stages if s.alias}
    stage = df.final_base_image
    seen: set[str] = set()
    while stage is not None and stage.image in by_alias and stage.image not in seen:
        seen.add(stage.image)
        stage = by_alias[stage.image]
    return stage.image if stage is not None else None


def _resolve_runtime_dockerfile(df: Dockerfile) -> str | None:
    base = (_root_base_image(df) or "").lower()
    cmd = df.last("CMD")
    argument = cmd.argument.lower() if cmd is not None else ""
    if base.startswith("nginx"):
        return "Nginx (static assets)"
    if "fastapi" in argument:
        return "FastAPI"
    if "uvicorn" in argument:
        return "Uvicorn (ASGI)"
    if "gunicorn" in argument:
        return "Gunicorn (WSGI)"
    if base.startswith("python"):
        return "Python"
    if base.startswith("node"):
        return "Node.js"
    return None


def _dockerfile_port(df: Dockerfile, rel: str) -> tuple[int | None, str, list[Evidence]]:
    for instr in df.find("EXPOSE"):
        tokens = instr.argument.split()
        token = tokens[0].split("/")[0] if tokens else ""
        if token.isdigit():
            return (
                int(token),
                "explicit",
                [Evidence(path=rel, selector="EXPOSE", symbol="EXPOSE", start_line=instr.start_line, end_line=instr.end_line)],
            )
    for name in ("CMD", "ENTRYPOINT"):
        instr = df.last(name)
        if instr is None:
            continue
        match = re.search(r"--port[=\s]+(\d+)", instr.argument)
        if match:
            return (
                int(match.group(1)),
                "derived",
                [Evidence(path=rel, selector=name, symbol=name, start_line=instr.start_line, end_line=instr.end_line)],
            )
    return None, "explicit", []


def _analyze_dockerfile_component(
    result: AnalysisResult, repo_name: str, dockerfiles: dict[str, Dockerfile]
) -> None:
    rel = _pick_primary_dockerfile(dockerfiles)
    df = dockerfiles[rel]
    context = rel.rsplit("/", 1)[0] if "/" in rel else ""
    name = (context.rsplit("/", 1)[-1] if context else repo_name) or "app"

    component = Component(name=name, workload_candidate="")
    component.source_files.append(rel)
    component.dockerfile = rel
    component.build_context = context or "."

    cmd = df.last("CMD")
    argv = exec_form(cmd.argument) if cmd is not None else None
    if argv is not None:
        component.command = argv
        component.workers = _parse_workers(argv)
    component.runtime = _resolve_runtime_dockerfile(df)

    port, confidence, port_ev = _dockerfile_port(df, rel)
    if port is not None:
        component.container_ports.append(port)
        result.networking.append(
            Finding(
                subject=f"{name}.container_port",
                value=port,
                confidence=confidence,
                kubernetes_effect=f"{name} Service targetPort candidate",
                evidence=port_ev,
            )
        )

    _emit_dockerfile_image(result, df, rel, component)

    kind = "Deployment + ClusterIP Service"
    component.workload_candidate = kind
    result.workload_mappings.append(
        WorkloadMapping(
            component=name,
            kubernetes_kind=kind,
            confidence="derived",
            rationale="Stateless application built from a Dockerfile (no compose); horizontally scalable behind a Service.",
            evidence=[Evidence(path=rel, selector="Dockerfile", symbol="Dockerfile", start_line=1, end_line=1)],
            unresolved=["replica count", "CPU/memory"],
        )
    )
    result.components.append(component)


def _emit_dockerfile_image(
    result: AnalysisResult, df: Dockerfile, rel: str, component: Component
) -> None:
    result.container_image.append(
        Finding(
            subject="image.dockerfile",
            value=rel,
            confidence="explicit",
            kubernetes_effect="the container image is built from this Dockerfile (build context = component dir)",
            evidence=[Evidence(path=rel, selector="Dockerfile", symbol="Dockerfile", start_line=1, end_line=1)],
        )
    )
    base = _root_base_image(df)
    from_instrs = df.find("FROM")
    if base and from_instrs:
        result.container_image.append(
            Finding(
                subject="image.base",
                value=base,
                confidence="explicit",
                kubernetes_effect="base image (informs runtime, CVE surface, non-root defaults)",
                evidence=[Evidence(path=rel, selector="FROM", symbol="FROM", start_line=from_instrs[0].start_line, end_line=from_instrs[0].end_line)],
            )
        )
    users = df.find("USER")
    if users:
        last_user = users[-1]
        tokens = last_user.argument.strip().split()
        value = tokens[0] if tokens else ""
        if value and value.lower() not in ("root", "0"):
            result.container_image.append(
                Finding(
                    subject="image.non_root",
                    value=value,
                    confidence="explicit",
                    kubernetes_effect="image runs as a non-root user; aligns with runAsNonRoot securityContext",
                    evidence=[Evidence(path=rel, selector="USER", symbol="USER", start_line=last_user.start_line, end_line=last_user.end_line)],
                )
            )
    aliases = [s.alias for s in df.stages if s.alias]
    if len(aliases) > 1:
        result.container_image.append(
            Finding(
                subject="image.build_targets",
                value=aliases,
                confidence="explicit",
                kubernetes_effect="multi-stage Dockerfile; the deployable image is the final target (build a specific stage with --target)",
                evidence=[Evidence(path=rel, selector="Dockerfile", symbol="stages", start_line=df.stages[0].start_line, end_line=df.stages[-1].start_line)],
            )
        )
    for instr in df.find("CMD"):
        if any(token in instr.argument.lower() for token in _MIGRATION_TOKENS):
            result.container_image.append(
                Finding(
                    subject="image.migration_target",
                    value=instr.argument.strip(),
                    confidence="derived",
                    kubernetes_effect="a build stage runs DB migrations; deploy it as a pre-deploy Job/initContainer, not as the app",
                    evidence=[Evidence(path=rel, selector="CMD", symbol="CMD", start_line=instr.start_line, end_line=instr.end_line)],
                )
            )
            break


def _emit_compose_image_facts(
    result: AnalysisResult, dockerfiles: dict[str, Dockerfile]
) -> None:
    """Mine container-image facts from the Dockerfile a compose service builds.

    The no-compose path already surfaces base image, non-root ``USER``,
    multi-stage targets and migration ``CMD`` via ``_emit_dockerfile_image``.
    Compose-driven components resolve a real Dockerfile too, so mine the same
    facts here. Dedupe by Dockerfile path so services that share one image
    (e.g. an app and its migration sidecar) emit a single set of findings.
    """
    seen: set[str] = set()
    for component in result.components:
        rel = component.dockerfile
        if not rel or rel in seen:
            continue
        df = dockerfiles.get(rel)
        if df is None:
            continue
        seen.add(rel)
        _emit_dockerfile_image(result, df, rel, component)


def _emit_alembic_init(result: AnalysisResult, inventory: Inventory) -> None:
    for rel in inventory.alembic_files:
        result.startup_order.append(
            Finding(
                subject="startup.migration",
                value="Alembic migrations (alembic upgrade head)",
                confidence="derived",
                kubernetes_effect="run as a pre-deploy Job or initContainer before the app starts; not the app's long-running process",
                evidence=[Evidence(path=rel, selector="alembic", symbol="alembic.ini", start_line=1, end_line=1)],
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


def _collect_spring_unsupported(
    result: AnalysisResult,
    gradles: dict[str, GradleBuild],
    spring_props: dict[str, SpringProperties],
) -> None:
    for build in gradles.values():
        for issue in build.issues:
            result.unsupported_constructs.append(
                UnsupportedConstruct(path=build.path, construct_type=issue.construct, detail=issue.detail)
            )
    # application*.properties AND application*.yml are parsed; any construct a parser
    # could not handle is surfaced via its own issues (never silently dropped).
    for props in spring_props.values():
        for issue in props.issues:
            result.unsupported_constructs.append(
                UnsupportedConstruct(path=props.path, construct_type=issue.construct, detail=issue.detail)
            )
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
    for ignored in inventory.compose_ignored:
        result.warnings.append(
            Warning(
                code="compose_non_deployment_path",
                message="compose file under a documentation/examples/test path is treated as a demo/sample, NOT the deployment topology; its services are not workloads",
                path=ignored,
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
