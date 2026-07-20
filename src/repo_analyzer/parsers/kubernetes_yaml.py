"""Kubernetes YAML parser for P0 manifest evidence.

This confirms Kubernetes documents and extracts only migration-overview facts:
apiVersion, kind, metadata.name, ports, environment variable names, and
ConfigMap/Secret references.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ruamel.yaml import YAML

from .common import Located


@dataclass
class KubernetesResource:
    api_version: Located
    kind: Located
    name: Located | None = None
    ports: list[Located] = field(default_factory=list)
    env_names: list[Located] = field(default_factory=list)
    configmap_refs: list[Located] = field(default_factory=list)
    secret_refs: list[Located] = field(default_factory=list)


@dataclass
class KubernetesManifest:
    path: str
    resources: list[KubernetesResource] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def parse_kubernetes_yaml(text: str, path: str) -> KubernetesManifest:
    manifest = KubernetesManifest(path=path)
    yaml = YAML(typ="rt")
    try:
        docs = list(yaml.load_all(text))
    except Exception as exc:
        manifest.issues.append(f"yaml_parse_error: {exc}")
        return manifest

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        api_version = doc.get("apiVersion")
        kind = doc.get("kind")
        if not api_version or not kind:
            continue
        api_line = _line_for_key(doc, "apiVersion")
        kind_line = _line_for_key(doc, "kind")
        name = None
        metadata = doc.get("metadata")
        if isinstance(metadata, dict) and metadata.get("name"):
            name_line = _line_for_key(metadata, "name")
            name = Located(str(metadata.get("name")), "metadata.name", name_line, name_line)
        manifest.resources.append(
            KubernetesResource(
                api_version=Located(str(api_version), "apiVersion", api_line, api_line),
                kind=Located(str(kind), "kind", kind_line, kind_line),
                name=name,
                ports=_collect_ports(doc),
                env_names=_collect_env_names(doc),
                configmap_refs=_collect_named_refs(doc, "configMapRef", "configMapKeyRef"),
                secret_refs=_collect_named_refs(doc, "secretRef", "secretKeyRef"),
            )
        )
    return manifest


def _line_for_key(mapping: dict[Any, Any], key: str) -> int:
    try:
        return int(mapping.lc.key(key)[0]) + 1
    except Exception:
        return 1


def _collect_ports(node: Any) -> list[Located]:
    ports: list[Located] = []
    if isinstance(node, dict):
        for key in ("port", "targetPort", "containerPort"):
            value = node.get(key)
            if isinstance(value, int):
                line = _line_for_key(node, key)
                ports.append(Located(value, key, line, line))
        for value in node.values():
            ports.extend(_collect_ports(value))
    elif isinstance(node, list):
        for item in node:
            ports.extend(_collect_ports(item))
    return ports


def _collect_env_names(node: Any) -> list[Located]:
    names: list[Located] = []
    if isinstance(node, dict):
        if "env" in node and isinstance(node["env"], list):
            for item in node["env"]:
                if isinstance(item, dict) and item.get("name"):
                    line = _line_for_key(item, "name")
                    names.append(Located(str(item["name"]), "env.name", line, line))
        for value in node.values():
            names.extend(_collect_env_names(value))
    elif isinstance(node, list):
        for item in node:
            names.extend(_collect_env_names(item))
    return names


def _collect_named_refs(node: Any, *keys: str) -> list[Located]:
    refs: list[Located] = []
    if isinstance(node, dict):
        for key in keys:
            ref = node.get(key)
            if isinstance(ref, dict) and ref.get("name"):
                line = _line_for_key(ref, "name")
                refs.append(Located(str(ref["name"]), f"{key}.name", line, line))
        for value in node.values():
            refs.extend(_collect_named_refs(value, *keys))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_collect_named_refs(item, *keys))
    return refs
