"""Concise Markdown brief for the seven Kubernetes migration questions."""

from __future__ import annotations

from pathlib import Path

from ..models import AnalysisResult, AnswerBasis, WorkloadProfile

_MAX_EVIDENCE_ITEMS = 6


def to_brief(result: AnalysisResult) -> str:
    lines: list[str] = []
    out = lines.append
    repo = result.repository

    out(f"# Kubernetes migration brief - {repo.name}")
    out("")
    out(f"- Profile: `{repo.profile}`")
    out(f"- Git ref: `{repo.git_ref}`" if repo.git_ref else "- Git ref: (not provided)")
    out(f"- Detected files: {repo.file_count}")
    out("")

    out("## Executive summary")
    out("")
    if result.migration_questions:
        statuses = ", ".join(f"{q.id}={q.status}" for q in result.migration_questions)
        out(f"- Questions: {statuses}")
    else:
        out("- Questions: none emitted")
    out(f"- Components: {len(result.components)}")
    out(f"- Open inputs: {len(result.unresolved_operational_inputs)}")
    out("")

    if result.workload_profiles:
        _workload_profiles_section(out, result.workload_profiles)

    out("## Seven migration questions")
    out("")
    if not result.migration_questions:
        out("_No migration questions emitted._")
        out("")
    else:
        for index, question in enumerate(result.migration_questions, start=1):
            out(f"### {index}. {question.question}")
            out("")
            out(f"**Status:** {question.status}")
            out("")
            out(f"**Answer:** {_question_answer(question.id, question.answer, result.workload_profiles)}")
            out("")
            out(f"**Evidence:** {_format_basis(question.basis)}")
            out("")
            out(f"**Missing:** {_format_missing(question.missing)}")
            out("")

    out("## Open inputs")
    out("")
    if not result.unresolved_operational_inputs:
        out("_No unresolved operational inputs recorded._")
    else:
        for item in result.unresolved_operational_inputs:
            out(f"- {item.subject}: {item.needed_input}")
    out("")

    return "\n".join(lines) + "\n"


def _workload_profiles_section(out, profiles: list[WorkloadProfile]) -> None:
    out("## Workload profiles")
    out("")
    for profile in profiles:
        image = profile.image_build_profile
        runtime = profile.runtime_deployment_profile
        out(f"### {profile.name}")
        out("")

        image_details = _details(
            [
                ("tool", image.build_tool),
                ("context", image.build_context),
                ("Dockerfile", image.dockerfile),
                ("image", image.image),
                ("source", image.image_source),
            ]
        )
        out(
            "- Image build: "
            f"{image_details or 'no profile facts detected in scanned repository facts'}"
        )

        runtime_details = _details(
            [
                ("runtime", runtime.runtime),
                ("command", " ".join(runtime.command) if runtime.command else None),
                ("ports", ", ".join(str(port) for port in runtime.container_ports) or None),
            ]
        )
        out(
            "- Runtime deployment: "
            f"{runtime_details or 'no profile facts detected in scanned repository facts'}"
        )

        _candidate_summary(out, "Workload controller candidates", runtime.kubernetes_candidates, "workload_controller")
        _candidate_summary(out, "Companion object candidates", runtime.kubernetes_candidates, "companion_object")

        if runtime.relationships:
            out("- Relationships: " + "; ".join(
                f"{relationship.source} -> {relationship.target}"
                for relationship in runtime.relationships
            ))
        decisions = _profile_open_decisions(profile)
        if decisions:
            out(f"- Open decisions: {'; '.join(decisions)}")
        out("")


def _details(items: list[tuple[str, str | None]]) -> str:
    return "; ".join(f"{label}={value}" for label, value in items if value is not None)


def _candidate_summary(out, label: str, candidates, role: str) -> None:
    names = [candidate.kind for candidate in candidates if candidate.candidate_role == role]
    if names:
        out(f"- {label}: {', '.join(names)}")


