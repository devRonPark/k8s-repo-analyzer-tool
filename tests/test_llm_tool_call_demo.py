import importlib.util
import json
import urllib.error
from pathlib import Path


def _load_script():
    path = Path("scripts/llm_tool_call_demo.py")
    spec = importlib.util.spec_from_file_location("llm_tool_call_demo", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_converts_existing_tool_schema_to_responses_function_tool():
    module = _load_script()

    tool = module.load_responses_tool_schema(Path("integrations/tool-schema.json"))

    assert tool["type"] == "function"
    assert tool["name"] == "analyze_repository"
    assert "parameters" in tool
    assert tool["parameters"]["required"] == ["repository_path"]


def test_summarizes_tool_output_for_llm_transcript():
    module = _load_script()
    payload = {
        "ok": True,
        "analysis": {
            "repository": {"name": "jpetstore-6"},
            "migration_questions": [
                {
                    "id": "application_identity",
                    "status": "answered",
                    "answer": "Java web app",
                    "basis": [
                        {
                            "source_section": "components",
                            "subject": "webapp.runtime",
                            "evidence": [{"path": "pom.xml", "start_line": 1, "end_line": 2}],
                        }
                    ],
                    "missing": [],
                }
            ],
            "source_coverage": [
                {"source_class": "dockerfile", "status": "present"},
                {"source_class": "kubernetes", "status": "missing"},
            ],
            "warnings": [{"code": "jdk_version_mismatch"}],
        },
    }

    summary = module.summarize_tool_output(payload)

    assert summary["ok"] is True
    assert summary["repository"] == "jpetstore-6"
    assert summary["question_statuses"] == {"application_identity": "answered"}
    assert summary["source_coverage"] == {"dockerfile": "present", "kubernetes": "missing"}
    assert summary["warnings"] == ["jdk_version_mismatch"]
    assert summary["evidence_samples"] == ["components.webapp.runtime @ pom.xml:1-2"]


def test_builds_dry_run_transcript_with_real_tool_output():
    module = _load_script()

    transcript = module.build_dry_run_transcript(
        repository_path="tests/fixtures/jpetstore-6",
        question="이 repo의 Kubernetes 이관 큰 그림을 알려줘.",
        build_system="auto",
    )

    stages = [item["stage"] for item in transcript]
    assert stages == ["request", "model_tool_call", "tool_output", "final_answer"]
    assert transcript[1]["tool_call"]["name"] == "analyze_repository"
    assert transcript[1]["tool_call"]["arguments"]["repository_path"] == "tests/fixtures/jpetstore-6"
    assert transcript[2]["summary"]["ok"] is True
    assert len(transcript[2]["summary"]["question_statuses"]) == 7
    assert "Kubernetes 이관 질문 7개" in transcript[3]["content"]


def test_reads_openai_compatible_settings_from_env_file(tmp_path):
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=from-file",
                "OPENAI_BASE_URL=http://localhost:11434/v1",
            ]
        )
    )

    settings = module.resolve_openai_settings(
        env_file=env_file,
        environ={},
        cli_model=None,
        cli_base_url=None,
    )

    assert settings == {
        "api_key": "from-file",
        "base_url": "http://localhost:11434/v1",
        "model": None,
    }


def test_sglang_root_base_url_from_env_file_is_normalized_to_v1(tmp_path):
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_BASE_URL=http://sglang-runtime:30000\n")

    settings = module.resolve_openai_settings(
        env_file=env_file,
        environ={},
        cli_model=None,
        cli_base_url=None,
    )

    assert settings["base_url"] == "http://sglang-runtime:30000/v1"


def test_environment_and_cli_override_env_file(tmp_path):
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=from-file",
                "OPENAI_BASE_URL=http://file-server/v1",
                "OPENAI_MODEL=file-model",
            ]
        )
    )

    settings = module.resolve_openai_settings(
        env_file=env_file,
        environ={
            "OPENAI_API_KEY": "from-env",
            "OPENAI_BASE_URL": "http://env-server/v1",
            "OPENAI_MODEL": "env-model",
        },
        cli_model="cli-model",
        cli_base_url="http://cli-server/v1",
    )

    assert settings == {
        "api_key": "from-env",
        "base_url": "http://cli-server/v1",
        "model": "cli-model",
    }


