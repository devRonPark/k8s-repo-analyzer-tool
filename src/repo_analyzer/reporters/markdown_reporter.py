"""Workload-centric Markdown reporter.

Structured so an engineer new to the repository can answer the seven P0
migration questions. Content is derived entirely from the deterministic
``AnalysisResult``; the reporter invents nothing.
"""

from __future__ import annotations

from pathlib import Path

from ..models import AnalysisResult, Component, WorkloadProfile


def to_markdown(result: AnalysisResult) -> str:
    lines: list[str] = []
    out = lines.append
    repo = result.repository

    out(f"# Kubernetes P0 Analysis — {repo.name}")
    out("")
    out(f"- Profile: `{repo.profile}`")
    out(f"- Git ref: `{repo.git_ref}`" if repo.git_ref else "- Git ref: (not provided)")
    out(f"- Detected files: {repo.file_count}")
    out(f"- Schema version: {result.schema_version}")
    out("")

    if result.workload_profiles:
        _workload_profiles_section(out, result)
    else:
        _components_section(out, result)
    _workloads_section(out, result)
    _networking_section(out, result)
    _storage_section(out, result)
    _dependencies_section(out, result)
    _config_secret_section(out, result)
    _startup_section(out, result)
    _healthcheck_section(out, result)
    _buildtime_section(out, result)
    _image_section(out, result)
    _unresolved_section(out, result)
    _warnings_section(out, result)
    _migration_questions_section(out, result)

    return "\n".join(lines) + "\n"


def _fmt_evidence(evidence) -> str:
    parts = []
    for ev in evidence:
        loc = f"{ev.path}:{ev.start_line}-{ev.end_line}"
        parts.append(f"`{loc}` ({ev.selector})")
    return "; ".join(parts) if parts else "—"


def _components_section(out, result: AnalysisResult) -> None:
    out("## 1. Components")
    out("")
    if not result.components:
        out("_No components detected._")
        out("")
        return
    for comp in result.components:
        _component_block(out, comp)


def _workload_profiles_section(out, result: AnalysisResult) -> None:
    out("## 1. Workload profiles")
    out("")
    for profile in result.workload_profiles:
        _workload_profile_block(out, profile)


def _workload_profile_block(out, profile: WorkloadProfile) -> None:
    image = profile.image_build_profile
    runtime = profile.runtime_deployment_profile

    out(f"### {profile.name}")
    out("")
    if profile.role:
        out(f"- Role: {profile.role}")
    out(f"- Source files: {', '.join(f'`{path}`' for path in profile.source_files) or '—'}")
    out("")

    out("#### Image build profile")
    out("")
    image_facts = [
        ("Build tool", image.build_tool),
        ("Build command", image.build_command),
        ("Build context", image.build_context),
        ("Dockerfile", image.dockerfile),
        ("Build artifact", image.build_artifact),
        ("Packaging", image.packaging),
        ("Image", image.image),
        ("Base image", image.base_image),
        ("Builder image", image.builder_image),
        ("Image source", image.image_source),
        ("Build args", ", ".join(image.build_args) if image.build_args else None),
    ]
    _profile_facts(out, image_facts)
    _profile_evidence(out, image.evidence)
    out("")

    out("#### Runtime deployment profile")
    out("")
    runtime_facts = [
        ("Runtime", runtime.runtime),
        ("Language", runtime.language),
        ("Application server", runtime.application_server),
        ("Command", " ".join(runtime.command) if runtime.command else None),
        ("Workers", str(runtime.workers) if runtime.workers is not None else None),
        ("HTTP context path", runtime.context_path),
        ("Frameworks", ", ".join(runtime.frameworks) if runtime.frameworks else None),
        (
            "Container ports",
            ", ".join(str(port) for port in runtime.container_ports)
            if runtime.container_ports
            else None,
        ),
        ("Published ports", ", ".join(runtime.published_ports) if runtime.published_ports else None),
        ("Environment", ", ".join(runtime.environment) if runtime.environment else None),
        (
            "ConfigMap candidates",
            ", ".join(runtime.configmap_candidates) if runtime.configmap_candidates else None,
        ),
        (
            "Secret candidates",
            ", ".join(runtime.secret_candidates) if runtime.secret_candidates else None,
        ),
        ("Volumes", ", ".join(runtime.volumes) if runtime.volumes else None),
    ]
    _profile_facts(out, runtime_facts)
    _profile_evidence(out, runtime.evidence)
    out("")

    _profile_candidates_section(out, "Kubernetes workload controller candidates", runtime.kubernetes_candidates, "workload_controller")
    _profile_candidates_section(out, "Companion object candidates", runtime.kubernetes_candidates, "companion_object")

    out("#### Workload relationships")
    out("")
    if runtime.relationships:
        for relationship in runtime.relationships:
            out(
                f"- {relationship.source} -> {relationship.target}: {relationship.description} "
                f"({relationship.relationship_type}, {relationship.confidence})"
            )
    else:
        out("_No workload relationships detected in scanned repository facts._")
    out("")

    out("#### Unresolved decisions")
    out("")
    decisions = [
        *image.unresolved,
        *image.open_decisions,
        *runtime.unresolved,
        *runtime.open_decisions,
        *(
            decision
            for candidate in (
                *runtime.exposure_candidates,
                *runtime.probe_candidates,
                *runtime.kubernetes_candidates,
            )
            for decision in getattr(candidate, "open_decisions", ())
        ),
        *(decision for relationship in runtime.relationships for decision in relationship.open_decisions),
    ]
    decisions = list(dict.fromkeys(decisions))
    if decisions:
        for decision in decisions:
            out(f"- {decision}")
    else:
        out("_None recorded._")
    out("")


