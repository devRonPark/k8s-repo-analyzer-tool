"""OpenAI-compatible Chat Completions adapter for structured model output."""

from __future__ import annotations

import hashlib
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .contracts import (
    ModelCompletion,
    ModelRequest,
    ModelResponseMetadata,
    PROMPT_VERSION,
)
from .ports import (
    ModelClientError,
    ModelProtocolError,
    ModelSchemaError,
    ModelUnavailableError,
)

TModel = TypeVar("TModel", bound=BaseModel)


class OpenAICompatibleModelClient:
    """Validate structured output from an OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_seconds: float = 60,
        schema_repairs: int = 1,
    ) -> None:
        if schema_repairs not in {0, 1}:
            raise ValueError("schema_repairs must be 0 or 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not model.strip():
            raise ValueError("model must not be empty")
        self._endpoint = _endpoint(base_url)
        self._endpoint_identifier = urllib.parse.urlsplit(self._endpoint).netloc
        self._model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._schema_repairs = schema_repairs

    def complete(
        self, request: ModelRequest, response_model: type[TModel]
    ) -> ModelCompletion[TModel]:
        messages = [message.model_dump(mode="json") for message in request.messages]
        tool_name = _submission_tool_name(request.stage)
        last_error = "structured response was invalid"
        for attempt in range(1, self._schema_repairs + 2):
            body = {
                "model": self._model,
                "messages": messages,
                "tools": [
                    *[
                        {
                            "type": "function",
                            "function": tool.model_dump(mode="json"),
                        }
                        for tool in request.tools
                    ],
                    {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": f"Submit a validated {response_model.__name__} result.",
                            "parameters": response_model.model_json_schema(),
                        },
                    },
                ],
                "tool_choice": "auto",
                "temperature": 0,
            }
            payload, raw = self._post(body)
            try:
                value, response_mode = _decode_value(
                    payload, tool_name, response_model
                )
            except ModelSchemaError as exc:
                last_error = str(exc)
                if attempt > self._schema_repairs:
                    raise ModelSchemaError(
                        f"schema repair exhausted: {last_error}"
                    ) from exc
                messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "The previous structured response had a validation error: "
                            f"{last_error}. Return only a valid function call or strict JSON "
                            "matching this schema: "
                            + json.dumps(
                                response_model.model_json_schema(),
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                        ),
                    },
                ]
                continue
            return ModelCompletion[TModel](
                value=value,
                metadata=ModelResponseMetadata(
                    endpoint=self._endpoint_identifier,
                    model=self._model,
                    prompt_version=request.prompt_version or PROMPT_VERSION,
                    response_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
                    attempt_count=attempt,
                    response_mode=response_mode,
                ),
            )
        raise ModelSchemaError(f"schema repair exhausted: {last_error}")

    def _post(self, body: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            ),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout_seconds
            ) as response:
                raw = response.read()
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise ModelUnavailableError(
                f"Chat Completions endpoint is unavailable: {type(exc).__name__}"
            ) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelProtocolError("Chat Completions response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ModelProtocolError("Chat Completions response must be an object")
        return payload, raw


def _endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    parsed = urllib.parse.urlsplit(root)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    if parsed.path.endswith("/responses"):
        raise ValueError("Responses API is not supported")
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1"):
        path += "/v1"
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, path + "/chat/completions", "", "")
    )


def _submission_tool_name(stage: str) -> str:
    if stage == "analysis_plan":
        return "submit_analysis_plan"
    if stage == "topic_analysis":
        return "submit_topic_analysis"
    raise ModelProtocolError(f"unsupported structured completion stage: {stage}")


def _decode_value(
    payload: dict[str, Any], tool_name: str, response_model: type[TModel]
) -> tuple[TModel, str]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelProtocolError("Chat Completions response has no choices")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise ModelProtocolError("Chat Completions choice has no message")
    message = choice["message"]
    raw_value: Any = None
    response_mode = "json_text"
    tool_calls = message.get("tool_calls")
    if tool_calls:
        if not isinstance(tool_calls, list):
            raise ModelProtocolError("message.tool_calls must be an array")
        matching = [
            call
            for call in tool_calls
            if isinstance(call, dict)
            and isinstance(call.get("function"), dict)
            and call["function"].get("name") == tool_name
        ]
        if len(matching) != 1:
            raise ModelProtocolError(
                f"expected exactly one {tool_name} function call"
            )
        arguments = matching[0]["function"].get("arguments")
        if not isinstance(arguments, str):
            raise ModelProtocolError("function arguments must be a JSON string")
        try:
            raw_value = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ModelSchemaError("function arguments are not valid JSON") from exc
        response_mode = "tool_call"
    else:
        content = message.get("content")
        if not isinstance(content, str):
            raise ModelProtocolError("message has neither tool call nor JSON text")
        try:
            raw_value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelSchemaError("message content is not strict JSON") from exc
    try:
        return response_model.model_validate(raw_value), response_mode
    except ValidationError as exc:
        raise ModelSchemaError(str(exc)) from exc
