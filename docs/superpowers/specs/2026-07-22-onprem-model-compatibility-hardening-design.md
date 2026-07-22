# On-Premise Model Compatibility Hardening Design

Date: 2026-07-22

Status: Approved for planning

## Goal

Make `repository-assessment` reliable with the on-premise
`Qwen3-Coder-30B-A3B-Instruct` Chat Completions endpoint after its model context
window is increased from 32K to 128K, without assuming that a larger context
window removes protocol, planning, extraction, or audit failures.

The implementation must make the five pinned validation repositories complete
as far as their repository evidence permits. A command-line application is not
required to become a long-running Kubernetes workload; it may correctly finish
as a non-resident tool, Job candidate, or unsupported workload when supported by
checked evidence.

## Evidence Behind the Change

The live validation in
`docs/validation/2026-07-22-onprem-five-workload-validation.md` found two
independent failure classes.

1. Etherpad and SearXNG sent 34,211-token and 34,013-token planning requests to
   a 32,768-token model and received HTTP 400 context-length errors. A 128K
   context window is expected to remove these two specific failures.
2. JBang, Spring Petclinic REST, pipx, and a bounded SearXNG run reached topic
   analysis but failed because the model emitted multiple valid
   `submit_topic_analysis` calls while the client required exactly one call.
   Context expansion cannot fix this protocol mismatch.

The same runs also exposed invalid model-selected paths, unsupported structured
parse methods, partial-document structured parsing, out-of-range line requests,
and missing failed-run audit artifacts. These defects must be fixed as part of
the same compatibility boundary.

## Non-Goals

- Do not add a Qwen-specific tokenizer or make the engine depend on SGLang.
- Do not switch from Chat Completions to the Responses API.
- Do not increase repository read limits merely because the context is larger.
- Do not generate Kubernetes manifests or invent operational values.
- Do not silently accept conflicting duplicate topic results.
- Do not redesign the assessment into thirteen mandatory serial model calls.

## Selected Approach

Keep the existing two-stage model flow—one bounded analysis plan followed by
one topic-analysis request—but harden the seams around it:

1. pass an explicit model context capability into the assessment run;
2. compact model-facing scan data by deterministic evidence value when needed;
3. classify context rejection separately and retry once with a smaller prompt;
4. accept and deterministically merge parallel topic submission calls;
5. normalize safe plan method mistakes and repair unsafe plan mistakes;
6. write a run log even when no assessment result can be built.

This retains the current provider-neutral engine and two-call happy path. It is
less costly than one call per topic and more reliable than relying on a server
flag such as `parallel_tool_calls=false`, which the live SGLang endpoint ignored.

## Runtime Configuration

Add an optional positive `context_window_tokens` capability to the live runtime
configuration and assessment request. Expose it through:

```text
repository-assessment assess --context-window-tokens 131072
```

The value is model capability metadata, not a repository fact or Kubernetes
input. Record it in `run-log.json`, but do not copy it into
`migration-inputs.yaml` or `migration-report.md`.

When the flag is omitted, retain the current bounded defaults and allow the
server to reject an oversized request. The resulting error must still be
classified and audited correctly. Do not make a second `/models` request inside
the engine; endpoint discovery remains a runtime concern.

## Prompt Budgeting and Scan Selection

The repository scan remains the complete bounded internal scan up to
`tree_entries`. Only the scan representation sent to the model is compacted.
This preserves revision resolution, path validation, audit data, and repository
tool behavior.

### Budget

Reserve part of the context window for the response, submission schema, system
prompt, and repair message. The model-facing request builder uses at most 70%
of `context_window_tokens` for serialized prompt messages. Estimate tokens with
a deterministic provider-neutral UTF-8 byte heuristic and retain the server
response as the final authority. The estimator need not claim tokenizer-level
accuracy.

If the server reports a context-length error, use its reported input and limit
when available to reduce the model-facing scan budget by a safety factor and
retry the planning call once. This adaptive retry counts as a model call and is
recorded in run events and metadata. A second context rejection ends the run as
`failed`; it must not loop until the global timeout.

### High-Value Ordering

When compaction is required, select entries deterministically in this order:

1. root and shallow README/runbook files;
2. root and shallow build descriptors and wrappers;
3. Dockerfiles, Compose files, deployment manifests, and service descriptors;
4. application configuration and environment templates;
5. entrypoint, startup, migration, and operational scripts;
6. shallow source roots and likely main files;
7. remaining primary files;
8. documentation, tests, examples, development, and generated contexts.