def test_live_mode_uses_env_file_settings(tmp_path, monkeypatch, capsys):
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=file-key",
                "OPENAI_BASE_URL=http://compatible-endpoint/v1",
                "OPENAI_MODEL=file-model",
            ]
        )
    )
    seen = {}

    def fake_run_live_transcript(**kwargs):
        seen.update(kwargs)
        return [{"stage": "ok"}]

    monkeypatch.setattr(module, "run_live_transcript", fake_run_live_transcript)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    exit_code = module.main(["--mode", "live", "--env-file", str(env_file)])

    assert exit_code == 0
    assert seen["api_key"] == "file-key"
    assert seen["base_url"] == "http://compatible-endpoint/v1"
    assert seen["model"] == "file-model"
    assert '"stage": "ok"' in capsys.readouterr().out


def test_live_mode_resolves_github_url_from_question_when_repo_is_omitted(
    tmp_path, monkeypatch, capsys
):
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=http://compatible-endpoint/v1",
                "OPENAI_MODEL=file-model",
            ]
        )
    )
    seen = {}

    def fake_clone(repo_url, workdir):
        seen["repo_url"] = repo_url
        seen["workdir"] = workdir
        return tmp_path / "cloned-jpetstore"

    def fake_current_commit(repo_dir):
        seen["commit_repo_dir"] = repo_dir
        return "abc123"

    def fake_run_live_transcript(**kwargs):
        seen["live"] = kwargs
        return [{"stage": "ok"}]

    monkeypatch.setattr(module, "clone_or_update_github_url", fake_clone)
    monkeypatch.setattr(module, "current_git_commit", fake_current_commit)
    monkeypatch.setattr(module, "run_live_transcript", fake_run_live_transcript)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    exit_code = module.main(
        [
            "--mode",
            "live",
            "--env-file",
            str(env_file),
            "--question",
            "https://github.com/mybatis/jpetstore-6 이거 Kubernetes 이관 관점에서 분석해줘.",
        ]
    )

    assert exit_code == 0
    assert seen["repo_url"] == "https://github.com/mybatis/jpetstore-6"
    assert seen["live"]["repository_path"] == str(tmp_path / "cloned-jpetstore")
    assert seen["live"]["git_ref"] == "abc123"
    assert '"stage": "ok"' in capsys.readouterr().out


def test_selects_default_model_from_models_endpoint_response():
    module = _load_script()

    model = module.select_default_model(
        [
            {"id": "text-embedding-3-small"},
            {"id": "qwen2.5-coder:7b"},
            {"id": "rerank-lite"},
        ]
    )

    assert model == "qwen2.5-coder:7b"


def test_model_selection_prefers_explicit_low_cost_candidates():
    module = _load_script()

    model = module.select_default_model(
        [
            {"id": "llama3.1:8b"},
            {"id": "gpt-5-mini"},
            {"id": "qwen2.5-coder:7b"},
        ]
    )

    assert model == "gpt-5-mini"


def test_model_selection_rejects_non_chat_models():
    module = _load_script()

    model = module.select_default_model(
        [
            {"id": "text-embedding-3-small"},
            {"id": "bge-reranker-v2"},
        ]
    )

    assert model is None


def test_live_mode_fetches_default_model_when_env_file_omits_model(
    tmp_path, monkeypatch, capsys
):
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=file-key",
                "OPENAI_BASE_URL=http://compatible-endpoint/v1",
            ]
        )
    )
    seen = {}

    def fake_fetch_models(base_url, api_key):
        seen["fetch"] = {"base_url": base_url, "api_key": api_key}
        return [{"id": "text-embedding-3-small"}, {"id": "qwen2.5-coder:7b"}]

    def fake_run_live_transcript(**kwargs):
        seen["live"] = kwargs
        return [{"stage": "ok"}]

    monkeypatch.setattr(module, "fetch_models", fake_fetch_models)
    monkeypatch.setattr(module, "run_live_transcript", fake_run_live_transcript)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    exit_code = module.main(["--mode", "live", "--env-file", str(env_file)])

    assert exit_code == 0
    assert seen["fetch"] == {
        "base_url": "http://compatible-endpoint/v1",
        "api_key": "file-key",
    }
    assert seen["live"]["model"] == "qwen2.5-coder:7b"
    assert '"stage": "ok"' in capsys.readouterr().out


def test_live_mode_reports_when_default_model_cannot_be_selected(
    tmp_path, monkeypatch, capsys
):
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=file-key",
                "OPENAI_BASE_URL=http://compatible-endpoint/v1",
            ]
        )
    )

    monkeypatch.setattr(module, "fetch_models", lambda base_url, api_key: [])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    exit_code = module.main(["--mode", "live", "--env-file", str(env_file)])

    assert exit_code == 2
    assert "could not auto-select a chat model" in capsys.readouterr().err


