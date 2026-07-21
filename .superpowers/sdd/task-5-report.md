# Task 5 Report: Reduce LLM Prompt Reconstruction Burden

## Changes

- Added a compact JSON serialization of `analysis.workload_profiles` to the final-answer instruction.
- Directed the model to explain the structured workload profiles without reconstructing or reclassifying workloads from scattered facts.
- Kept the deterministic brief, candidate phrasing, negative-claim scope, and unresolved-operational-value guardrails intact.
- Added a prompt regression test using profile-level provenance and candidate `evidence_type` fields accepted by `AnalysisResult.model_validate`.

## TDD Evidence

- RED: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py::test_final_answer_instruction_prefers_workload_profiles`
  - Failed as expected because the instruction lacked `workload_profiles`.
- GREEN: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py::test_final_answer_instruction_prefers_workload_profiles`
  - Passed.
- Focused module: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py`
  - 22 passed.
- Full suite: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q`
  - 262 passed.

## Scope

Only `scripts/llm_tool_call_demo.py`, `tests/test_llm_tool_call_demo.py`, and this report are part of the task commit. Pre-existing `.superpowers/sdd` scratch files remain unmodified.

## Follow-up Fix

- Updated the allowed-content rule to explicitly permit structured workload profile facts from `<workload_profiles>`, while retaining the deterministic brief as fallback context and preserving candidate, scanned-facts-only negative-claim, and unresolved-operational-value guardrails.
- Strengthened `test_final_answer_instruction_prefers_workload_profiles` to extract and parse the tagged compact JSON, assert it is non-empty and exactly matches the supplied profiles, and verify the workload name, Dockerfile, runtime, candidate kind, candidate role, and evidence type.

## Exact Verification Results

- `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py::test_final_answer_instruction_prefers_workload_profiles`
  - Passed: 1 passed.
- `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py`
  - Passed: 22 passed.
- `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q`
  - Passed: 262 passed.
