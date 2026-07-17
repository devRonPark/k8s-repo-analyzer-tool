"""Spring Boot ``application*.yml`` / ``.yaml`` parser with source-line tracking.

Flattens a YAML Spring config into the SAME dot-keyed ``SpringProperties`` model
the ``.properties`` parser produces, so the Spring/Java rules consume both
formats identically (e.g. ``server.port``, ``spring.datasource.url``,
``management.endpoints.web.exposure.include``).

Uses ruamel.yaml in round-trip mode so every extracted key keeps its real source
line. ``${ENV:default}`` placeholders are extracted (reusing the properties
parser) so datasource URLs and credentials map to ConfigMap/Secret candidates.

Constructs that cannot be flattened deterministically are NOT silently dropped;
each is recorded as a ``ParseIssue`` so the gap is visible:

* ``yaml_parse_error`` — the document is not valid YAML.
* ``spring_yaml_root`` — a non-empty top-level document is not a mapping.
* ``spring_yaml_sequence`` — a sequence whose items are not all scalars.
* ``spring_yaml_extra_document`` — an additional ``---`` document (typically a
  ``spring.config.activate.on-profile`` section) is not merged.
"""

from __future__ import annotations

import re

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .common import ParseIssue
from .spring_properties import SpringProperties, SpringProperty, _placeholders

_YAML_PROFILE_RE = re.compile(r"application-([\w.-]+)\.ya?ml")


def profile_from_yaml_filename(path: str) -> str | None:
    """``application-prod.yml`` -> ``prod``; ``application.yml`` -> None."""

    name = path.rsplit("/", 1)[-1]
    match = _YAML_PROFILE_RE.fullmatch(name)
    return match.group(1) if match else None


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar_to_str(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _key_line(node: object, key: object) -> int:
    """1-based source line of ``key`` within a ruamel round-trip mapping."""

    lc = getattr(node, "lc", None)
    data = getattr(lc, "data", None) if lc is not None else None
    if isinstance(data, dict) and key in data:
        return data[key][0] + 1
    line = getattr(lc, "line", None) if lc is not None else None
    return (line + 1) if line is not None else 1


def _flatten(node: dict, prefix: str, result: SpringProperties) -> None:
    for key in node:
        dotted = f"{prefix}{key}"
        value = node[key]
        line = _key_line(node, key)
        if isinstance(value, dict):
            _flatten(value, f"{dotted}.", result)
        elif isinstance(value, list):
            if all(_is_scalar(item) for item in value):
                joined = ",".join(_scalar_to_str(item) for item in value)
                result.entries.append(
                    SpringProperty(
                        key=dotted, value=joined, line=line, placeholders=_placeholders(joined)
                    )
                )
            else:
                result.issues.append(
                    ParseIssue(
                        "spring_yaml_sequence",
                        f"non-scalar sequence at '{dotted}' (line {line}) not flattened",
                    )
                )
        elif _is_scalar(value):
            svalue = _scalar_to_str(value)
            result.entries.append(
                SpringProperty(
                    key=dotted, value=svalue, line=line, placeholders=_placeholders(svalue)
                )
            )
        else:  # pragma: no cover - defensive; ruamel yields only dict/list/scalar
            result.issues.append(
                ParseIssue(
                    "spring_yaml_value",
                    f"unsupported value type at '{dotted}' (line {line})",
                )
            )


def parse_spring_yaml(text: str, path: str) -> SpringProperties:
    result = SpringProperties(path=path, profile=profile_from_yaml_filename(path))
    yaml = YAML()
    try:
        documents = list(yaml.load_all(text))
    except YAMLError as exc:
        result.issues.append(ParseIssue("yaml_parse_error", str(exc)))
        return result

    mappings = [doc for doc in documents if isinstance(doc, dict)]
    if not mappings:
        if any(doc is not None for doc in documents):
            result.issues.append(
                ParseIssue("spring_yaml_root", "top-level YAML document is not a mapping")
            )
        return result

    _flatten(mappings[0], "", result)
    for _ in mappings[1:]:
        result.issues.append(
            ParseIssue(
                "spring_yaml_extra_document",
                "additional YAML document (profile-gated section) not merged",
            )
        )
    return result