def test_live_mode_reports_chat_completions_transport_errors(tmp_path, monkeypatch, capsys):
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=file-key",
                "OPENAI_BASE_URL=http://compatible-endpoint/v1",
                "OPENAI_MODEL=file-model",
            ]
        )
    )

    def fail_chat_completion(**kwargs):
        raise RuntimeError("Chat Completions API request failed: <urlopen error blocked>")

    monkeypatch.setattr(module, "_chat_completions_create", fail_chat_completion)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    exit_code = module.main(["--mode", "live", "--env-file", str(env_file)])

    assert exit_code == 2
    assert "Chat Completions API request failed" in capsys.readouterr().err


def test_live_transcript_uses_chat_completions_endpoint_for_tool_calls(monkeypatch):
    module = _load_script()
    requests = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        requests.append({"url": request.full_url, "body": body})
        if len(requests) == 1:
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "analyze_repository",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            )
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "final summary",
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        module,
        "analyze_repository",
        lambda **kwargs: {
            "ok": True,
            "analysis": {
                "repository": {"name": "demo"},
                "migration_questions": [],
                "source_coverage": [],
                "warnings": [],
            },
        },
    )

    transcript = module.run_live_transcript(
        repository_path="tests/fixtures/jpetstore-6",
        question="요약해줘",
        build_system="auto",
        git_ref=None,
        model="qwen",
        base_url="http://sglang-runtime:30000/v1",
        api_key="dummy",
    )

    assert requests[0]["url"] == "http://sglang-runtime:30000/v1/chat/completions"
    assert requests[1]["url"] == "http://sglang-runtime:30000/v1/chat/completions"
    assert requests[0]["body"]["tools"][0]["type"] == "function"
    assert requests[0]["body"]["tool_choice"] == {
        "type": "function",
        "function": {"name": "analyze_repository"},
    }
    assert requests[1]["body"]["messages"][2]["role"] == "tool"
    assert transcript[-1]["content"] == "final summary"


def test_live_transcript_uses_cli_repository_arguments_over_model_arguments(monkeypatch):
    module = _load_script()
    seen = {}

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    responses = [
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "analyze_repository",
                                    "arguments": json.dumps(
                                        {
                                            "repository_path": "/tmp/repo",
                                            "profile": "wrong",
                                            "build_system": "maven",
                                            "git_ref": "model-ref",
                                        }
                                    ),
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": {"role": "assistant", "content": "final summary"}}]},
    ]

    def fake_urlopen(request, timeout):
        return FakeResponse(responses.pop(0))

    def fake_analyze_repository(**kwargs):
        seen.update(kwargs)
        return {
            "ok": True,
            "analysis": {
                "repository": {"name": "demo"},
                "migration_questions": [],
                "source_coverage": [],
                "warnings": [],
            },
        }

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module, "analyze_repository", fake_analyze_repository)

    transcript = module.run_live_transcript(
        repository_path="tests/fixtures/jpetstore-6",
        question="요약해줘",
        build_system="auto",
        git_ref=None,
        model="qwen",
        base_url="http://sglang-runtime:30000/v1",
        api_key="dummy",
    )

    assert seen == {
        "repository_path": "tests/fixtures/jpetstore-6",
        "profile": "kubernetes-p0",
        "build_system": "auto",
    }
    assert transcript[1]["tool_call"]["arguments"] == seen