Within a priority group, sort by repository-relative POSIX path. Include compact
summary counts for omitted directories and source contexts so omission is
visible. Set a model-facing `truncated` marker without changing the full scan's
own `truncated` value.

This avoids the prior lexicographic truncation behavior that selected
`.github/workflows/docker.yml` while excluding more valuable root runtime files.

### Topic Evidence Budget

The topic request has the same context risk as the planning request. Keep every
extracted evidence item in engine state and the audit artifacts, but construct a
separate model-facing evidence view within the same 70% prompt budget.

Select complete evidence items; never cut an excerpt in the middle and continue
to present its original line range as though it were complete. Prefer primary,
shallow, runtime-referenced evidence and high-priority plan targets, then select
remaining items by evidence ID. Include a compact list of omitted evidence IDs,
paths, source contexts, and omission reason in the topic request.

If one evidence item cannot fit, do not send an oversized excerpt. Record
`evidence_item_over_budget` and make the next plan round request a narrower line
range or bounded search for the affected topics. If no round remains, those
topics finish `partial`, `unresolved`, or `unsupported`; they must not make a
claim from evidence the model did not receive.

If the server still rejects the topic request for context length, reduce the
model-facing evidence budget using the reported token ratio and retry once. The
engine retains all evidence for audit and checking, but a claim may cite only an
evidence ID included in that model request.

## Context Error Classification

Add a provider-neutral `ModelContextLengthError` below `ModelClientError`. It
contains safe optional fields:

- HTTP status;
- reported input tokens;
- reported context limit;
- provider error type and code.

The OpenAI-compatible adapter catches `HTTPError` before generic `URLError`,
reads a bounded response body, and recognizes structured context-length errors.
The exact repository prompt and response body are never copied into the public
error. Preserve only the bounded provider message and structured fields.

Classify non-context HTTP failures as follows:

- retryable connection errors, timeouts, HTTP 429, and HTTP 5xx:
  `ModelUnavailableError`;
- other HTTP 4xx protocol or configuration rejections:
  `ModelProtocolError` with bounded, redacted provider details.

## Parallel Topic Submission Calls

Analysis plans still require exactly one `submit_analysis_plan` call. Topic
analysis accepts one or more `submit_topic_analysis` calls in the first choice.

For every matching topic call:

1. require string JSON arguments;
2. decode arguments independently;
3. validate each value as `TopicAnalysisBatch`;
4. reject any unexpected tool name in the same assistant message;
5. concatenate topics in response order, then canonicalize by
   `(workload, topic)`;
6. set `needs_more_evidence` to logical OR;
7. set `gap_topics` to a sorted unique union.

Identical duplicate `(workload, topic)` values collapse to one. Conflicting
duplicates raise `ModelSchemaError` and use the existing one-shot schema repair
flow. The client must never pick the first or last conflicting value silently.

Add `tool_call_count` to model response metadata so the run log distinguishes a
single aggregate call from parallel topic calls. The public response mode can
remain `tool_call` for backward compatibility.

The request should still send `parallel_tool_calls: false` as a preference, but
correctness must not depend on the server honoring it.

## Plan Validation and Extraction

### Safe Normalization

Plan validation may normalize a method only when the result is unambiguous:

- supported JSON, YAML, XML, TOML, and properties paths use
  `parse_structured` over the complete document;
- Dockerfiles, Makefiles, Gradle files, source files, shell scripts, and other
  text formats use `read_lines`;
- an unsupported `parse_structured` request is downgraded to `read_lines` and
  recorded as a plan normalization warning rather than discarded.

Structured parsing must never parse a model-selected fragment as if it were a
complete JSON, YAML, TOML, XML, or properties document. It reads the complete
file subject to `single_file_bytes` and returns evidence with the actual full
line range.

### Unsafe Targets and Plan Repair

Paths absent from the bounded full scan, path escapes, symlink escapes, binary
files, oversized files, and `line_start` values beyond the real file remain
rejected. They must not be clamped to unrelated content.

When the first plan has rejected targets and a second plan round remains, send
bounded rejection feedback containing the path, reason, supported method, and
actual line count when known. The second plan may replace rejected work while
accepted first-round targets remain deduplicated. Extraction and topic analysis
must not proceed with zero accepted evidence when a repair round remains.

An excessive `line_end` may be reduced to the actual last line during the read,
as today. An invalid `line_start` is an error because moving it to line 1 or the
last line would change the selected evidence semantics.

## Failed-Run Artifacts

Successful and `completed_with_gaps` runs continue to write exactly four
artifacts. A `failed` run writes at least an atomic `run-log.json` containing:

