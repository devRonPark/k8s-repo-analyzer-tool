from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from repository_assessment.contracts import (
    AnalysisPlan,
    ModelMessage,
    ModelRequest,
)
from repository_assessment.openai_compatible import (
    ModelProtocolError,
    ModelSchemaError,
    ModelUnavailableError,
    OpenAICompatibleModelClient,
)
from repository_assessment.recorded import RecordedModelClient, RecordedResponseMismatch


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _chat_response(*, arguments: str | None = None, content: str | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "refusal": None,
        "annotations": [],
    }
    finish_reason = "stop"
    if arguments is not None:
        message["tool_calls"] = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "submit_analysis_plan",
                    "arguments": arguments,
                },
            }
        ]
        finish_reason = "tool_calls"
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1_785_000_000,
        "model": "qwen3-coder",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
                "logprobs": None,
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 6,
            "total_tokens": 18,
        },
    }


def _plan_request() -> ModelRequest:
    return ModelRequest(
        stage="analysis_plan",
        messages=[ModelMessage(role="user", content="Create a bounded plan.")],
    )


def test_function_call_arguments_are_validated_without_sdk_types(monkeypatch) -> None:
    requests = []
    response = _chat_response(arguments='{"round":1,"targets":[],"searches":[]}')

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _FakeResponse(response)

    monkeypatch.setattr(
        "repository_assessment.openai_compatible.urllib.request.urlopen", fake_urlopen
    )
    client = OpenAICompatibleModelClient(
        base_url="http://model.internal:30000",
        model="qwen3-coder",
        api_key="secret",
        timeout_seconds=30,
    )

    completion = client.complete(_plan_request(), AnalysisPlan)

    request, timeout = requests[0]
    body = json.loads(request.data)
    assert completion.value == AnalysisPlan(round=1, targets=[])
    assert request.full_url == "http://model.internal:30000/v1/chat/completions"
    assert timeout == 30
    assert body["tools"][0]["function"]["name"] == "submit_analysis_plan"
    assert body["tools"][0]["function"]["parameters"] == AnalysisPlan.model_json_schema()
    assert request.get_header("Authorization") == "Bearer secret"
    assert "secret" not in completion.metadata.model_dump_json()
    assert completion.metadata.response_mode == "tool_call"


def test_strict_json_text_is_supported_as_fallback(monkeypatch) -> None:
    response = _chat_response(content='{"round":1,"targets":[]}')
    monkeypatch.setattr(
        "repository_assessment.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(response),
    )

    completion = OpenAICompatibleModelClient(
        base_url="http://model/v1",
        model="model",
        api_key=None,
    ).complete(_plan_request(), AnalysisPlan)

    assert completion.value.round == 1
    assert completion.metadata.response_mode == "json_text"


def test_invalid_json_gets_one_repair_then_narrow_failure(monkeypatch) -> None:
    requests = []
    responses = iter([_chat_response(content="{"), _chat_response(content="still invalid")])

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data))
        return _FakeResponse(next(responses))

    monkeypatch.setattr(
        "repository_assessment.openai_compatible.urllib.request.urlopen", fake_urlopen
    )
    client = OpenAICompatibleModelClient(
        base_url="http://model",
        model="model",
        api_key=None,
        schema_repairs=1,
    )

    with pytest.raises(ModelSchemaError, match="schema repair exhausted"):
        client.complete(_plan_request(), AnalysisPlan)

    assert len(requests) == 2
    assert "validation error" in requests[1]["messages"][-1]["content"]


def test_recorded_client_validates_stage_schema_and_exhaustion(tmp_path: Path) -> None:
    fixture = tmp_path / "responses.json"
    fixture.write_text(
        json.dumps(
            {
                "responses": [
                    {
                        "stage": "analysis_plan",
                        "schema_name": "AnalysisPlan",
                        "value": {"round": 1, "targets": []},
                        "metadata": {
                            "endpoint": "recorded",
                            "model": "fixture-model",
                            "prompt_version": "assessment-prompts/v1",
                            "response_digest": "sha256:abc",
                            "attempt_count": 1,
                            "response_mode": "recorded",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    client = RecordedModelClient.from_file(fixture)

    completion = client.complete(_plan_request(), AnalysisPlan)

    assert completion.value.round == 1
    assert completion.metadata.response_mode == "recorded"
    with pytest.raises(RecordedResponseMismatch, match="exhausted"):
        client.complete(_plan_request(), AnalysisPlan)


def test_protocol_errors_are_not_sent_for_schema_repair(monkeypatch) -> None:
    response = _chat_response(arguments='{"round":1,"targets":[]}')
    response["choices"][0]["message"]["tool_calls"][0]["function"][
        "name"
    ] = "unknown_tool"
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        return _FakeResponse(response)

    monkeypatch.setattr(
        "repository_assessment.openai_compatible.urllib.request.urlopen", fake_urlopen
    )

    with pytest.raises(ModelProtocolError, match="submit_analysis_plan"):
        OpenAICompatibleModelClient(
            base_url="http://model", model="model", api_key=None
        ).complete(_plan_request(), AnalysisPlan)

    assert calls == 1


def test_transport_error_is_reported_without_leaking_endpoint_details(monkeypatch) -> None:
    def fail_urlopen(request, timeout):
        raise urllib.error.URLError("connection refused at secret-host")

    monkeypatch.setattr(
        "repository_assessment.openai_compatible.urllib.request.urlopen", fail_urlopen
    )

    with pytest.raises(ModelUnavailableError) as raised:
        OpenAICompatibleModelClient(
            base_url="http://model.internal", model="model", api_key="secret"
        ).complete(_plan_request(), AnalysisPlan)

    assert "secret-host" not in str(raised.value)
    assert "secret" not in str(raised.value)


def test_responses_endpoint_and_extra_schema_repairs_are_rejected() -> None:
    with pytest.raises(ValueError, match="Responses API"):
        OpenAICompatibleModelClient(
            base_url="http://model/v1/responses", model="model", api_key=None
        )
    with pytest.raises(ValueError, match="schema_repairs"):
        OpenAICompatibleModelClient(
            base_url="http://model", model="model", api_key=None, schema_repairs=2
        )