def test_live_transcript_injects_brief_and_risk_contract_for_final_answer(monkeypatch):
    module = _load_script()
    requests = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    responses = [
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "analyze_repository",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": {"role": "assistant", "content": "final summary"}}]},
    ]

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse(responses.pop(0))

    def fake_analyze_repository(**kwargs):
        return {
            "ok": True,
            "analysis": {
                "schema_version": "1.0",
                "repository": {
                    "name": "jpetstore-6",
                    "profile": "kubernetes-p0",
                    "git_ref": None,
                    "file_count": 8,
                },
                "detected_files": [],
                "source_coverage": [],
                "migration_questions": [
                    {
                        "id": "application_identity",
                        "question": "어떤 애플리케이션인가?",
                        "status": "answered",
                        "answer": "jpetstore: Java 17 web application (WAR)",
                        "basis": [],
                        "missing": [],
                    },
                    {
                        "id": "persistent_data",
                        "question": "어떤 데이터가 영속되어야 하는가?",
                        "status": "partial",
                        "answer": "No application PVC was detected.",
                        "basis": [],
                        "missing": ["external database persistence decision"],
                    },
                ],
                "components": [],
                "workload_mappings": [],
                "networking": [],
                "configuration": [],
                "secrets": [],
                "storage": [],
                "runtime_dependencies": [],
                "startup_order": [],
                "health_checks": [],
                "build_time_constraints": [],
                "container_image": [
                    {
                        "subject": "image.signal_handling",
                        "value": "Maven runs as PID 1 (shell form CMD)",
                        "confidence": "derived",
                        "kubernetes_effect": "graceful shutdown risk",
                        "evidence": [],
                    }
                ],
                "unresolved_operational_inputs": [
                    {
                        "subject": "replica_count",
                        "reason": "desired availability is an operational decision",
                        "needed_input": "target replicas per Deployment",
                        "kubernetes_effect": "Deployment.spec.replicas",
                        "no_default_used": True,
                    }
                ],
                "warnings": [
                    {
                        "code": "jdk_version_mismatch",
                        "message": "Dockerfile base image targets Java 25, but the POM builds for Java 17.",
                        "path": "Dockerfile",
                    }
                ],
                "unsupported_constructs": [],
            },
        }

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module, "analyze_repository", fake_analyze_repository)

    module.run_live_transcript(
        repository_path="tests/fixtures/jpetstore-6",
        question="요약해줘",
        build_system="auto",
        git_ref=None,
        model="qwen",
        base_url="http://sglang-runtime:30000/v1",
        api_key="dummy",
    )

    final_instruction = requests[1]["messages"][-1]
    assert final_instruction["role"] == "user"
    assert "Kubernetes migration brief - jpetstore-6" in final_instruction["content"]
    assert "Allowed final-answer content is limited to" in final_instruction["content"]
    assert "jdk_version_mismatch" in final_instruction["content"]
    assert "image.signal_handling" in final_instruction["content"]
    assert "Use not_detected, partial, and unresolved as explicit status labels" in final_instruction["content"]
    assert "Write the final answer in Korean natural-language Markdown" in final_instruction["content"]
    assert "## 핵심 요약" in final_instruction["content"]
    assert "## 7문항 답변" in final_instruction["content"]
    assert "## 경고와 리스크" in final_instruction["content"]
    assert "## 추가 결정사항" in final_instruction["content"]
    assert "source material for rewriting into the required sections" in final_instruction["content"]
    assert "Include compact source references only when needed" in final_instruction["content"]
    assert "use '후보' or 'candidate' for derived workload mappings" in final_instruction["content"]
    assert "Allowed derived-workload phrasing" in final_instruction["content"]
    assert "Start each warning/risk bullet with the exact warning code or risk subject" in final_instruction["content"]
    assert "Think and check internally in English" in final_instruction["content"]
    assert "output only the Korean Markdown final answer" in final_instruction["content"]
    assert "<deterministic_brief>" in final_instruction["content"]
    assert "</deterministic_brief>" in final_instruction["content"]
    assert "<warnings>" in final_instruction["content"]
    assert "<image_runtime_risks>" in final_instruction["content"]
    assert "Before writing the final answer, silently verify" in final_instruction["content"]
    assert "all final content is inside the allowed scope" in final_instruction["content"]


def test_responses_create_wraps_url_errors(monkeypatch):
    module = _load_script()

    def fail_urlopen(request, timeout):
        raise urllib.error.URLError(PermissionError("blocked"))

    monkeypatch.setattr(module.urllib.request, "urlopen", fail_urlopen)

    try:
        module._responses_create(
            base_url="http://compatible-endpoint/v1",
            api_key="file-key",
            body={"model": "file-model"},
        )
    except RuntimeError as exc:
        assert "Responses API request failed" in str(exc)
        assert "blocked" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_live_mode_allows_base_url_only_for_compatible_endpoint(
    tmp_path, monkeypatch, capsys
):
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_BASE_URL=http://localhost:11434/v1\n")
    seen = {}

    def fake_fetch_models(base_url, api_key):
        seen["fetch"] = {"base_url": base_url, "api_key": api_key}
        return [{"id": "qwen2.5-coder:7b"}]

    def fake_run_live_transcript(**kwargs):
        seen["live"] = kwargs
        return [{"stage": "ok"}]

    monkeypatch.setattr(module, "fetch_models", fake_fetch_models)
    monkeypatch.setattr(module, "run_live_transcript", fake_run_live_transcript)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    exit_code = module.main(["--mode", "live", "--env-file", str(env_file)])

    assert exit_code == 0
    assert seen["fetch"] == {"base_url": "http://localhost:11434/v1", "api_key": None}
    assert seen["live"]["api_key"] is None
    assert seen["live"]["model"] == "qwen2.5-coder:7b"
    assert '"stage": "ok"' in capsys.readouterr().out


