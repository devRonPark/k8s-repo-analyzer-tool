"""Show how an LLM tool call invokes the repository analyzer.

The default dry-run mode is deterministic and needs no API key. Live mode uses
the OpenAI-compatible Chat Completions API with a local function tool
implementation, which works with SGLang runtime endpoints.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from integrations.tool import analyze_repository  # noqa: E402
from repo_analyzer.models import AnalysisResult  # noqa: E402
from repo_analyzer.parsers.dotenv import parse_dotenv  # noqa: E402
from repo_analyzer.reporters.brief_reporter import to_brief  # noqa: E402

DEFAULT_QUESTION = (
    "소스 코드를 직접 읽지 않은 개발자가 Kubernetes 이관 큰 그림을 이해할 수 있게 "
    "7개 migration question 중심으로 요약해줘."
)
MODEL_PREFERENCE_PATTERNS = [
    "gpt-5-mini",
    "gpt-4.1-mini",
    "gpt-4o-mini",
    "qwen",
    "llama",
    "mistral",
    "gemma",
]
NON_CHAT_MODEL_MARKERS = [
    "embedding",
    "embed",
    "rerank",
    "whisper",
    "tts",
    "moderation",
    "vision",
]


def load_responses_tool_schema(path: Path) -> dict[str, Any]:
    """Convert the existing OpenAI-compatible schema to Responses API shape."""

    schema = json.loads(path.read_text(encoding="utf-8"))
    function = schema["function"]
    return {
        "type": "function",
        "name": function["name"],
        "description": function.get("description", ""),
        "parameters": function["parameters"],
        "strict": True,
    }


def load_chat_completions_tool_schema(path: Path) -> dict[str, Any]:
    """Load the existing OpenAI-compatible Chat Completions tool schema."""

    return json.loads(path.read_text(encoding="utf-8"))


def summarize_tool_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the small part of analyzer output useful in an LLM transcript."""

    if not payload.get("ok"):
        return {
            "ok": False,
            "error": payload.get("error", {}),
            "profile": payload.get("profile"),
        }

    analysis = payload["analysis"]
    questions = analysis.get("migration_questions", [])
    coverage = analysis.get("source_coverage", [])
    warnings = analysis.get("warnings", [])
    return {
        "ok": True,
        "repository": analysis.get("repository", {}).get("name"),
        "question_statuses": {
            question.get("id"): question.get("status") for question in questions
        },
        "source_coverage": {
            item.get("source_class"): item.get("status") for item in coverage
        },
        "warnings": [warning.get("code") for warning in warnings],
        "evidence_samples": _evidence_samples(questions, limit=5),
    }


def resolve_openai_settings(
    env_file: Path,
    environ: dict[str, str],
    cli_model: str | None,
    cli_base_url: str | None,
) -> dict[str, str | None]:
    """Resolve OpenAI-compatible endpoint settings.

    Precedence is CLI flags for CLI-exposed values, then process environment,
    then ``.env``, then defaults.
    """

    file_values = _read_env_file(env_file)
    base_url = _first_nonempty(
        cli_base_url,
        environ.get("OPENAI_BASE_URL"),
        file_values.get("OPENAI_BASE_URL"),
        "https://api.openai.com/v1",
    )
    return {
        "api_key": _first_nonempty(environ.get("OPENAI_API_KEY"), file_values.get("OPENAI_API_KEY")),
        "base_url": _normalize_openai_base_url(base_url),
        "model": _first_nonempty(
            cli_model,
            environ.get("OPENAI_MODEL"),
            file_values.get("OPENAI_MODEL"),
        ),
    }


