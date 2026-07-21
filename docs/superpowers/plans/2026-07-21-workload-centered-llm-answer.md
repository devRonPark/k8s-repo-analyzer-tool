# Workload-Centered LLM Answer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the live LLM final answer prompt so model responses describe application workload composition, workload details, workload relationships, and Kubernetes migration context instead of leading with the seven migration questions.

**Architecture:** Keep the analyzer, JSON schema, deterministic brief renderer, and tool schema unchanged. Update only the final-answer instruction built after the analyzer tool call, and verify the prompt contract through the existing live transcript unit test.

**Tech Stack:** Python 3.12, pytest, existing OpenAI-compatible Chat Completions demo.

## Global Constraints

- Change only the live final-answer instruction in `scripts/llm_tool_call_demo.py`.
- Keep the analyzer output, JSON schema, deterministic brief renderer, and tool schema unchanged.
- Keep the deterministic brief as source material.
- Preserve warning codes, image/runtime risk subjects, status labels, and unresolved operational inputs.
- Continue prohibiting invented Kubernetes values.
- The final answer should read like a developer handoff narrative, not a rigid seven-question report.
- The seven migration question statuses must still be represented, but they can be summarized in context rather than listed as numbered questions.
- Do not include raw `Evidence:` lines by default.
- Do not claim "no external dependency" without the qualifier that no dependency was detected from scanned repository facts.

---

### Task 1: Workload-Centered Final Answer Prompt

**Files:**
- Modify: `tests/test_llm_tool_call_demo.py`
- Modify: `scripts/llm_tool_call_demo.py`

**Interfaces:**
- Consumes: `_build_final_answer_instruction(payload: dict[str, Any]) -> str`
- Produces: A final-answer instruction requiring Korean workload-centered Markdown with these top-level sections: `## 애플리케이션 구성 개요`, `## 워크로드 구성`, `## 워크로드 간 관계`, `## Kubernetes 이관 관점`, `## 확인이 필요한 부분`

- [ ] **Step 1: Update the failing prompt-contract test**

In `tests/test_llm_tool_call_demo.py`, in `test_live_transcript_injects_brief_and_risk_contract_for_final_answer`, replace the current natural-brief section assertions:

```python
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
```

with these workload-centered assertions:

```python
    assert "Write the final answer in Korean workload-centered Markdown" in final_instruction["content"]
    assert "## 애플리케이션 구성 개요" in final_instruction["content"]
    assert "## 워크로드 구성" in final_instruction["content"]
    assert "## 워크로드 간 관계" in final_instruction["content"]
    assert "## Kubernetes 이관 관점" in final_instruction["content"]
    assert "## 확인이 필요한 부분" in final_instruction["content"]
    assert "The seven migration questions are coverage checks, not the final answer structure" in final_instruction["content"]
    assert "Image Build Profile" in final_instruction["content"]
    assert "Runtime Deployment Profile" in final_instruction["content"]
    assert "build tool, image build path or context, Dockerfile/buildpack/Jib/prebuilt-image source" in final_instruction["content"]
    assert "start command and arguments, exposed or listening container ports" in final_instruction["content"]
    assert "configuration candidates, Secret candidates, persistent volumes or mounts" in final_instruction["content"]
    assert "workload controller candidates first, then companion object candidates" in final_instruction["content"]
    assert "do not describe Services, PVCs, ConfigMaps, Secrets, Ingresses, or Gateways as workloads" in final_instruction["content"]
    assert "Service type, IngressClass, host, TLS, Gateway policy" in final_instruction["content"]
    assert "Deployment candidate for long-running stateless" in final_instruction["content"]
    assert "StatefulSet or external managed service candidate" in final_instruction["content"]
    assert "Job candidate for one-off migration/seed/prestart work" in final_instruction["content"]
    assert "init container candidate only when" in final_instruction["content"]
    assert "Do not give a Service candidate to a background worker" in final_instruction["content"]
    assert "Compose depends_on" in final_instruction["content"]
    assert "Dockerfile EXPOSE, Compose ports" in final_instruction["content"]
    assert "Probe Candidates" in final_instruction["content"]
    assert "Do not translate one generic health check into final startup, readiness, and liveness probes" in final_instruction["content"]
    assert "Do not infer an application PVC from datasource or database evidence alone" in final_instruction["content"]
    assert "Compose profiles" in final_instruction["content"]
    assert "Explain workload relationships" in final_instruction["content"]
    assert "Do not claim no external dependency without saying no dependency was detected from scanned repository facts" in final_instruction["content"]
    assert "source material for the workload-centered rewrite" in final_instruction["content"]
    assert "Include compact file references only when they materially help" in final_instruction["content"]
    assert "Keep all Kubernetes object mappings as candidates" in final_instruction["content"]
```

