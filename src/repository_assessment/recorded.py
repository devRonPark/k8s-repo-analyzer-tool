"""Offline structured-model adapter for deterministic replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .contracts import (
    ModelCompletion,
    ModelRequest,
    RecordedCompletion,
    RecordedCompletionFile,
)

TModel = TypeVar("TModel", bound=BaseModel)


class RecordedResponseMismatch(RuntimeError):
    """Raised when a replay fixture does not match the requested completion."""


class RecordedModelClient:
    """Consume an exact sequence of schema-validated recorded completions."""

    def __init__(self, responses: tuple[RecordedCompletion, ...]) -> None:
        self._responses = responses
        self._index = 0

    @classmethod
    def from_file(cls, path: str | Path) -> RecordedModelClient:
        fixture_path = Path(path)
        try:
            raw = json.loads(fixture_path.read_text(encoding="utf-8"))
            fixture = RecordedCompletionFile.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RecordedResponseMismatch(
                f"recorded response file is invalid: {fixture_path}"
            ) from exc
        return cls(tuple(fixture.responses))

    def complete(
        self, request: ModelRequest, response_model: type[TModel]
    ) -> ModelCompletion[TModel]:
        if self._index >= len(self._responses):
            raise RecordedResponseMismatch("recorded response sequence is exhausted")
        response = self._responses[self._index]
        self._index += 1
        if response.stage != request.stage:
            raise RecordedResponseMismatch(
                f"recorded stage {response.stage} does not match {request.stage}"
            )
        if response.schema_name != response_model.__name__:
            raise RecordedResponseMismatch(
                f"recorded schema {response.schema_name} does not match "
                f"{response_model.__name__}"
            )
        try:
            value = response_model.model_validate(response.value)
        except ValidationError as exc:
            raise RecordedResponseMismatch(
                f"recorded value does not match {response_model.__name__}"
            ) from exc
        return ModelCompletion[TModel](value=value, metadata=response.metadata)

    def assert_consumed(self) -> None:
        remaining = len(self._responses) - self._index
        if remaining:
            raise RecordedResponseMismatch(
                f"recorded response sequence has {remaining} unused responses"
            )