- run ID and status;
- resolved revision when available;
- stage events;
- limits and usage;
- model metadata and attempts;
- safe structured errors;
- no repository excerpts beyond the existing evidence-log contract.

The CLI summary for a failed run returns the `run_log` path in `artifacts` and
exit code 3. It must no longer return an empty artifact map after the output
directory has been supplied and is writable.

## Data Flow

```text
full bounded repository scan
        |
        +--> deterministic high-value prompt scan
                 |
                 v
          analysis plan request
                 |
       context error? -- yes --> shrink prompt scan, retry once
                 |
                 v
       validate + normalize plan
                 |
       unsafe rejections? -- yes --> bounded plan repair round
                 |
                 v
         evidence extraction
                 |
        model-facing evidence budget
                 |
                 v
       topic-analysis request
                 |
       one or many submission calls
                 |
       validate + merge + conflict check
                 |
                 v
       evidence check and report building
```

Any fatal path writes `run-log.json` before the CLI returns.

## Testing Strategy

Implementation follows test-driven development.

### Model Adapter Tests

- merge thirteen valid topic tool calls into one batch;
- merge `needs_more_evidence` and sorted unique `gap_topics`;
- collapse byte-identical duplicate topics;
- reject conflicting duplicate topics and exercise one repair attempt;
- reject unexpected tool names mixed with submission calls;
- preserve the single-call and strict JSON fallback behavior;
- include `parallel_tool_calls: false` in live requests;
- parse the captured 34,211/32,768 HTTP context error;
- classify HTTP 429/5xx as unavailable and other HTTP 4xx as protocol errors;
- record `tool_call_count` without storing raw responses.

### Prompt and Scan Tests

- keep the full internal scan unchanged;
- fit the model-facing scan within the configured deterministic budget;
- select root Dockerfile, Compose, build, package, configuration, and entrypoint
  files before `.github`, docs, tests, and examples;
- produce byte-identical compact scans for the same tree;
- record omitted context summaries;
- retry once with a smaller scan after a synthetic context rejection;
- stop and fail after a second context rejection.

### Topic Evidence Budget Tests

- retain all extracted evidence in engine state while sending only the bounded
  model-facing evidence view;
- prefer primary runtime evidence over documentation, test, example, and CI
  evidence;
- never truncate an evidence excerpt while preserving its old line range;
- expose omitted evidence IDs and reasons to the model and run log;
- reject claims that cite evidence omitted from the topic request;
- request narrower evidence for an individually oversized item when a plan
  round remains;
- retry one topic request after a synthetic context rejection and stop after a
  second rejection.

### Plan and Repository Tool Tests

- normalize Dockerfile `parse_structured` to `read_lines`;
- parse supported structured files as complete documents even when the model
  requests a fragment;
- retain secret masking and file-size limits for full-document parsing;
- repair absent paths on round two;
- report, rather than clamp, an invalid `line_start`;
- keep duplicate target and search limits deterministic.

### Writer and CLI Tests

- write only `run-log.json` for a failed run;
- return its path in the compact CLI summary;
- keep four-file atomic output for non-fatal runs;
- avoid leaking raw HTTP bodies or repository prompt contents.

### Live Acceptance

After the endpoint is reconfigured, query `/v1/models` and confirm an advertised
context length of at least 131,072 tokens. Re-run the five exact SHAs from
`docs/research/2026-07-22-five-workload-repository-selection.md` with:

```text
--context-window-tokens 131072
```

Acceptance requires:

- no context-length failure;
- no `expected exactly one submit_topic_analysis function call` error;
- every accepted claim passes evidence checking;
- no target repository changes;
- all failed or non-failed runs have a run log;
- web applications produce all thirteen topic statuses across supported
  workloads;
- command-line applications retain evidence-backed non-resident, Job-candidate,
  unresolved, or unsupported semantics without an invented Deployment;
- Secret values remain masked and operational values remain required inputs.

`completed_with_gaps` is acceptable only for genuine repository gaps or
unsupported evidence, not for context, protocol, plan-method, or audit-artifact
defects introduced by the assessment implementation.

## Compatibility and Migration

All new runtime fields are optional except in the 128K acceptance command. The
recorded-response client and existing fixtures continue to work without a model
context value. Existing successful single-call Chat Completions responses remain
valid. Output schema versions remain unchanged because the assessment result is
unchanged; the run log receives additive model metadata and failed-run artifact
behavior.

The deterministic `repo-analyzer` compatibility path is outside this change.