def fetch_models(base_url: str, api_key: str | None) -> list[dict[str, Any]]:
    """Fetch models from an OpenAI-compatible ``/models`` endpoint."""

    endpoint = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(
        endpoint,
        headers=_request_headers(api_key),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Models API request failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Models API request failed: {exc}") from exc
    data = payload.get("data")
    return data if isinstance(data, list) else []


def select_default_model(models: list[dict[str, Any]]) -> str | None:
    """Pick a likely chat/generation model without blindly using the first item."""

    ids = [
        str(model.get("id"))
        for model in models
        if model.get("id") and _is_likely_chat_model(str(model.get("id")))
    ]
    for pattern in MODEL_PREFERENCE_PATTERNS:
        for model_id in ids:
            if pattern in model_id.lower():
                return model_id
    return ids[0] if ids else None


def build_dry_run_transcript(
    repository_path: str,
    question: str = DEFAULT_QUESTION,
    build_system: str = "auto",
    git_ref: str | None = None,
) -> list[dict[str, Any]]:
    """Build a deterministic transcript that mirrors a real tool-call loop."""

    args = {
        "repository_path": repository_path,
        "profile": "kubernetes-p0",
        "build_system": build_system,
    }
    if git_ref:
        args["git_ref"] = git_ref
    payload = analyze_repository(**args)
    summary = summarize_tool_output(payload)
    return [
        {
            "stage": "request",
            "content": question,
            "tool_choice": "required",
            "available_tools": ["analyze_repository"],
        },
        {
            "stage": "model_tool_call",
            "tool_call": {
                "name": "analyze_repository",
                "arguments": args,
            },
        },
        {
            "stage": "tool_output",
            "summary": summary,
        },
        {
            "stage": "final_answer",
            "content": _dry_run_final_answer(summary),
        },
    ]


def run_live_transcript(
    repository_path: str,
    question: str,
    build_system: str,
    git_ref: str | None,
    model: str,
    base_url: str,
    api_key: str | None,
) -> list[dict[str, Any]]:
    """Run a real Chat Completions tool-call loop and return a compact transcript."""

    tool_schema = load_chat_completions_tool_schema(_ROOT / "integrations/tool-schema.json")
    tool_name = tool_schema["function"]["name"]
    request_message = {"role": "user", "content": question}
    first = _chat_completions_create(
        base_url=base_url,
        api_key=api_key,
        body={
            "model": model,
            "messages": [request_message],
            "tools": [tool_schema],
            "tool_choice": {
                "type": "function",
                "function": {"name": tool_name},
            },
        },
    )
    message = _extract_chat_message(first)
    call = _extract_chat_tool_call(message)
    if call is None:
        return [
            {"stage": "request", "content": question, "tool_choice": "required"},
            {"stage": "model_response", "raw": _compact_json(first)},
            {
                "stage": "error",
                "message": "model did not return a tool_call item",
            },
        ]

    function = call.get("function") or {}
    arguments = json.loads(function.get("arguments") or "{}")
    arguments["repository_path"] = repository_path
    arguments["profile"] = "kubernetes-p0"
    arguments["build_system"] = build_system
    if git_ref:
        arguments["git_ref"] = git_ref
    else:
        arguments.pop("git_ref", None)

    payload = analyze_repository(**arguments)
    summary = summarize_tool_output(payload)
    final_answer_instruction = _build_final_answer_instruction(payload)
    assistant_message = {
        "role": "assistant",
        "content": message.get("content"),
        "tool_calls": [call],
    }
    second = _chat_completions_create(
        base_url=base_url,
        api_key=api_key,
        body={
            "model": model,
            "messages": [
                request_message,
                assistant_message,
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(payload, ensure_ascii=False),
                },
                {
                    "role": "user",
                    "content": final_answer_instruction,
                },
            ],
            "tools": [tool_schema],
        },
    )
    return [
        {"stage": "request", "content": question, "tool_choice": "required"},
        {
            "stage": "model_tool_call",
            "tool_call": {
                "name": function.get("name"),
                "call_id": call.get("id"),
                "arguments": arguments,
            },
        },
        {"stage": "tool_output", "summary": summary},
        {
            "stage": "final_answer",
            "content": _extract_output_text(second),
            "raw_response_id": second.get("id"),
        },
    ]


