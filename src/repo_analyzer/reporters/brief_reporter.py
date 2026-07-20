"""Concise Markdown brief for the seven Kubernetes migration questions."""

from __future__ import annotations

from pathlib import Path

from ..models import AnalysisResult, AnswerBasis

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
            out(f"**Answer:** {question.answer}")
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
