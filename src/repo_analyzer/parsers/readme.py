"""README parser for high-level repository facts."""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import Located


@dataclass
class ReadmeFile:
    path: str
    title: Located | None = None
    application_description: Located | None = None
    commands: list[Located] = field(default_factory=list)


def parse_readme(text: str, path: str) -> ReadmeFile:
    parsed = ReadmeFile(path=path)
    in_fence = False
    for index, raw in enumerate(text.splitlines()):
        line_no = index + 1
        line = raw.strip()
        if line.startswith("# ") and parsed.title is None:
            title = line.removeprefix("# ").split("[", 1)[0].strip()
            if title:
                parsed.title = Located(title, "heading.h1", line_no, line_no)
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and line and not line.startswith("#"):
            parsed.commands.append(Located(line, "fenced-command", line_no, line_no))
        if (
            parsed.application_description is None
            and not line.startswith("#")
            and not line.startswith("[")
            and " application " in f" {line.lower()} "
            and " is " in f" {line.lower()} "
        ):
            parsed.application_description = Located(line, "application-description", line_no, line_no)
    return parsed