def _profile_facts(out, facts) -> None:
    emitted = False
    for label, value in facts:
        if value is not None:
            out(f"- {label}: `{value}`")
            emitted = True
    if not emitted:
        out("_No profile facts detected in scanned repository facts._")


def _profile_evidence(out, evidence) -> None:
    if evidence:
        out(f"- Evidence: {_fmt_evidence(evidence)}")


def _profile_candidates_section(out, heading: str, candidates, candidate_role: str) -> None:
    out(f"#### {heading}")
    out("")
    relevant = [candidate for candidate in candidates if candidate.candidate_role == candidate_role]
    if not relevant:
        label = (
            "workload controller"
            if candidate_role == "workload_controller"
            else "companion object"
        )
        out(f"_No {label} candidates detected in scanned repository facts._")
    else:
        for candidate in relevant:
            out(f"- {candidate.kind} candidate: {candidate.rationale} ({candidate.confidence})")
    out("")


def _component_block(out, comp: Component) -> None:
    out(f"### {comp.name}")
    out("")
    if comp.dockerfile:
        build_source = comp.dockerfile
    elif comp.build_tool:
        build_source = f"via {comp.build_tool}"
    else:
        build_source = comp.image or "(image only)"
    out(f"- Build: {build_source}"
        + (f" (context `{comp.build_context}`)" if comp.build_context else ""))
    out(f"- Image: `{comp.image}`" if comp.image else "- Image: (built locally)")
    if comp.language:
        out(f"- Language: {comp.language}")
    if comp.frameworks:
        out(f"- Frameworks: {', '.join(comp.frameworks)}")
    if comp.build_tool:
        out(f"- Build tool: {comp.build_tool}")
    if comp.build_command:
        out(f"- Build command: `{comp.build_command}`")
    if comp.build_artifact:
        out(f"- Build artifact: `{comp.build_artifact}`" + (f" ({comp.packaging})" if comp.packaging else ""))
    if comp.application_server:
        out(f"- Application server: {comp.application_server}")
    if comp.runtime:
        out(f"- Runtime: {comp.runtime}")
    if comp.command:
        cmd = " ".join(comp.command)
        out(f"- Command: `{cmd}`" + (f" (workers={comp.workers})" if comp.workers else ""))
    if comp.container_ports:
        out(f"- Container port: {', '.join(str(p) for p in comp.container_ports)}")
    if comp.context_path:
        out(f"- HTTP context path: `{comp.context_path}`")
    if comp.published_ports:
        out(f"- Published (compose): {', '.join(comp.published_ports)}")
    if comp.depends_on:
        out(f"- Depends on: {', '.join(comp.depends_on)}")
    if comp.environment:
        out(f"- Environment: {', '.join(comp.environment)}")
    if comp.secret_candidates:
        out(f"- Secret candidates: {', '.join(comp.secret_candidates)}")
    if comp.runtime_dependencies:
        out(f"- Runtime dependencies: {', '.join(comp.runtime_dependencies)}")
    if comp.volumes:
        out(f"- Volumes: {', '.join(comp.volumes)}")
    if comp.healthcheck:
        out(f"- Health check: {comp.healthcheck}")
    out(f"- Kubernetes mapping: {comp.workload_candidate}")
    if comp.unresolved:
        out(f"- Unresolved: {', '.join(sorted(set(comp.unresolved)))}")
    out("")


