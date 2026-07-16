"""Dockerfile parser at instruction granularity.

Line-continuations (``\\``) are joined into a single logical instruction while the
physical start/end line range is preserved for evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .common import ParseIssue


@dataclass
class DockerInstruction:
    instruction: str
    argument: str
    start_line: int
    end_line: int


@dataclass
class DockerStage:
    image: str
    alias: str | None
    start_line: int
    end_line: int


@dataclass
class Dockerfile:
    path: str
    instructions: list[DockerInstruction] = field(default_factory=list)
    stages: list[DockerStage] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    def find(self, instruction: str) -> list[DockerInstruction]:
        return [i for i in self.instructions if i.instruction == instruction]

    def last(self, instruction: str) -> DockerInstruction | None:
        found = self.find(instruction)
        return found[-1] if found else None

    @property
    def final_base_image(self) -> DockerStage | None:
        return self.stages[-1] if self.stages else None


def exec_form(argument: str) -> list[str] | None:
    """Return the argv list for JSON exec-form instructions, else ``None``."""

    text = argument.strip()
    if not text.startswith("["):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return parsed
    return None


def parse_dockerfile(text: str, path: str) -> Dockerfile:
    result = Dockerfile(path=path)
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        start = index
        parts = [lines[index]]
        while parts[-1].rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            parts.append(lines[index])
        end = index
        combined = " ".join(part.rstrip().rstrip("\\").strip() for part in parts).strip()
        tokens = combined.split(None, 1)
        if not tokens:
            index += 1
            continue
        instruction = tokens[0].upper()
        argument = tokens[1] if len(tokens) > 1 else ""
        result.instructions.append(
            DockerInstruction(instruction, argument, start + 1, end + 1)
        )
        if instruction == "FROM":
            result.stages.append(_parse_from(argument, start + 1, end + 1, result))
        index += 1
    if not result.stages:
        result.issues.append(ParseIssue("dockerfile_from", "no FROM instruction found"))
    return result


def _parse_from(argument: str, start: int, end: int, result: Dockerfile) -> DockerStage:
    tokens = [t for t in argument.split() if not t.startswith("--")]
    image = tokens[0] if tokens else ""
    alias: str | None = None
    for pos, token in enumerate(tokens):
        if token.upper() == "AS" and pos + 1 < len(tokens):
            alias = tokens[pos + 1]
            break
    if not image:
        result.issues.append(ParseIssue("dockerfile_from", f"unparseable FROM: {argument!r}"))
    return DockerStage(image=image, alias=alias, start_line=start, end_line=end)