def _build_final_answer_instruction(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return (
            "The repository analyzer returned an error. Report the failed step and error "
            "from the tool output. Do not replace it with generic Kubernetes advice."
        )

    analysis = payload.get("analysis") or {}
    brief = _deterministic_brief(analysis)
    warnings = _warning_lines(analysis)
    image_risks = _image_runtime_risk_lines(analysis)

    return "\n".join(
        [
            "Use the deterministic analyzer output below as the source of truth for the final answer.",
            "Write the final answer in Korean natural-language Markdown, not as a copied deterministic report.",
            "Use exactly these top-level sections: ## 핵심 요약, ## 7문항 답변, ## 경고와 리스크, ## 추가 결정사항.",
            "For ## 핵심 요약, write 3-5 natural Korean sentences.",
            "For ## 7문항 답변, write one numbered item per migration question, include the status in parentheses, and rewrite each answer in 1-2 Korean sentences.",
            "For ## 경고와 리스크, include every warning code and every image/runtime risk subject, with why it matters for Kubernetes migration.",
            "For ## 추가 결정사항, list unresolved operational inputs concretely; do not collapse them into vague examples.",
            "Do not omit warnings or image/runtime risks.",
            "Preserve confidence/status wording: preserve not_detected, partial, and unresolved statuses; do not turn missing or unresolved inputs into decided Kubernetes values.",
            "When a workload mapping is derived, describe it as a candidate, not as a final manifest.",
            "For derived workload mappings, use '후보' or 'candidate' and do not say it is already configured.",
            "Do not invent replica counts, CPU/memory, PVC sizes, StorageClass, IngressClass, HPA, PDB, DB HA, backup policy, hosts, TLS, or Secret values.",
            "The deterministic brief below is source material only; do not copy it verbatim.",
            "Do not include raw Evidence: lines in the final answer.",
            "",
            "Deterministic brief:",
            brief.rstrip(),
            "",
            "Warnings:",
            "\n".join(warnings) if warnings else "- none",
            "",
            "Image/runtime risks:",
            "\n".join(image_risks) if image_risks else "- none",
        ]
    )


def _deterministic_brief(analysis: dict[str, Any]) -> str:
    try:
        return to_brief(AnalysisResult.model_validate(analysis))
    except Exception:
        questions = analysis.get("migration_questions") or []
        if not questions:
            return "_No migration questions emitted._\n"
        lines = ["# Kubernetes migration brief - " + str(analysis.get("repository", {}).get("name", "unknown")), ""]
        for index, question in enumerate(questions, start=1):
            lines.append(f"### {index}. {question.get('question', question.get('id', 'unknown'))}")
            lines.append(f"**Status:** {question.get('status', 'unknown')}")
            lines.append(f"**Answer:** {question.get('answer', '')}")
            missing = question.get("missing") or []
            lines.append("**Missing:** " + ("; ".join(missing) if missing else "-"))
            lines.append("")
        return "\n".join(lines)


def _warning_lines(analysis: dict[str, Any]) -> list[str]:
    lines = []
    for warning in analysis.get("warnings") or []:
        code = warning.get("code", "warning")
        message = warning.get("message", "")
        path = warning.get("path")
        suffix = f" ({path})" if path else ""
        lines.append(f"- {code}: {message}{suffix}")
    return lines


def _image_runtime_risk_lines(analysis: dict[str, Any]) -> list[str]:
    lines = []
    for finding in analysis.get("container_image") or []:
        subject = finding.get("subject", "container_image")
        value = finding.get("value", "")
        confidence = finding.get("confidence", "")
        effect = finding.get("kubernetes_effect", "")
        lines.append(f"- {subject}: {value} ({confidence}) - {effect}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Demonstrate LLM tool-call output.")
    parser.add_argument("--repo", default="tests/fixtures/jpetstore-6")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--build-system", default="auto", choices=["auto", "gradle", "maven"])
    parser.add_argument("--git-ref", default=None)
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "auto", "live"])
    parser.add_argument(
        "--env-file",
        default=str(_ROOT / ".env"),
        help="path to .env containing OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible base URL; overrides OPENAI_BASE_URL from env/.env",
    )
    args = parser.parse_args(argv)

    settings = resolve_openai_settings(
        env_file=Path(args.env_file),
        environ=dict(os.environ),
        cli_model=args.model,
        cli_base_url=args.base_url,
    )
    api_key = settings["api_key"]
    base_url = settings["base_url"] or "https://api.openai.com/v1"
    mode = args.mode
    if mode == "auto":
        mode = "live" if api_key or not _is_default_openai_base_url(base_url) else "dry-run"
    if mode == "live":
        model = settings["model"]
        if not api_key and _is_default_openai_base_url(base_url):
            print(
                f"error: OPENAI_API_KEY is required for {base_url}",
                file=sys.stderr,
            )
            return 2
        if not model:
            try:
                model = select_default_model(fetch_models(base_url, api_key))
            except RuntimeError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            if not model:
                print(
                    "error: could not auto-select a chat model from /models; "
                    "set OPENAI_MODEL or pass --model",
                    file=sys.stderr,
                )
                return 2
        try:
            transcript = run_live_transcript(
                repository_path=args.repo,
                question=args.question,
                build_system=args.build_system,
                git_ref=args.git_ref,
                model=model,
                base_url=base_url,
                api_key=api_key,
            )
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        transcript = build_dry_run_transcript(
            repository_path=args.repo,
            question=args.question,
            build_system=args.build_system,
            git_ref=args.git_ref,
        )
    print(json.dumps(transcript, ensure_ascii=False, indent=2))
    return 0