def _workloads_section(out, result: AnalysisResult) -> None:
    out("## 2. Kubernetes workload mappings")
    out("")
    if result.workload_profiles:
        out("| Component | Kubernetes candidates | Rationale |")
        out("| --- | --- | --- |")
        for profile in result.workload_profiles:
            candidates = profile.runtime_deployment_profile.kubernetes_candidates
            kinds = " + ".join(dict.fromkeys(candidate.kind for candidate in candidates)) or "—"
            rationales = "; ".join(
                f"{candidate.kind}: {candidate.rationale}" for candidate in candidates
            ) or "No candidate derived from scanned repository facts."
            out(f"| {profile.name} | {kinds} | {rationales} |")
        out("")
        return
    if not result.workload_mappings:
        out("_No workloads derived._")
        out("")
        return
    out("| Component | Workload candidate | Rationale |")
    out("| --- | --- | --- |")
    for wm in result.workload_mappings:
        out(f"| {wm.component} | {wm.kubernetes_kind} | {wm.rationale} |")
    out("")


def _networking_section(out, result: AnalysisResult) -> None:
    out("## 3. Networking (ports & services)")
    out("")
    if not result.networking:
        out("_No networking facts found._")
        out("")
        return
    out("| Subject | Value | Confidence | Kubernetes effect | Evidence |")
    out("| --- | --- | --- | --- | --- |")
    for f in result.networking:
        out(f"| {f.subject} | {f.value} | {f.confidence} | {f.kubernetes_effect} | {_fmt_evidence(f.evidence)} |")
    out("")


def _storage_section(out, result: AnalysisResult) -> None:
    out("## 4. Persistent storage")
    out("")
    if not result.storage:
        out("_No persistent volumes detected._")
        out("")
        return
    for f in result.storage:
        value = f.value
        if isinstance(value, dict) and "tables" in value:
            desc = "database tables: " + ", ".join(value.get("tables") or [])
            profiles = value.get("profiles") or []
            if profiles:
                desc += f" (profiles: {', '.join(profiles)})"
        elif isinstance(value, dict):
            desc = f"`{value.get('volume')}` at `{value.get('mount_path')}`"
        else:
            desc = str(value)
        out(f"- {f.subject}: {desc} — {f.kubernetes_effect} ({f.confidence}); evidence {_fmt_evidence(f.evidence)}")
    out("")


def _dependencies_section(out, result: AnalysisResult) -> None:
    out("## 4b. Runtime dependencies (external services & datastores)")
    out("")
    if not result.runtime_dependencies:
        out("_No external runtime dependencies detected._")
        out("")
        return
    for f in result.runtime_dependencies:
        out(f"- {f.subject}: **{f.value}** — {f.kubernetes_effect} ({f.confidence}); evidence {_fmt_evidence(f.evidence)}")
    out("")


def _image_section(out, result: AnalysisResult) -> None:
    out("## 8b. Container image build & runtime")
    out("")
    if not result.container_image:
        out("_No container image facts detected._")
        out("")
        return
    for f in result.container_image:
        out(f"- {f.subject}: **{f.value}** — {f.kubernetes_effect} ({f.confidence})")
        out(f"  - evidence: {_fmt_evidence(f.evidence)}")
    out("")


def _config_secret_section(out, result: AnalysisResult) -> None:
    out("## 5. Configuration & Secrets")
    out("")
    config_keys = [f for f in result.configuration if "ConfigMap key candidate" in f.kubernetes_effect]
    stack_facts = [f for f in result.configuration if "ConfigMap key candidate" not in f.kubernetes_effect]

    out("### ConfigMap candidates")
    out("")
    if config_keys:
        out("| Key | Default | Evidence |")
        out("| --- | --- | --- |")
        for f in config_keys:
            shown = "" if f.value == "" else f.value
            out(f"| {f.subject.removeprefix('config.')} | {shown} | {_fmt_evidence(f.evidence)} |")
    else:
        out("_None detected._")
    out("")

    if stack_facts:
        out("### Stack, build & profile facts")
        out("")
        out("| Subject | Value | Kubernetes effect | Evidence |")
        out("| --- | --- | --- | --- |")
        for f in stack_facts:
            out(f"| {f.subject} | {f.value} | {f.kubernetes_effect} | {_fmt_evidence(f.evidence)} |")
        out("")
    out("### Secret candidates")
    out("")
    if result.secrets:
        out("| Key | Evidence |")
        out("| --- | --- |")
        for f in result.secrets:
            out(f"| {f.subject.removeprefix('secret.')} | {_fmt_evidence(f.evidence)} |")
    else:
        out("_None detected._")
    out("")


