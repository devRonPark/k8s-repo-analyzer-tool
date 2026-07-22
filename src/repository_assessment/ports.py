"""Injected interfaces used by the assessment engine."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from .contracts import (
    ModelCompletion,
    ModelRequest,
    RepositoryScan,
    RunEvent,
    ToolObservation,
)

TModel = TypeVar("TModel", bound=BaseModel)


class StructuredModelClient(Protocol):
    def complete(
        self, request: ModelRequest, response_model: type[TModel]
    ) -> ModelCompletion[TModel]: ...


class RepositoryTools(Protocol):
    def scan(self) -> RepositoryScan: ...

    def list_tree(self, path: str = ".") -> ToolObservation: ...

    def find_files(self, patterns: list[str]) -> ToolObservation: ...

    def search_text(
        self, pattern: str, paths: list[str], *, regex: bool = False
    ) -> ToolObservation: ...

    def read_lines(self, path: str, line_start: int, line_end: int) -> ToolObservation: ...

    def file_info(self, path: str) -> ToolObservation: ...

    def parse_structured(
        self, path: str, line_start: int, line_end: int
    ) -> ToolObservation: ...


class EventSink(Protocol):
    def emit(self, event: RunEvent) -> None: ...

    def is_cancelled(self) -> bool: ...
