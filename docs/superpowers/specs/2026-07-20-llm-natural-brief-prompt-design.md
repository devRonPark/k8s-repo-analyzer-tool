# LLM Natural Brief Prompt Design

## Goal

Tune the live LLM final-answer prompt so it preserves every deterministic migration fact, warning, and image/runtime risk while rewriting the answer as a concise Korean natural-language Kubernetes migration brief.

## Scope

- Change only the final-answer instruction used after the analyzer tool call.
- Keep the analyzer output, JSON schema, and deterministic brief renderer unchanged.
- Keep the deterministic brief in the prompt as source material, but instruct the model not to copy it verbatim.
- Preserve `not_detected`, `partial`, and `unresolved` status meaning in the final response.
- Preserve all warning codes and all image/runtime risk subjects in the final response.

## Output Contract

The LLM final answer should be Korean Markdown with these sections:

1. `## 핵심 요약`
   - Three to five natural Korean sentences.
   - State that workload mappings are candidates when derived.
2. `## 7문항 답변`
   - One numbered item per migration question.
   - Include each question status in parentheses.
   - Rewrite the deterministic answer in one or two Korean sentences.
3. `## 경고와 리스크`
   - Include every analyzer warning code.
   - Include every image/runtime risk subject.
   - Explain why each matters for Kubernetes migration.
4. `## 추가 결정사항`
   - List unresolved operational inputs concretely.
   - Do not collapse them into vague examples.

## Prohibitions

- Do not copy the deterministic brief verbatim.
- Do not emit raw `Evidence:` lines in the final response.
- Do not invent Kubernetes values: replica count, CPU/memory, PVC size, StorageClass, IngressClass, HPA, PDB, DB HA, backup policy, hosts, TLS, or Secret values.
- Do not turn `not_detected`, `partial`, or `unresolved` into a positive assertion.
- Do not describe a derived workload mapping as a final manifest.

## Testing

Update `tests/test_llm_tool_call_demo.py` so the captured second Chat Completions request verifies:

- The final instruction asks for Korean natural-language Markdown.
- The instruction includes the required section names.
- The instruction says the deterministic brief is source material and must not be copied verbatim.
- The instruction forbids raw `Evidence:` lines in the final response.
- The instruction still includes warning codes, image/runtime risk subjects, and status preservation requirements.

Run `tests/test_llm_tool_call_demo.py`, the full test suite, and one live `jpetstore-6` spot check.