def _startup_section(out, result: AnalysisResult) -> None:
    out("## 6. Startup order & initialization")
    out("")
    if not result.startup_order:
        out("_No explicit ordering constraints found._")
        out("")
        return
    for f in result.startup_order:
        if f.subject == "startup.order" and isinstance(f.value, list):
            out("Overall order (derived):")
            out("")
            for step_index, step in enumerate(f.value, start=1):
                out(f"{step_index}. {step}")
            out("")
    for f in result.startup_order:
        if f.subject == "startup.order":
            continue
        out(f"- {f.subject}: `{f.value}` — {f.kubernetes_effect} ({f.confidence}); evidence {_fmt_evidence(f.evidence)}")
    out("")


def _healthcheck_section(out, result: AnalysisResult) -> None:
    out("## 7. Health checks")
    out("")
    if not result.health_checks:
        out("_No health checks defined._")
        out("")
        return
    for f in result.health_checks:
        out(f"- {f.subject}: `{f.value}` — {f.kubernetes_effect} ({f.confidence}); evidence {_fmt_evidence(f.evidence)}")
    out("")


def _buildtime_section(out, result: AnalysisResult) -> None:
    out("## 8. Build-time constraints")
    out("")
    if not result.build_time_constraints:
        out("_None detected._")
        out("")
        return
    for f in result.build_time_constraints:
        out(f"- {f.subject}: **{f.value}** — {f.kubernetes_effect} ({f.confidence})")
        out(f"  - evidence: {_fmt_evidence(f.evidence)}")
    out("")


def _unresolved_section(out, result: AnalysisResult) -> None:
    out("## 9. Unresolved operational inputs")
    out("")
    out("_These are NOT decided from the repository. No default values were invented._")
    out("")
    out("| Subject | Why unresolved | Input needed | Kubernetes effect |")
    out("| --- | --- | --- | --- |")
    for u in result.unresolved_operational_inputs:
        out(f"| {u.subject} | {u.reason} | {u.needed_input} | {u.kubernetes_effect} |")
    out("")


def _warnings_section(out, result: AnalysisResult) -> None:
    out("## 10. Warnings & unsupported constructs")
    out("")
    if result.warnings:
        out("Warnings:")
        out("")
        for w in result.warnings:
            location = f" (`{w.path}`)" if w.path else ""
            out(f"- [{w.code}] {w.message}{location}")
        out("")
    else:
        out("_No warnings._")
        out("")
    if result.unsupported_constructs:
        out("Unsupported constructs:")
        out("")
        for u in result.unsupported_constructs:
            out(f"- `{u.path}` — {u.construct_type}: {u.detail}")
        out("")
    else:
        out("_No unsupported constructs._")
        out("")


def _migration_questions_section(out, result: AnalysisResult) -> None:
    out("## Migration questions")
    out("")
    if not result.migration_questions:
        out("_No migration question answers emitted._")
        out("")
        return
    for index, question in enumerate(result.migration_questions, start=1):
        out(f"{index}. **{question.question}**")
        out(f"   - Status: `{question.status}`")
        out(f"   - Answer: {question.answer}")
        if question.basis:
            basis = "; ".join(
                f"{basis.source_section}.{basis.subject}"
                + (f" ({_fmt_evidence(basis.evidence)})" if basis.evidence else "")
                for basis in question.basis
            )
            out(f"   - Basis: {basis}")
        else:
            out("   - Basis: —")
        if question.missing:
            out(f"   - Missing: {'; '.join(question.missing)}")
        else:
            out("   - Missing: —")
    out("")


def write_markdown(result: AnalysisResult, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_markdown(result), encoding="utf-8")
