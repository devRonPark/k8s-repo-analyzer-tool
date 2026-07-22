"""Bounded, read-only repository inspection tools."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any

from ruamel.yaml import YAML

from .contracts import (
    EvidenceItem,
    ExtractionMethod,
    RepositoryScan,
    RunLimits,
    ScanEntry,
    SearchMatch,
    SourceContext,
    ToolObservation,
    UsageSnapshot,
)

EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        ".venv",
        "venv",
        "target",
        "build",
        "dist",
        "coverage",
        ".cache",
        "__pycache__",
    }
)
SOURCE_CONTEXT_PARTS: tuple[tuple[SourceContext, frozenset[str]], ...] = (
    ("documentation", frozenset({"doc", "docs", "documentation"})),
    ("test", frozenset({"test", "tests", "spec", "specs"})),
    ("example", frozenset({"example", "examples", "demo", "samples"})),
    ("development", frozenset({"dev", "development", ".devcontainer"})),
    ("generated", frozenset({"target", "build", "dist", "generated"})),
)
SECRET_NAME = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)"
)
_ASSIGNMENT = re.compile(r"^(\s*[^#\s][^=:]*)(\s*[:=]\s*)(.*?)(\r?\n)?$")
_JSON_SECRET = re.compile(
    r'(?i)("[^"\\]*(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)[^"\\]*"\s*:\s*)'
    r'("(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?|true|false|null)'
)


class RepositoryToolError(RuntimeError):
    """Base class for narrow repository-tool failures."""


class RepositoryAccessError(RepositoryToolError):
    """Raised when a target cannot be accessed safely."""


class RepositoryLimitError(RepositoryToolError):
    """Raised when a configured repository-tool limit is exhausted."""


class UnsupportedFormatError(RepositoryToolError):
    """Raised when structured parsing does not support a selected file."""


class LocalRepositoryTools:
    """Expose bounded repository facts behind one read-only interface."""

    def __init__(
        self,
        root: str | Path,
        limits: RunLimits,
        revision: str | None = None,
    ) -> None:
        candidate = Path(root)
        try:
            self._root = candidate.resolve(strict=True)
        except OSError as exc:
            raise RepositoryAccessError(f"repository cannot be read: {candidate}") from exc
        if not self._root.is_dir():
            raise RepositoryAccessError(f"repository is not a directory: {candidate}")
        self._limits = limits
        self._requested_revision = revision
        self._file_cache: dict[Path, tuple[tuple[int, int], bytes, str]] = {}
        self._observation_cache: dict[
            tuple[str, int, int, str], ToolObservation
        ] = {}
        self._scan_cache: RepositoryScan | None = None
        self._physical_reads = 0
        self._search_calls = 0
        self._selected_targets = 0
        self._next_evidence_number = 1

    @property
    def usage(self) -> UsageSnapshot:
        return UsageSnapshot(
            physical_reads=self._physical_reads,
            search_calls=self._search_calls,
            selected_targets=self._selected_targets,
        )

    def scan(self) -> RepositoryScan:
        if self._scan_cache is not None:
            return self._scan_cache
        entries: list[ScanEntry] = []
        excluded: list[str] = []
        truncated = False

        def visit(directory: Path) -> None:
            nonlocal truncated
            if truncated:
                return
            try:
                children = sorted(directory.iterdir(), key=lambda path: path.name)
            except OSError as exc:
                raise RepositoryAccessError(f"repository directory cannot be listed: {directory}") from exc
            for child in children:
                relative = child.relative_to(self._root).as_posix()
                if child.name in EXCLUDED_DIRS and child.is_dir():
                    excluded.append(relative)
                    continue
                if len(entries) >= self._limits.tree_entries:
                    truncated = True
                    return
                try:
                    stat = child.lstat()
                except OSError as exc:
                    raise RepositoryAccessError(f"repository entry cannot be inspected: {relative}") from exc
                if child.is_symlink():
                    kind = "symlink"
                elif child.is_dir():
                    kind = "directory"
                else:
                    kind = "file"
                entries.append(
                    ScanEntry(
                        path=relative,
                        kind=kind,
                        size=stat.st_size if kind != "directory" else 0,
                        source_context=_source_context(relative),
                    )
                )
                if kind == "directory":
                    visit(child)

        visit(self._root)
        entries.sort(key=lambda item: item.path)
        revision, revision_source = self._resolve_revision(entries)
        self._scan_cache = RepositoryScan(
            repository=self._root.name,
            resolved_revision=revision,
            revision_source=revision_source,
            entries=entries,
            truncated=truncated,
            excluded_paths=sorted(excluded),
        )
        return self._scan_cache

    def list_tree(self, path: str = ".") -> ToolObservation:
        prefix = _normal_path(path)
        scan = self.scan()
        content = [
            item
            for item in scan.entries
            if prefix == "." or item.path == prefix or item.path.startswith(prefix + "/")
        ]
        return ToolObservation(
            operation="list_tree",
            target=prefix,
            content=content,
            truncated=scan.truncated,
        )

    def find_files(self, patterns: list[str]) -> ToolObservation:
        if not patterns:
            raise RepositoryAccessError("find_files requires at least one pattern")
        matches = [
            item.path
            for item in self.scan().entries
            if item.kind == "file"
            and any(fnmatch.fnmatchcase(item.path, pattern) for pattern in patterns)
        ]
        return ToolObservation(
            operation="find_files",
            target=",".join(patterns),
            content=sorted(matches),
        )

    def search_text(
        self, pattern: str, paths: list[str], *, regex: bool = False
    ) -> ToolObservation:
        if self._search_calls >= self._limits.search_calls:
            raise RepositoryLimitError("search_calls limit exhausted")
        if not pattern or len(pattern) > 256:
            raise RepositoryLimitError("search pattern must contain 1 to 256 characters")
        self._search_calls += 1
        matcher = _compile_matcher(pattern, regex)
        candidates = self._candidate_files(paths)
        matches: list[SearchMatch] = []
        evidence: list[EvidenceItem] = []
        truncated = False
        for relative in candidates:
            text, digest = self._read_text(relative)
            for line_number, line in enumerate(text.splitlines(), start=1):
                if len(line.encode("utf-8")) > 16 * 1024:
                    raise RepositoryLimitError(f"search line exceeds 16 KiB: {relative}:{line_number}")
                if not matcher(line):
                    continue
                masked_line, masked = mask_text(line)
                matches.append(
                    SearchMatch(
                        file=relative,
                        line=line_number,
                        text=masked_line,
                        masked=masked,
                    )
                )
                evidence.append(
                    self._evidence(
                        relative,
                        line_number,
                        line_number,
                        masked_line,
                        "search_text",
                        digest,
                        masked,
                    )
                )
                if len(matches) >= self._limits.matches_per_search:
                    truncated = True
                    break
            if truncated:
                break
        return ToolObservation(
            operation="search_text",
            target=pattern,
            content=matches,
            evidence=evidence,
            truncated=truncated,
        )

    def read_lines(self, path: str, line_start: int, line_end: int) -> ToolObservation:
        relative, text, digest, actual_end = self._read_range(path, line_start, line_end)
        cache_key = (digest, line_start, actual_end, "read_lines")
        if cache_key in self._observation_cache:
            return self._observation_cache[cache_key].model_copy(update={"cached": True})
        self._consume_target()
        masked_text, masked = mask_text(text)
        observation = ToolObservation(
            operation="read_lines",
            target=relative,
            content=masked_text,
            evidence=[
                self._evidence(
                    relative,
                    line_start,
                    actual_end,
                    masked_text.rstrip("\r\n"),
                    "read_lines",
                    digest,
                    masked,
                )
            ],
        )
        self._observation_cache[cache_key] = observation
        return observation

    def file_info(self, path: str) -> ToolObservation:
        resolved, relative = self._resolve_file(path)
        data, digest = self._read_bytes(resolved, relative)
        return ToolObservation(
            operation="file_info",
            target=relative,
            content={
                "path": relative,
                "size": len(data),
                "digest": digest,
                "binary": False,
                "source_context": _source_context(relative),
            },
        )

    def parse_structured(
        self, path: str, line_start: int, line_end: int
    ) -> ToolObservation:
        relative, text, digest, actual_end = self._read_range(path, line_start, line_end)
        method = _structured_method(relative)
        cache_key = (digest, line_start, actual_end, method)
        if cache_key in self._observation_cache:
            return self._observation_cache[cache_key].model_copy(update={"cached": True})
        self._consume_target()
        parsed = _parse_structured(relative, text, method)
        masked_value, value_masked = _mask_value(parsed)
        masked_excerpt, excerpt_masked = mask_text(text)
        observation = ToolObservation(
            operation="parse_structured",
            target=relative,
            content=masked_value,
            evidence=[
                self._evidence(
                    relative,
                    line_start,
                    actual_end,
                    masked_excerpt.rstrip("\r\n"),
                    method,
                    digest,
                    value_masked or excerpt_masked,
                )
            ],
        )
        self._observation_cache[cache_key] = observation
        return observation

    def _candidate_files(self, paths: list[str]) -> list[str]:
        if not paths:
            raise RepositoryAccessError("search_text requires at least one path")
        normalized = [_normal_path(path) for path in paths]
        for path in normalized:
            self._resolve(path)
        return sorted(
            entry.path
            for entry in self.scan().entries
            if entry.kind == "file"
            and any(
                prefix == "."
                or entry.path == prefix
                or entry.path.startswith(prefix + "/")
                for prefix in normalized
            )
        )

    def _read_range(
        self, path: str, line_start: int, line_end: int
    ) -> tuple[str, str, str, int]:
        if line_start < 1 or line_end < line_start:
            raise RepositoryAccessError("invalid line range")
        if line_end - line_start + 1 > self._limits.lines_per_read:
            raise RepositoryLimitError("lines_per_read limit exceeded")
        resolved, relative = self._resolve_file(path)
        data, digest = self._read_bytes(resolved, relative)
        text = _decode_text(data, relative)
        lines = text.splitlines(keepends=True)
        if line_start > max(len(lines), 1):
            raise RepositoryAccessError(f"line_start is outside file: {relative}")
        actual_end = min(line_end, max(len(lines), 1))
        selected = "".join(lines[line_start - 1 : actual_end])
        return relative, selected, digest, actual_end

    def _read_text(self, relative: str) -> tuple[str, str]:
        resolved, normalized = self._resolve_file(relative)
        data, digest = self._read_bytes(resolved, normalized)
        return _decode_text(data, normalized), digest

    def _read_bytes(self, resolved: Path, relative: str) -> tuple[bytes, str]:
        try:
            stat = resolved.stat()
        except OSError as exc:
            raise RepositoryAccessError(f"file cannot be inspected: {relative}") from exc
        if stat.st_size > self._limits.single_file_bytes:
            raise RepositoryLimitError(f"single_file_bytes limit exceeded: {relative}")
        stat_key = (stat.st_mtime_ns, stat.st_size)
        cached = self._file_cache.get(resolved)
        if cached and cached[0] == stat_key:
            return cached[1], cached[2]
        try:
            data = resolved.read_bytes()
        except OSError as exc:
            raise RepositoryAccessError(f"file cannot be read: {relative}") from exc
        self._physical_reads += 1
        if b"\x00" in data:
            raise RepositoryAccessError(f"binary file cannot be read: {relative}")
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        self._file_cache[resolved] = (stat_key, data, digest)
        return data, digest

    def _resolve_file(self, path: str) -> tuple[Path, str]:
        resolved, relative = self._resolve(path)
        if not resolved.is_file():
            raise RepositoryAccessError(f"target is not a regular file: {relative}")
        return resolved, relative

    def _resolve(self, path: str) -> tuple[Path, str]:
        normalized = _normal_path(path)
        pure = PurePosixPath(normalized)
        if normalized.startswith("/") or ".." in pure.parts or "\x00" in normalized:
            raise RepositoryAccessError(f"path resolves outside repository: {path}")
        candidate = self._root if normalized == "." else self._root / Path(*pure.parts)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise RepositoryAccessError(f"repository path does not exist: {normalized}") from exc
        if resolved != self._root and self._root not in resolved.parents:
            raise RepositoryAccessError(f"path resolves outside repository: {path}")
        relative = "." if resolved == self._root else resolved.relative_to(self._root).as_posix()
        return resolved, relative

    def _consume_target(self) -> None:
        if self._selected_targets >= self._limits.selected_targets:
            raise RepositoryLimitError("selected_targets limit exhausted")
        self._selected_targets += 1

    def _evidence(
        self,
        relative: str,
        line_start: int,
        line_end: int,
        excerpt: str,
        method: ExtractionMethod,
        digest: str,
        masked: bool,
    ) -> EvidenceItem:
        identifier = f"E{self._next_evidence_number:03d}"
        self._next_evidence_number += 1
        return EvidenceItem(
            id=identifier,
            file=relative,
            line_start=line_start,
            line_end=line_end,
            excerpt=excerpt,
            extraction_method=method,
            source_context=_source_context(relative),
            digest=digest,
            masked=masked,
        )

    def _resolve_revision(
        self, entries: list[ScanEntry]
    ) -> tuple[str, str]:
        if self._requested_revision:
            return self._requested_revision, "requested"
        try:
            completed = subprocess.run(
                ["git", "-C", str(self._root), "rev-parse", "--verify", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed and completed.returncode == 0:
            revision = completed.stdout.strip()
            if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision):
                return revision.lower(), "git"
        payload = json.dumps(
            [entry.model_dump(mode="json") for entry in entries],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest(), "tree_digest"


def mask_text(text: str) -> tuple[str, bool]:
    masked = False
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        match = _ASSIGNMENT.match(line)
        if match and SECRET_NAME.search(match.group(1)):
            ending = match.group(4) or ""
            lines.append(f"{match.group(1)}{match.group(2)}[REDACTED]{ending}")
            masked = True
        else:
            replaced, count = _JSON_SECRET.subn(r'\1"[REDACTED]"', line)
            lines.append(replaced)
            masked = masked or count > 0
    return "".join(lines), masked


def _mask_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        masked = False
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if SECRET_NAME.search(str(key)):
                result[key] = "[REDACTED]"
                masked = True
            else:
                result[key], item_masked = _mask_value(item)
                masked = masked or item_masked
        return result, masked
    if isinstance(value, list):
        result = []
        masked = False
        for item in value:
            transformed, item_masked = _mask_value(item)
            result.append(transformed)
            masked = masked or item_masked
        return result, masked
    return value, False


def _normal_path(path: str) -> str:
    if "\x00" in path:
        raise RepositoryAccessError("path contains NUL byte")
    normalized = path.replace("\\", "/").rstrip("/") or "."
    return normalized[2:] if normalized.startswith("./") else normalized


def _source_context(path: str) -> SourceContext:
    parts = {part.lower() for part in PurePosixPath(path).parts}
    for context, names in SOURCE_CONTEXT_PARTS:
        if parts & names:
            return context
    return "primary"


def _decode_text(data: bytes, relative: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepositoryAccessError(f"binary or non-UTF-8 file cannot be read: {relative}") from exc


def _compile_matcher(pattern: str, regex: bool):
    if not regex:
        return lambda line: pattern in line
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise RepositoryAccessError(f"invalid regular expression: {exc}") from exc
    return lambda line: compiled.search(line) is not None


def _structured_method(relative: str) -> ExtractionMethod:
    lower = relative.lower()
    if lower.endswith(".json"):
        return "structured_json"
    if lower.endswith((".yaml", ".yml")):
        return "structured_yaml"
    if lower.endswith(".xml"):
        return "structured_xml"
    if lower.endswith(".toml"):
        return "structured_toml"
    if lower.endswith(".properties"):
        return "structured_properties"
    raise UnsupportedFormatError(f"unsupported structured format: {relative}")


def _parse_structured(relative: str, text: str, method: ExtractionMethod) -> Any:
    try:
        if method == "structured_json":
            return json.loads(text)
        if method == "structured_yaml":
            return YAML(typ="safe").load(text)
        if method == "structured_xml":
            return _xml_value(ET.fromstring(text))
        if method == "structured_toml":
            return tomllib.loads(text)
        if method == "structured_properties":
            return _parse_properties(text)
    except (ET.ParseError, ValueError, TypeError) as exc:
        raise UnsupportedFormatError(f"cannot parse selected range: {relative}: {exc}") from exc
    raise UnsupportedFormatError(f"unsupported structured format: {relative}")


def _xml_value(element: ET.Element) -> dict[str, Any]:
    return {
        "tag": element.tag,
        "attributes": dict(sorted(element.attrib.items())),
        "text": (element.text or "").strip(),
        "children": [_xml_value(child) for child in element],
    }


def _parse_properties(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        match = re.match(r"((?:\\.|[^:=\s])+)(?:\s*[:=]\s*|\s+)(.*)$", line)
        if not match:
            result[line.replace("\\:", ":").replace("\\=", "=")] = ""
            continue
        key = match.group(1).replace("\\:", ":").replace("\\=", "=")
        result[key] = match.group(2)
    return result