def _evidence_samples(questions: list[dict[str, Any]], limit: int) -> list[str]:
    samples: list[str] = []
    for question in questions:
        for basis in question.get("basis", []):
            for evidence in basis.get("evidence", []):
                samples.append(
                    f"{basis.get('source_section')}.{basis.get('subject')} @ "
                    f"{evidence.get('path')}:{evidence.get('start_line')}-{evidence.get('end_line')}"
                )
                if len(samples) >= limit:
                    return samples
    return samples


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    parsed = parse_dotenv(path.read_text(encoding="utf-8"), str(path))
    return {entry.name: entry.value for entry in parsed.entries}


def _is_likely_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(marker in lowered for marker in NON_CHAT_MODEL_MARKERS)


def _first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def _normalize_openai_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return base_url
    stripped = base_url.rstrip("/")
    if stripped.endswith("/v1"):
        return stripped
    return stripped + "/v1"


def _dry_run_final_answer(summary: dict[str, Any]) -> str:
    if not summary.get("ok"):
        error = summary.get("error", {})
        return f"tool 실행 실패: {error.get('type')}: {error.get('message')}"
    statuses = summary["question_statuses"]
    answered = sum(1 for status in statuses.values() if status == "answered")
    partial = sum(1 for status in statuses.values() if status == "partial")
    unresolved = sum(1 for status in statuses.values() if status == "unresolved")
    not_detected = sum(1 for status in statuses.values() if status == "not_detected")
    return (
        f"{summary['repository']} 분석 결과, Kubernetes 이관 질문 7개가 생성되었습니다. "
        f"상태는 answered={answered}, partial={partial}, unresolved={unresolved}, "
        f"not_detected={not_detected}입니다. 세부 값은 tool_output의 근거 파일/라인을 "
        "확인해 사람이 배포 의사결정값을 보완해야 합니다."
    )


def _responses_create(base_url: str, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/responses"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=_request_headers(api_key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Responses API request failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Responses API request failed: {exc}") from exc


def _chat_completions_create(
    base_url: str,
    api_key: str | None,
    body: dict[str, Any],
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=_request_headers(api_key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Chat Completions API request failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Chat Completions API request failed: {exc}") from exc


def _extract_function_call(response: dict[str, Any]) -> dict[str, Any] | None:
    for item in response.get("output", []):
        if item.get("type") == "function_call":
            return item
    return None


def _extract_chat_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices") or []
    if not choices:
        return {}
    message = choices[0].get("message")
    return message if isinstance(message, dict) else {}


def _extract_chat_tool_call(message: dict[str, Any]) -> dict[str, Any] | None:
    tool_calls = message.get("tool_calls") or []
    for call in tool_calls:
        if call.get("type") == "function":
            return call
    return None


def _request_headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _is_default_openai_base_url(base_url: str) -> bool:
    return base_url.rstrip("/") == "https://api.openai.com/v1"


def _extract_output_text(response: dict[str, Any]) -> str:
    message = _extract_chat_message(response)
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        ]
        return "\n".join(chunk for chunk in chunks if chunk).strip()

    chunks: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(content.get("text", ""))
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def _compact_json(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id"),
        "output": payload.get("output", [])[:3],
    }


if __name__ == "__main__":
    raise SystemExit(main())
