"""Docker Compose parser.

Uses ruamel.yaml in round-trip mode so every extracted value keeps its real
source line range. Rules never hardcode line numbers; they read the ranges this
parser attaches to each ``Located`` value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .common import Located, ParseIssue


@dataclass
class ComposeService:
    name: str
    selector: str
    image: Located | None = None
    build_context: Located | None = None
    build_dockerfile: Located | None = None
    build_args: list[Located] = field(default_factory=list)
    command: Located | None = None
    environment: list[Located] = field(default_factory=list)
    env_files: list[Located] = field(default_factory=list)
    ports: list[Located] = field(default_factory=list)
    volumes: list[Located] = field(default_factory=list)
    labels: list[Located] = field(default_factory=list)
    healthcheck: Located | None = None
    healthcheck_test: Located | None = None
    depends_on: list[Located] = field(default_factory=list)


@dataclass
class ComposeFile:
    path: str
    services: list[ComposeService] = field(default_factory=list)
    named_volumes: list[Located] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)


def _first_line(node: object) -> int | None:
    lc = getattr(node, "lc", None)
    if lc is not None and getattr(lc, "line", None) is not None:
        return lc.line
    return None


def _last_line(node: object) -> int | None:
    lc = getattr(node, "lc", None)
    if lc is None:
        return None
    lines: list[int] = []
    if getattr(lc, "line", None) is not None:
        lines.append(lc.line)
    if isinstance(node, dict):
        for key, value in node.items():
            data = getattr(node.lc, "data", {})
            if key in data:
                lines.append(data[key][0])
            child = _last_line(value)
            if child is not None:
                lines.append(child)
    elif isinstance(node, list):
        data = getattr(node.lc, "data", {})
        for index, value in enumerate(node):
            if index in data:
                lines.append(data[index][0])
            child = _last_line(value)
            if child is not None:
                lines.append(child)
    return max(lines) if lines else None


def _map_key_range(parent: dict, key: str) -> tuple[int, int]:
    data = parent.lc.data[key]
    start = data[0]
    end = _last_line(parent[key])
    if end is None:
        end = data[2] if len(data) > 2 and data[2] is not None else start
    return start + 1, end + 1


def _seq_item_range(parent: list, index: int) -> tuple[int, int]:
    start = parent.lc.data[index][0]
    end = _last_line(parent[index])
    if end is None:
        end = start
    return start + 1, end + 1


def _located_map_value(parent: dict, key: str, selector: str) -> Located:
    start, end = _map_key_range(parent, key)
    return Located(value=parent[key], selector=selector, start_line=start, end_line=end)


def _normalise_command(value: object) -> list[str]:
    if isinstance(value, str):
        return value.split()
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def parse_compose(text: str, path: str) -> ComposeFile:
    """Parse a compose file's text into a structured, line-located model."""

    result = ComposeFile(path=path)
    yaml = YAML()
    try:
        data = yaml.load(text)
    except YAMLError as exc:  # pragma: no cover - exercised via bad-input test
        result.issues.append(ParseIssue("yaml_parse_error", str(exc)))
        return result
    if not isinstance(data, dict):
        result.issues.append(ParseIssue("compose_root", "top-level document is not a mapping"))
        return result

    services = data.get("services")
    if isinstance(services, dict):
        for name in services:
            svc_node = services[name]
            base = f"$.services.{name}"
            service = ComposeService(name=str(name), selector=base)
            if not isinstance(svc_node, dict):
                result.issues.append(
                    ParseIssue("compose_service", f"service '{name}' is not a mapping")
                )
                result.services.append(service)
                continue
            _parse_service(svc_node, service, result)
            result.services.append(service)

    top_volumes = data.get("volumes")
    if isinstance(top_volumes, dict):
        for vol_name in top_volumes:
            start, end = _map_key_range(top_volumes, vol_name)
            result.named_volumes.append(
                Located(str(vol_name), f"$.volumes.{vol_name}", start, end)
            )
    return result


def _parse_service(node: dict, service: ComposeService, result: ComposeFile) -> None:
    base = service.selector

    if "image" in node:
        service.image = _located_map_value(node, "image", f"{base}.image")

    build = node.get("build")
    if isinstance(build, dict):
        if "context" in build:
            service.build_context = _located_map_value(
                build, "context", f"{base}.build.context"
            )
        if "dockerfile" in build:
            service.build_dockerfile = _located_map_value(
                build, "dockerfile", f"{base}.build.dockerfile"
            )
        args = build.get("args")
        service.build_args = _collect_kv(args, f"{base}.build.args")
    elif isinstance(build, str):
        start, end = _map_key_range(node, "build")
        service.build_context = Located(build, f"{base}.build", start, end)

    if "command" in node:
        start, end = _map_key_range(node, "command")
        service.command = Located(
            _normalise_command(node["command"]), f"{base}.command", start, end
        )

    service.environment = _collect_kv(
        node.get("environment"), f"{base}.environment", preserve_unassigned=True
    )
    service.env_files = _collect_scalar_list(node.get("env_file"), f"{base}.env_file")
    service.ports = _collect_scalar_list(node.get("ports"), f"{base}.ports")
    service.volumes = _collect_scalar_list(node.get("volumes"), f"{base}.volumes")
    service.labels = _collect_kv(node.get("labels"), f"{base}.labels")

    health = node.get("healthcheck")
    if isinstance(health, dict):
        service.healthcheck = _located_map_value(node, "healthcheck", f"{base}.healthcheck")
        if "test" in health:
            service.healthcheck_test = _located_map_value(
                health, "test", f"{base}.healthcheck.test"
            )

    service.depends_on = _collect_depends_on(node.get("depends_on"), f"{base}.depends_on")


def _collect_scalar_list(node: object, selector: str) -> list[Located]:
    items: list[Located] = []
    if isinstance(node, list):
        for index, value in enumerate(node):
            start, end = _seq_item_range(node, index)
            items.append(Located(str(value), f"{selector}[{index}]", start, end))
    elif isinstance(node, str):
        items.append(Located(node, selector, 0, 0))
    return items


def _collect_kv(
    node: object, selector: str, *, preserve_unassigned: bool = False
) -> list[Located]:
    """Collect key=value style entries from either a list or a mapping."""

    items: list[Located] = []
    if isinstance(node, list):
        for index, value in enumerate(node):
            start, end = _seq_item_range(node, index)
            items.append(Located(str(value), f"{selector}[{index}]", start, end))
    elif isinstance(node, dict):
        for key in node:
            start, end = _map_key_range(node, key)
            raw = (
                str(key)
                if preserve_unassigned and node[key] is None
                else f"{key}={node[key]}"
            )
            items.append(Located(raw, f"{selector}.{key}", start, end))
    return items


def _collect_depends_on(node: object, selector: str) -> list[Located]:
    items: list[Located] = []
    if isinstance(node, list):
        for index, value in enumerate(node):
            start, end = _seq_item_range(node, index)
            items.append(Located(str(value), f"{selector}[{index}]", start, end))
    elif isinstance(node, dict):
        for key in node:
            start, end = _map_key_range(node, key)
            condition = ""
            if isinstance(node[key], dict) and "condition" in node[key]:
                condition = str(node[key]["condition"])
            items.append(
                Located(
                    {"service": str(key), "condition": condition},
                    f"{selector}.{key}",
                    start,
                    end,
                )
            )
    return items
