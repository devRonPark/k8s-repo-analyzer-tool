"""Directive-oriented Nginx configuration parser.

A small brace/semicolon tokenizer that keeps line numbers and block nesting.
Enough to answer P0 questions: what does it ``listen`` on, which ``location``
blocks exist, and where does it ``proxy_pass`` / ``return``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import ParseIssue


@dataclass
class NginxDirective:
    name: str
    args: list[str]
    context: tuple[str, ...]
    start_line: int
    end_line: int


@dataclass
class NginxConfig:
    path: str
    directives: list[NginxDirective] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    def find(self, name: str) -> list[NginxDirective]:
        return [d for d in self.directives if d.name == name]


def parse_nginx(text: str, path: str) -> NginxConfig:
    result = NginxConfig(path=path)
    context: list[str] = []
    tokens: list[str] = []
    buf = ""
    stmt_line: int | None = None
    line = 1
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char == "#":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "\n":
            line += 1
            index += 1
            continue
        if char in " \t\r":
            if buf:
                tokens.append(buf)
                buf = ""
            index += 1
            continue
        if char in "{};":
            if buf:
                tokens.append(buf)
                buf = ""
            if char == ";":
                if tokens:
                    result.directives.append(
                        NginxDirective(
                            tokens[0], tokens[1:], tuple(context), stmt_line or line, line
                        )
                    )
                tokens = []
                stmt_line = None
            elif char == "{":
                if tokens:
                    result.directives.append(
                        NginxDirective(
                            tokens[0], tokens[1:], tuple(context), stmt_line or line, line
                        )
                    )
                    context.append(" ".join(tokens))
                else:
                    context.append("{}")
                tokens = []
                stmt_line = None
            else:  # '}'
                if context:
                    context.pop()
                else:
                    result.issues.append(ParseIssue("nginx_brace", f"unbalanced '}}' at line {line}"))
                tokens = []
                stmt_line = None
            index += 1
            continue
        if stmt_line is None:
            stmt_line = line
        buf += char
        index += 1

    if context:
        result.issues.append(ParseIssue("nginx_brace", "unclosed block(s) at end of file"))
    return result
