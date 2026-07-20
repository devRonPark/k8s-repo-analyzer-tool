# LLM Natural Brief Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tune the live LLM final-answer prompt so it preserves deterministic migration facts while producing a concise Korean natural-language brief instead of copying the deterministic brief verbatim.

**Architecture:** Keep the analyzer, JSON schema, and deterministic brief renderer unchanged. Modify only `_build_final_answer_instruction()` in `scripts/llm_tool_call_demo.py` and update its prompt-contract test in `tests/test_llm_tool_call_demo.py`.

**Tech Stack:** Python 3.12, pytest, existing OpenAI-compatible Chat Completions demo.

## Global Constraints

- Change only the final-answer instruction used after the analyzer tool call.
- Keep the analyzer output, JSON schema, and deterministic brief renderer unchanged.
- Keep the deterministic brief in the prompt as source material, but instruct the model not to copy it verbatim.
- Preserve `not_detected`, `partial`, and `unresolved` status meaning in the final response.
- Preserve all warning codes and all image/runtime risk subjects in the final response.
- Do not copy the deterministic brief verbatim.
- Do not emit raw `Evidence:` lines in the final response.
- Do not invent Kubernetes values: replica count, CPU/memory, PVC size, StorageClass, IngressClass, HPA, PDB, DB HA, backup policy, hosts, TLS, or Secret values.
- Do not turn `not_detected`, `partial`, or `unresolved` into a positive assertion.
- Do not describe a derived workload mapping as a final manifest.

---

### Task 1: Natural-Language Final Answer Contract

**Files:**
- Modify: `tests/test_llm_tool_call_demo.py`
- Modify: `scripts/llm_tool_call_demo.py`

**Interfaces:**
- Consumes: `_build_final_answer_instruction(payload: dict[str, Any]) -> str`
- Produces: A final-answer instruction that requires Korean natural-language Markdown with `## 핵심 요약`, `## 7문항 답변`, `## 경고와 리스크`, and `## 추가 결정사항`

- [ ] **Step 1: Update the failing prompt-contract test**

In `tests/test_llm_tool_call_demo.py`, extend `test_live_transcript_injects_brief_and_risk_contract_for_final_answer` so it asserts:

```python
assert "Write the final answer in Korean natural-language Markdown" in final_instruction["content"]
assert "## 핵심 요약" in final_instruction["content"]
assert "## 7문항 답변" in final_instruction["content"]
assert "## 경고와 리스크" in final_instruction["content"]
assert "## 추가 결정사항" in final_instruction["content"]
assert "source material only; do not copy it verbatim" in final_instruction["content"]
assert "Do not include raw Evidence: lines" in final_instruction["content"]
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py::test_live_transcript_injects_brief_and_risk_contract_for_final_answer
```

Expected: FAIL because the current instruction does not include the natural-language output contract.

- [ ] **Step 3: Implement the prompt contract**

In `scripts/llm_tool_call_demo.py`, update `_build_final_answer_instruction()` so the returned instruction includes:

```python
"Write the final answer in Korean natural-language Markdown, not as a copied deterministic report.",
"Use exactly these top-level sections: ## 핵심 요약, ## 7문항 답변, ## 경고와 리스크, ## 추가 결정사항.",
"For ## 핵심 요약, write 3-5 natural Korean sentences.",
"For ## 7문항 답변, write one numbered item per migration question, include the status in parentheses, and rewrite each answer in 1-2 Korean sentences.",
"For ## 경고와 리스크, include every warning code and every image/runtime risk subject, with why it matters for Kubernetes migration.",
"For ## 추가 결정사항, list unresolved operational inputs concretely; do not collapse them into vague examples.",
"The deterministic brief below is source material only; do not copy it verbatim.",
"Do not include raw Evidence: lines in the final answer.",
```

Keep the existing warning/risk/status/no-invention rules.

- [ ] **Step 4: Run the focused test**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py::test_live_transcript_injects_brief_and_risk_contract_for_final_answer
```

Expected: PASS.

- [ ] **Step 5: Run LLM demo tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Run live spot check**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run python scripts/llm_tool_call_demo.py --mode live --repo tests/fixtures/jpetstore-6 --git-ref c8f62cc76b8a --question "검증 레포 mybatis/jpetstore-6를 Kubernetes 이관 관점에서 7개 migration question 중심으로 brief하게 요약해줘."
```

Expected: final answer uses the four Korean sections, includes warnings and image/runtime risks, and does not paste raw `Evidence:` lines.

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/plans/2026-07-20-llm-natural-brief-prompt.md tests/test_llm_tool_call_demo.py scripts/llm_tool_call_demo.py
git commit -m "fix: ask LLM to rewrite migration brief naturally"
```