def test_auto_mode_uses_live_when_only_compatible_base_url_is_configured(
    tmp_path, monkeypatch, capsys
):
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_BASE_URL=http://localhost:11434/v1\n")
    seen = {}

    monkeypatch.setattr(
        module,
        "fetch_models",
        lambda base_url, api_key: [{"id": "qwen2.5-coder:7b"}],
    )

    def fake_run_live_transcript(**kwargs):
        seen.update(kwargs)
        return [{"stage": "ok"}]

    monkeypatch.setattr(module, "run_live_transcript", fake_run_live_transcript)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    exit_code = module.main(["--mode", "auto", "--env-file", str(env_file)])

    assert exit_code == 0
    assert seen["base_url"] == "http://localhost:11434/v1"
    assert seen["api_key"] is None
    assert seen["model"] == "qwen2.5-coder:7b"
    assert '"stage": "ok"' in capsys.readouterr().out


def test_live_mode_requires_api_key_for_default_openai_endpoint(
    tmp_path, capsys, monkeypatch
):
    module = _load_script()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    exit_code = module.main(
        ["--mode", "live", "--env-file", str(tmp_path / "missing.env")]
    )

    assert exit_code == 2
    assert "OPENAI_API_KEY is required for https://api.openai.com/v1" in capsys.readouterr().err


def test_final_answer_instruction_prefers_workload_profiles():
    module = _load_script()
    payload = {
        "ok": True,
        "analysis": {
            "schema_version": "1.0",
            "repository": {
                "name": "repo",
                "profile": "kubernetes-p0",
                "git_ref": None,
                "file_count": 1,
            },
            "workload_profiles": [
                {
                    "name": "backend",
                    "source_files": ["compose.yml"],
                    "image_build_profile": {
                        "dockerfile": "backend/Dockerfile",
                        "evidence": [
                            {
                                "path": "compose.yml",
                                "selector": "services.backend.build",
                                "symbol": "build",
                                "start_line": 1,
                                "end_line": 1,
                            }
                        ],
                    },
                    "runtime_deployment_profile": {
                        "runtime": "FastAPI",
                        "container_ports": [8000],
                        "evidence": [
                            {
                                "path": "compose.yml",
                                "selector": "services.backend",
                                "symbol": "backend",
                                "start_line": 1,
                                "end_line": 1,
                            }
                        ],
                        "kubernetes_candidates": [
                            {
                                "kind": "Deployment",
                                "candidate_role": "workload_controller",
                                "evidence_type": "component_source",
                                "confidence": "derived",
                                "rationale": "stateless HTTP application",
                            }
                        ],
                        "relationships": [],
                    },
                }
            ],
            "migration_questions": [],
            "components": [],
            "workload_mappings": [],
            "networking": [],
            "configuration": [],
            "secrets": [],
            "storage": [],
            "runtime_dependencies": [],
            "startup_order": [],
            "health_checks": [],
            "build_time_constraints": [],
            "container_image": [],
            "unresolved_operational_inputs": [],
            "warnings": [],
            "unsupported_constructs": [],
            "source_coverage": [],
            "detected_files": [],
        },
    }

    instruction = module._build_final_answer_instruction(payload)

    start = instruction.index("\n<workload_profiles>\n") + len("\n<workload_profiles>\n")
    end = instruction.index("\n</workload_profiles>", start)
    serialized_profiles = instruction[start:end].strip()
    assert serialized_profiles == json.dumps(
        payload["analysis"]["workload_profiles"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert serialized_profiles != "[]"
    assert json.loads(serialized_profiles) == payload["analysis"]["workload_profiles"]
    assert 'name":"backend"' in serialized_profiles
    assert 'dockerfile":"backend/Dockerfile"' in serialized_profiles
    assert 'runtime":"FastAPI"' in serialized_profiles
    assert '"kind":"Deployment"' in serialized_profiles
    assert '"candidate_role":"workload_controller"' in serialized_profiles
    assert '"evidence_type":"component_source"' in serialized_profiles
    assert "structured workload profile facts from <workload_profiles>" in instruction
    assert "Scope every negative claim to scanned repository facts" in instruction
    assert "infer" not in instruction.lower()
    assert "structured workload profiles" in instruction