Keep these existing assertions unchanged:

```python
    assert "Kubernetes migration brief - jpetstore-6" in final_instruction["content"]
    assert "Allowed final-answer content is limited to" in final_instruction["content"]
    assert "jdk_version_mismatch" in final_instruction["content"]
    assert "image.signal_handling" in final_instruction["content"]
    assert "Use not_detected, partial, and unresolved as explicit status labels" in final_instruction["content"]
    assert "Think and check internally in English" in final_instruction["content"]
    assert "output only the Korean Markdown final answer" in final_instruction["content"]
    assert "<deterministic_brief>" in final_instruction["content"]
    assert "</deterministic_brief>" in final_instruction["content"]
    assert "<warnings>" in final_instruction["content"]
    assert "<image_runtime_risks>" in final_instruction["content"]
    assert "Before writing the final answer, silently verify" in final_instruction["content"]
    assert "all final content is inside the allowed scope" in final_instruction["content"]
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py::test_live_transcript_injects_brief_and_risk_contract_for_final_answer
```

Expected: FAIL because `_build_final_answer_instruction()` still asks for `## 핵심 요약`, `## 7문항 답변`, `## 경고와 리스크`, and `## 추가 결정사항`.

- [ ] **Step 3: Implement the workload-centered final-answer instruction**

In `scripts/llm_tool_call_demo.py`, replace the instruction list inside `_build_final_answer_instruction()` with:

```python
        [
            "Use the deterministic analyzer output below as the source of truth for the final answer.",
            "Think and check internally in English for logic accuracy; output only the Korean Markdown final answer.",
            "Write the final answer in Korean workload-centered Markdown, not as a copied deterministic report.",
            "Use exactly these top-level sections: ## 애플리케이션 구성 개요, ## 워크로드 구성, ## 워크로드 간 관계, ## Kubernetes 이관 관점, ## 확인이 필요한 부분.",
            "The seven migration questions are coverage checks, not the final answer structure; represent their statuses in context without listing them as the main numbered report.",
            "Allowed final-answer content is limited to: migration question answers and statuses, component/workload/port/dependency/config/storage/startup facts from the deterministic brief, analyzer warning codes and messages, image/runtime risk subjects and effects, and unresolved operational inputs with needed inputs.",
            "For ## 애플리케이션 구성 개요, explain the application as a set of runtime workloads in natural Korean, mentioning roles such as API, frontend, database, cache, admin tool, worker, or init/prestart job only when present in analyzer facts.",
            "For ## 워크로드 구성, describe each detected workload in a short paragraph or compact bullet group.",
            "For each workload, include the role and language/runtime/framework when present in analyzer facts.",
            "For each workload, include the Image Build Profile when present: build tool, image build path or context, Dockerfile/buildpack/Jib/prebuilt-image source, build command, produced artifact, and base or builder image.",
            "For each workload, include the Runtime Deployment Profile when present: image reference, start command and arguments, exposed or listening container ports, published or Service-facing ports, Exposure Candidates, configuration candidates, Secret candidates, persistent volumes or mounts, Probe Candidates, lifecycle or init behavior, and Kubernetes workload controller candidate.",
            "For missing workload fields, say the value was not detected from repository facts instead of inventing it.",
            "Explain workload relationships in ## 워크로드 간 관계 using natural language and compact arrows when helpful, for example frontend -> backend, backend -> db, worker -> broker/cache/db, or prestart job -> db; use only relationships present in component runtime dependencies, Compose service dependency/startup facts, configuration evidence, ports, or deterministic migration answers.",
            "When using Compose depends_on, phrase it as startup-order evidence, not as a final Kubernetes dependency mechanism.",
            "If workload relationships are not detected, say repository facts do not expose enough relationship evidence.",
            "For ## Kubernetes 이관 관점, explain Kubernetes object candidates as workload controller candidates first, then companion object candidates such as Service, PVC, ConfigMap, Secret, Ingress, or Gateway.",
            "Keep all Kubernetes object mappings as candidates, and do not describe Services, PVCs, ConfigMaps, Secrets, Ingresses, or Gateways as workloads.",
            "Use conservative controller wording: Deployment candidate for long-running stateless app/server/worker processes; StatefulSet or external managed service candidate for stateful services with persistent storage or stable identity evidence; Job candidate for one-off migration/seed/prestart work; init container candidate only when the evidence points to app-Pod startup gating.",
            "Do not give a Service candidate to a background worker solely because it is a workload; require inbound port or consumer evidence.",
            "Keep Service type, IngressClass, host, TLS, Gateway policy, PVC size, access mode, and StorageClass unresolved unless declared by repository facts.",
            "Treat Dockerfile EXPOSE, Compose ports, Dockerfile or Compose health checks, and declared volumes as evidence for candidates, not final Kubernetes design decisions.",
            "Do not translate one generic health check into final startup, readiness, and liveness probes.",
            "Do not infer an application PVC from datasource or database evidence alone; report application-local mounts separately from database/service persistence.",
            "Surface ignored Compose overrides, sample/documented deployment evidence, and unknown/inactive Compose profiles as coverage caveats when present.",
            "Include every analyzer warning code and every image/runtime risk subject in context, with why it matters for Kubernetes migration.",
            "For ## 확인이 필요한 부분, list unresolved operational inputs concretely and include important coverage caveats such as ignored compose override files or missing deployment topology files.",
            "Use not_detected, partial, and unresolved as explicit status labels and explain them as missing evidence or open decisions.",
            "Do not claim no external dependency without saying no dependency was detected from scanned repository facts.",
            "Operational values are allowed only when they appear in unresolved_operational_inputs as needed inputs; keep replica counts, CPU/memory, PVC sizes, StorageClass, IngressClass, HPA, PDB, DB HA, backup policy, hosts, TLS, and Secret values as decisions to collect.",
            "The deterministic brief below is source material for the workload-centered rewrite.",
            "Include compact file references only when they materially help a developer verify a workload fact; do not include raw Evidence: lines by default.",
            "Before writing the final answer, silently verify: all migration question statuses are represented, all warning codes are present, all image/runtime risk subjects are present, all final content is inside the allowed scope, Kubernetes mappings are candidates, external dependency absence is qualified as scanned-facts-only, and operational values remain open decisions unless provided by the analyzer.",
            "",
            "<deterministic_brief>",
            brief.rstrip(),
            "</deterministic_brief>",
            "",
            "<warnings>",
            "\n".join(warnings) if warnings else "- none",
            "</warnings>",
            "",
            "<image_runtime_risks>",
            "\n".join(image_risks) if image_risks else "- none",
            "</image_runtime_risks>",
        ]
```

- [ ] **Step 4: Run the focused test to verify it passes**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py::test_live_transcript_injects_brief_and_risk_contract_for_final_answer
```

Expected: PASS.

- [ ] **Step 5: Run all LLM demo tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py
```

Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Run one live Python spot check**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run python scripts/llm_tool_call_demo.py --mode live --repo tests/fixtures/full-stack-fastapi --question '이 Python repository를 Kubernetes migration 관점에서 애플리케이션 워크로드 구성, 각 워크로드의 언어/빌드/실행/포트, 워크로드 간 의존 관계 중심으로 설명해줘. 도구 출력에 없는 값은 추정하지 마.'
```

Expected:

- The transcript includes a model tool call for `analyze_repository`.
- Tool output summary has `ok=true`.
- The final answer uses the five workload-centered sections.
- The final answer describes `db`, `adminer`, `prestart`, `backend`, and `frontend` as workloads.
- The final answer qualifies `not_detected` external dependencies as scanned-facts-only.
- The final answer keeps replica/resource/Ingress/HPA/PDB/PVC/StorageClass/DB HA values as decisions to collect.

- [ ] **Step 8: Commit**

Run:

```bash
git add docs/superpowers/plans/2026-07-21-workload-centered-llm-answer.md tests/test_llm_tool_call_demo.py scripts/llm_tool_call_demo.py
git commit -m "fix: make LLM answers workload centered"
```