def _question_answer(question_id: str, legacy_answer: str, profiles: list[WorkloadProfile]) -> str:
    if not profiles:
        return legacy_answer

    if question_id == "build_and_run":
        summaries = []
        for profile in profiles:
            image = profile.image_build_profile
            runtime = profile.runtime_deployment_profile
            image_details = _details(
                [
                    ("tool", image.build_tool),
                    ("context", image.build_context),
                    ("Dockerfile", image.dockerfile),
                    ("image", image.image),
                    ("source", image.image_source),
                ]
            )
            runtime_details = _details(
                [
                    ("runtime", runtime.runtime),
                    ("command", " ".join(runtime.command) if runtime.command else None),
                    ("ports", ", ".join(str(port) for port in runtime.container_ports) or None),
                ]
            )
            summaries.extend(
                [
                    f"{profile.name}: Image build: "
                    f"{image_details or 'no profile facts detected in scanned repository facts'}",
                    f"{profile.name}: Runtime deployment: "
                    f"{runtime_details or 'no profile facts detected in scanned repository facts'}",
                ]
            )
        return _enriched_answer(legacy_answer, summaries)

    if question_id == "ports_and_services":
        summaries = []
        relationships = []
        for profile in profiles:
            candidates = profile.runtime_deployment_profile.kubernetes_candidates
            controllers = [
                candidate.kind
                for candidate in candidates
                if candidate.candidate_role == "workload_controller"
            ]
            companions = [
                candidate.kind
                for candidate in candidates
                if candidate.candidate_role == "companion_object"
            ]
            if controllers:
                summaries.append(
                    f"{profile.name}: Workload controller candidates: "
                    f"{', '.join(controllers)}"
                )
            if companions:
                summaries.append(
                    f"{profile.name}: Companion object candidates: {', '.join(companions)}"
                )
            relationships.extend(
                f"{relationship.source} -> {relationship.target}"
                for relationship in profile.runtime_deployment_profile.relationships
            )
        if relationships:
            summaries.append(f"Workload relationships: {'; '.join(dict.fromkeys(relationships))}")
        return _enriched_answer(legacy_answer, summaries)

    if question_id == "repository_unknowns":
        decisions = list(
            dict.fromkeys(
                decision
                for profile in profiles
                for decision in _profile_open_decisions(profile)
            )
        )
        summaries = (
            [f"Workload profile open decisions: {'; '.join(decisions)}"]
            if decisions
            else []
        )
        return _enriched_answer(legacy_answer, summaries)

    return legacy_answer


def _profile_open_decisions(profile: WorkloadProfile) -> list[str]:
    image = profile.image_build_profile
    runtime = profile.runtime_deployment_profile
    decisions = [
        *image.open_decisions,
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
        *(
            decision
            for relationship in runtime.relationships
            for decision in relationship.open_decisions
        ),
    ]
    return list(dict.fromkeys(decisions))


def _enriched_answer(legacy_answer: str, summaries: list[str]) -> str:
    if not summaries:
        return legacy_answer
    return f"{legacy_answer}\n\n" + "\n".join(f"- {summary}" for summary in summaries)


def _format_basis(basis_items: list[AnswerBasis]) -> str:
    if not basis_items:
        return "-"
    rendered = [_format_basis_item(item) for item in basis_items[:_MAX_EVIDENCE_ITEMS]]
    remaining = len(basis_items) - _MAX_EVIDENCE_ITEMS
    if remaining > 0:
        rendered.append(f"+{remaining} more")
    return "; ".join(rendered)


def _format_basis_item(item: AnswerBasis) -> str:
    prefix = f"{item.source_section}.{item.subject}"
    if not item.evidence:
        return prefix
    locations = ", ".join(
        f"{evidence.path}:{evidence.start_line}-{evidence.end_line}"
        for evidence in item.evidence[:2]
    )
    remaining = len(item.evidence) - 2
    if remaining > 0:
        locations += f", +{remaining} more"
    return f"{prefix} -> {locations}"


def _format_missing(missing: list[str]) -> str:
    if not missing:
        return "-"
    return "; ".join(missing)


def write_brief(result: AnalysisResult, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_brief(result), encoding="utf-8")
