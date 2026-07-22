# LLM-led Kubernetes Migration Assessment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runtime-independent, LLM-led repository assessment workflow that selects bounded evidence targets, checks every important claim, and emits four workload-centered Kubernetes migration input artifacts.

**Architecture:** Add a new top-level `repository_assessment` package instead of extending the deterministic `repo_analyzer` pipeline. Its external interface is the single deep module `assess(request, model_client, repository_tools, event_sink) -> AssessmentRun`; provider, filesystem, and OpenShell details sit behind injected interfaces or adapters, while evidence checking and artifact writing remain deterministic.

**Tech Stack:** Python 3.12, Pydantic v2, ruamel.yaml, Python standard-library HTTP/JSON/XML/TOML support, pytest, OpenAI-compatible `/v1/chat/completions`, NVIDIA OpenShell sandbox policies.

## Global Constraints

- Keep `repo-analyzer analyze` and all existing compatibility tests working throughout the changeover.
- The new assessment core must not import `repo_analyzer`, OpenShell, an OpenAI SDK, or provider-specific message/response types.
- Repository access is read-only; every path is repository-relative after symlink resolution, and links escaping the repository are rejected.
- Repository content is untrusted data and cannot add tools, change prompts, raise run limits, or request network access.
- Secret-looking values are masked before model calls, run logs, or result artifacts; key names may remain, values may not.
- The LLM selects targets and proposes topic results; deterministic code validates plans, extracts evidence, checks claims/conflicts, calculates confidence, enforces limits, and writes artifacts.
- The first version supports generic JSON, YAML, XML, TOML, and properties extraction without requiring a stack plugin.
- Topic statuses are exactly `answered`, `partial`, `unresolved`, `unsupported`, and `contradicted`.
- Run statuses are exactly `completed`, `completed_with_gaps`, and `failed`; narrow target, parser, topic, or response failures do not fail a useful run.
- Output separates repository `facts`, non-final `kubernetes_candidates`, and external `required_inputs`; it contains no owner roles, question IDs, question list, final manifests, readiness score, or invented operational values.
- Use the public terms Repository scan, Analysis plan, Evidence extraction, Analysis topic, Topic status, Evidence check, Report building, Required input, Run limits, and Assessment engine.
- Default run limits are: 20,000 tree entries, 40 selected targets, 512 KiB per readable file, 200 lines per read, 20 searches, 100 matches per search, 2 plan rounds, 10 model calls, 1 schema repair retry, and 300 seconds total run time.
- Repeated extraction of the same file digest, line range, and method must use cached evidence.
- Given recorded model responses, evidence checks and all machine-readable outputs must be deterministic.
- OpenShell is treated as the sandbox/runtime that launches this CLI. Do not add an invented `agent.yaml` package contract; provide a versioned OpenShell policy example and documented `openshell sandbox create` / `openshell policy set` flow.

---

## File Structure

The new package is organized around deep modules, not one file per workflow stage:

- Create `src/repository_assessment/contracts.py`: all plain Pydantic request, plan, evidence, topic, run, event, and artifact contracts plus version constants.
- Create `src/repository_assessment/ports.py`: the three injected interfaces `StructuredModelClient`, `RepositoryTools`, and `EventSink`; production and test adapters cross these seams.
- Create `src/repository_assessment/repository.py`: one deep read-only repository-tools implementation, including safe path resolution, bounded scan/search/read, structured parsing, masking, source-context classification, and evidence caching.
- Create `src/repository_assessment/evidence.py`: deterministic plan validation, evidence checking, conflict preservation, status normalization, and confidence calculation.
- Create `src/repository_assessment/openai_compatible.py`: provider adapter for `/v1/chat/completions`, function-call/JSON fallback parsing, response digests, and one repair request.
- Create `src/repository_assessment/recorded.py`: offline structured-model adapter that replays validated response fixtures for deterministic tests and audits.
- Create `src/repository_assessment/prompts.py`: versioned system, planning, revision, and topic prompts; repository text appears only inside delimited untrusted-data blocks.
- Create `src/repository_assessment/engine.py`: the deep assessment module and its internal state machine, limit accounting, early stops, narrow error handling, and final checked result assembly.
- Create `src/repository_assessment/writers.py`: deterministic YAML, JSON, Korean Markdown, and run-log writers plus artifact-path return values.
- Create `src/repository_assessment/cli.py`: local CLI composition root; it constructs adapters and writes artifacts but contains no assessment decisions.
- Create `integrations/openshell_assessment.py`: thin OpenShell-facing process adapter that maps environment/CLI values to plain core contracts and streams progress as JSON lines.
- Create `openshell/policy.yaml`: OpenShell schema-v1 filesystem/process policy with no arbitrary outbound network access; inference uses the runtime-managed `inference.local` route.
- Create `tests/assessment/`: contract, repository-tool, evidence, model-adapter, engine, writer, runtime, security, and scenario tests.
- Create `tests/fixtures/assessment/`: small local repositories and recorded model responses for all required scenarios.
- Modify `pyproject.toml`: package both `repo_analyzer` and `repository_assessment`, and add the `repository-assessment` command without changing `repo-analyzer`.
- Modify `README.md`, `CLAUDE.md`, `docs/CLAUDE.md`, `tests/CLAUDE.md`, and `docs/adr/0001-openshell-repository-assessment-package.md`: document the new source of truth, compatibility path, OpenShell runtime model, and exact validation commands.

The main interface stays small:

```python
def assess(
    request: AssessmentRequest,
    model_client: StructuredModelClient,
    repository_tools: RepositoryTools,
    event_sink: EventSink,
) -> AssessmentRun:
    """Run one bounded assessment and return checked, serializable state."""
```

The CLI is the only composition root. Tests exercise the same interface with a recorded model adapter and an in-memory event sink.

---

### Task 1: Add Versioned Assessment Contracts and Injected Interfaces

**Files:**
- Create: `src/repository_assessment/__init__.py`
- Create: `src/repository_assessment/contracts.py`
- Create: `src/repository_assessment/ports.py`
- Modify: `pyproject.toml`
- Test: `tests/assessment/test_contracts.py`

**Interfaces:**
- Produces: `AssessmentRequest`, `RunLimits`, `AnalysisPlan`, `PlanTarget`, `EvidenceItem`, `Claim`, `TopicResult`, `CheckedClaim`, `AssessmentResult`, `RunEvent`, and `AssessmentRun`.
- Produces: `StructuredModelClient.complete(request, response_model)`, `RepositoryTools` read-only methods, and `EventSink.emit(event)`.
- Consumes: no new package code; this task defines the contracts used by all later tasks.

- [ ] **Step 1: Write failing contract tests**

```python
from pydantic import ValidationError
import pytest

from repository_assessment.contracts import (
    AnalysisPlan,
    AssessmentRequest,
    PlanTarget,
    RunLimits,
    TopicResult,
)


def test_run_limits_match_v1_defaults():
    limits = RunLimits()
    assert limits.model_dump() == {
        "tree_entries": 20_000,
        "selected_targets": 40,
        "single_file_bytes": 512 * 1024,
        "lines_per_read": 200,
        "search_calls": 20,
        "matches_per_search": 100,
        "plan_rounds": 2,
        "model_calls": 10,
        "schema_repairs": 1,
        "total_seconds": 300,
    }


def test_plan_and_topic_contracts_reject_unknown_public_terms():
    target = PlanTarget(
        path="package.json",
        line_start=1,
        line_end=160,
        topics=["build_profile", "runtime_profile"],
        purpose="Find build and start scripts.",
        method="parse_structured",
        priority="high",
    )
    assert AnalysisPlan(round=1, targets=[target]).targets == [target]
    with pytest.raises(ValidationError):
        TopicResult(topic="build_profile", status="not_detected")


def test_request_rejects_credential_bearing_repository_urls():
    with pytest.raises(ValidationError, match="credentials"):
        AssessmentRequest(repository="https://token@github.com/acme/app.git")
```

- [ ] **Step 2: Run the contract tests and verify the package is missing**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_contracts.py`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'repository_assessment'`.

- [ ] **Step 3: Define the complete public type vocabulary in `contracts.py`**

Use `BaseModel` with `ConfigDict(extra="forbid", frozen=True)` for all contracts. Define these exact aliases and fields:

```python
TopicStatus = Literal["answered", "partial", "unresolved", "unsupported", "contradicted"]
RunStatus = Literal["completed", "completed_with_gaps", "failed"]
RunStage = Literal[
    "repository_scan", "analysis_plan", "evidence_extraction",
    "topic_analysis", "evidence_check", "report_building",
]
SourceContext = Literal[
    "primary", "documentation", "test", "example", "development",
    "generated", "unknown",
]
ExtractionMethod = Literal[
    "list_tree", "find_files", "search_text", "read_lines",
    "file_info", "structured_json", "structured_yaml", "structured_xml",
    "structured_toml", "structured_properties",
]


class RunLimits(ContractModel):
    tree_entries: int = Field(default=20_000, ge=1)
    selected_targets: int = Field(default=40, ge=1)
    single_file_bytes: int = Field(default=512 * 1024, ge=1)
    lines_per_read: int = Field(default=200, ge=1)
    search_calls: int = Field(default=20, ge=0)
    matches_per_search: int = Field(default=100, ge=1)
    plan_rounds: int = Field(default=2, ge=1)
    model_calls: int = Field(default=10, ge=1)
    schema_repairs: int = Field(default=1, ge=0, le=1)
    total_seconds: int = Field(default=300, ge=1)


class AssessmentRequest(ContractModel):
    run_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    repository: str
    revision: str | None = None
    output_directory: str
    language: Literal["ko"] = "ko"
    limits: RunLimits = Field(default_factory=RunLimits)

    @field_validator("repository")
    @classmethod
    def reject_url_credentials(cls, value: str) -> str:
        parsed = urllib.parse.urlsplit(value)
        if parsed.username or parsed.password:
            raise ValueError("repository URL credentials are not allowed")
        return value


class PlanTarget(ContractModel):
    path: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    topics: list[str] = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=240)
    method: Literal["read_lines", "parse_structured"]
    priority: Literal["high", "medium", "low"]


class SearchTarget(ContractModel):
    pattern: str = Field(min_length=1, max_length=256)
    paths: list[str] = Field(min_length=1)
    regex: bool = False
    topics: list[str] = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=240)
    priority: Literal["high", "medium", "low"]


class AnalysisPlan(ContractModel):
    round: int = Field(ge=1, le=2)
    targets: list[PlanTarget]
    searches: list[SearchTarget] = Field(default_factory=list)


class EvidenceItem(ContractModel):
    id: str
    file: str
    line_start: int
    line_end: int
    excerpt: str
    extraction_method: ExtractionMethod
    source_context: SourceContext
    digest: str
    masked: bool = False


class RequiredInput(ContractModel):
    reason: str
    needed_for: str
    candidates: list[Any] = Field(default_factory=list)


class Claim(ContractModel):
    property_path: str
    value: Any
    evidence_refs: list[str] = Field(min_length=1)


class TopicResult(ContractModel):
    topic: str
    workload: str
    status: TopicStatus
    claims: list[Claim] = Field(default_factory=list)
    kubernetes_candidates: dict[str, Any] = Field(default_factory=dict)
    required_inputs: dict[str, RequiredInput] = Field(default_factory=dict)
    unsupported_reason: str | None = None


class ConfidenceFactors(ContractModel):
    direct_setting: bool
    referenced_by_runtime_path: bool
    agreeing_primary_sources: int = Field(ge=0)
    source_context: SourceContext
    conflict_detected: bool


class Confidence(ContractModel):
    level: Literal["high", "medium", "low"]
    factors: ConfidenceFactors


class CheckedClaim(Claim):
    confidence: Confidence


class CheckedTopicResult(ContractModel):
    topic: str
    workload: str
    status: TopicStatus
    facts: dict[str, Any] = Field(default_factory=dict)
    checked_claims: list[CheckedClaim] = Field(default_factory=list)
    kubernetes_candidates: dict[str, Any] = Field(default_factory=dict)
    required_inputs: dict[str, RequiredInput] = Field(default_factory=dict)
    migration_note: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class AssessmentResult(ContractModel):
    schema_version: Literal["migration-assessment/v1"] = "migration-assessment/v1"
    repository: dict[str, str]
    workloads: dict[str, dict[str, CheckedTopicResult]]
    required_inputs: dict[str, RequiredInput] = Field(default_factory=dict)
    risks: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)


class RunEvent(ContractModel):
    sequence: int
    stage: RunStage
    kind: Literal["started", "completed", "rejected", "warning", "failed"]
    detail: dict[str, Any] = Field(default_factory=dict)


class AssessmentRun(ContractModel):
    run_id: str
    status: RunStatus
    request: AssessmentRequest
    resolved_revision: str
    result: AssessmentResult | None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    limits_used: dict[str, int] = Field(default_factory=dict)
    model_metadata: list[ModelResponseMetadata] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


class ArtifactPaths(ContractModel):
    migration_inputs: Path
    migration_report: Path
    assessment_details: Path
    run_log: Path
```

Also define scan entries (including `resolved_revision` and `revision_source`), search matches, tool observations, model messages, tool definitions, structured model requests, `ModelResponseMetadata`, rejected targets, conflicts, and artifact paths as frozen `extra="forbid"` contracts. Use schema constants `ASSESSMENT_SCHEMA_VERSION = "migration-assessment/v1"`, `RUN_LOG_SCHEMA_VERSION = "assessment-run-log/v1"`, and `PROMPT_VERSION = "assessment-prompts/v1"` rather than repeating literals outside `contracts.py`.

- [ ] **Step 4: Define the three seams in `ports.py` and export the main interface**

```python
TModel = TypeVar("TModel", bound=BaseModel)


class StructuredModelClient(Protocol):
    def complete(self, request: ModelRequest, response_model: type[TModel]) -> ModelCompletion[TModel]: ...


class RepositoryTools(Protocol):
    def scan(self) -> RepositoryScan: ...
    def list_tree(self, path: str = ".") -> ToolObservation: ...
    def find_files(self, patterns: list[str]) -> ToolObservation: ...
    def search_text(self, pattern: str, paths: list[str], *, regex: bool = False) -> ToolObservation: ...
    def read_lines(self, path: str, line_start: int, line_end: int) -> ToolObservation: ...
    def file_info(self, path: str) -> ToolObservation: ...
    def parse_structured(self, path: str, line_start: int, line_end: int) -> ToolObservation: ...


class EventSink(Protocol):
    def emit(self, event: RunEvent) -> None: ...
    def is_cancelled(self) -> bool: ...
```

Set `[tool.hatch.build.targets.wheel].packages` to both `src/repo_analyzer` and `src/repository_assessment`. Export `assess`, `AssessmentRequest`, and `AssessmentRun` from `repository_assessment.__init__` only after `engine.py` exists; until Task 5, export the two contracts and leave `assess` out so imports cannot point at a fake implementation.

- [ ] **Step 5: Run tests and commit**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_contracts.py tests/test_determinism_and_errors.py`

Expected: both files PASS; the legacy determinism tests remain unchanged.

Commit:

```bash
git add pyproject.toml src/repository_assessment tests/assessment/test_contracts.py
git commit -m "feat(assessment): add versioned core contracts"
```

---

### Task 2: Build the Deep Read-only Repository Tools Module

**Files:**
- Create: `src/repository_assessment/repository.py`
- Test: `tests/assessment/test_repository_tools.py`
- Test: `tests/assessment/test_repository_security.py`

**Interfaces:**
- Consumes: `AssessmentRequest.limits`, repository contracts, and `RepositoryTools`.
- Produces: `LocalRepositoryTools(root, limits, revision=None)` implementing all six generic tools plus `scan()`.
- Produces: stable evidence IDs and cached observations keyed by `(digest, line_start, line_end, extraction_method)`.

- [ ] **Step 1: Write failing behavior and security tests**

```python
def test_scan_is_metadata_only_and_selected_reads_are_cached(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"start":"node app.js"}}\n')
    tools = LocalRepositoryTools(tmp_path, RunLimits())
    scan = tools.scan()
    assert [item.path for item in scan.entries] == ["package.json"]
    first = tools.parse_structured("package.json", 1, 20)
    second = tools.parse_structured("package.json", 1, 20)
    assert first == second
    assert tools.usage.physical_reads == 1
    assert first.evidence[0].file == "package.json"


def test_repository_tools_reject_traversal_and_escaping_symlink(tmp_path):
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("TOP_SECRET=visible")
    (tmp_path / "escape").symlink_to(outside)
    tools = LocalRepositoryTools(tmp_path, RunLimits())
    with pytest.raises(RepositoryAccessError, match="outside repository"):
        tools.read_lines("../outside-secret.txt", 1, 1)
    with pytest.raises(RepositoryAccessError, match="outside repository"):
        tools.read_lines("escape", 1, 1)


def test_secret_values_are_masked_before_observation(tmp_path):
    (tmp_path / ".env").write_text("DATABASE_PASSWORD=hunter2\nPORT=8080\n")
    result = LocalRepositoryTools(tmp_path, RunLimits()).read_lines(".env", 1, 2)
    assert "hunter2" not in result.content
    assert "DATABASE_PASSWORD=[REDACTED]" in result.content
    assert "PORT=8080" in result.content
    assert result.evidence[0].masked is True
```

- [ ] **Step 2: Run the focused tests and verify the implementation is missing**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_repository_tools.py tests/assessment/test_repository_security.py`

Expected: FAIL importing `repository_assessment.repository`.

- [ ] **Step 3: Implement safe resolution, bounded scanning, and source context**

Implement `_resolve()` using `Path.resolve(strict=True)`, then require `resolved == root` or `root in resolved.parents`. Reject absolute input paths, NUL bytes, traversal components, directories passed to file operations, files over `single_file_bytes`, and binary content containing NUL bytes. Exclude these directory names during scan and search:

```python
EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "vendor", ".venv", "venv",
    "target", "build", "dist", "coverage", ".cache", "__pycache__",
})

SOURCE_CONTEXT_PARTS = {
    "documentation": frozenset({"doc", "docs", "documentation"}),
    "test": frozenset({"test", "tests", "spec", "specs"}),
    "example": frozenset({"example", "examples", "demo", "samples"}),
    "development": frozenset({"dev", "development", ".devcontainer"}),
    "generated": frozenset({"target", "build", "dist", "generated"}),
}
```

Sort directory entries and every returned path using repository-relative POSIX strings. Stop at `tree_entries` and include `truncated=True`; do not interpret truncation as file absence. `scan()` may read file metadata and names but not file content.

Resolve the repository revision once during `scan()`: preserve `AssessmentRequest.revision` when the runtime supplied an already-resolved revision; otherwise run `git -C <root> rev-parse --verify HEAD` with a five-second timeout and validate the result as a 40- or 64-character hexadecimal object ID. If the sandbox-visible directory is not a Git checkout, use the stable SHA-256 digest of sorted scan-entry metadata as the local revision identifier and record `revision_source="tree_digest"`.

- [ ] **Step 4: Implement bounded search/read/structured parse and masking**

Use `json.loads`, `ruamel.yaml.YAML(typ="safe")`, `xml.etree.ElementTree`, `tomllib.loads`, and a deterministic properties parser that splits the first unescaped `=` or `:`. Parse only the approved range; reject partial XML/JSON/TOML documents with a narrow `UnsupportedFormatError` rather than silently widening the read.

Apply masking before constructing `ToolObservation` or `EvidenceItem`:

```python
SECRET_NAME = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)"
)


def mask_text(text: str) -> tuple[str, bool]:
    masked = False
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        match = re.match(r"^(\s*[^#\s][^=:]*)(\s*[:=]\s*)(.*?)(\r?\n)?$", line)
        if match and SECRET_NAME.search(match.group(1)):
            ending = match.group(4) or ""
            lines.append(f"{match.group(1)}{match.group(2)}[REDACTED]{ending}")
            masked = True
        else:
            lines.append(line)
    return "".join(lines), masked
```

After structured parsing, recursively replace values whose mapping key matches `SECRET_NAME` with `[REDACTED]` before JSON serialization. Search operates line by line, rejects lines over 16 KiB and regex patterns over 256 characters, checks the run deadline between files, and returns at most `matches_per_search` stable matches.

Create evidence IDs after sorting extracted observations by `(file, line_start, line_end, extraction_method)` so the same run yields `E001`, `E002`, and so on deterministically. Hash original file bytes for the digest, but never retain unmasked excerpts in an observation or cache value.

- [ ] **Step 5: Verify all repository-tool limits and commit**

Add parameterized tests for 512 KiB file rejection, 200-line clipping rejection, 20-search exhaustion, 100-match truncation, 20,000-entry scan truncation, binary rejection, generated/vendor exclusion, regex errors, and stable SHA-256 digests.

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_repository_tools.py tests/assessment/test_repository_security.py`

Expected: PASS, including a target-repository before/after digest assertion.

Commit:

```bash
git add src/repository_assessment/repository.py tests/assessment/test_repository_tools.py tests/assessment/test_repository_security.py
git commit -m "feat(assessment): add bounded repository tools"
```

---

### Task 3: Add Deterministic Plan and Evidence Checks

**Files:**
- Create: `src/repository_assessment/evidence.py`
- Test: `tests/assessment/test_plan_validation.py`
- Test: `tests/assessment/test_evidence_check.py`

**Interfaces:**
- Consumes: `AnalysisPlan`, scan entries, extracted `EvidenceItem` objects, topic results, repository tools, and remaining limits.
- Produces: `validate_plan(...) -> ValidatedPlan` and `check_topics(...) -> EvidenceCheckResult`.
- Guarantees: no unchecked claim reaches `AssessmentResult`; conflicts retain every candidate value.

- [ ] **Step 1: Write failing plan-validation and evidence-check tests**

```python
def test_plan_rejects_duplicate_invalid_and_over_budget_targets(scan):
    plan = AnalysisPlan(round=1, targets=[
        target("package.json", 1, 20),
        target("package.json", 1, 20),
        target("missing.json", 1, 20),
        target("README.md", 20, 1),
    ])
    checked = validate_plan(plan, scan, RunLimits(selected_targets=2))
    assert [item.path for item in checked.targets] == ["package.json"]
    assert [item.reason for item in checked.rejected] == [
        "duplicate_target", "path_not_in_scan", "invalid_line_range",
    ]


def test_primary_runtime_conflict_is_preserved_as_contradicted(repo_tools):
    evidence = [
        evidence_item("E001", "Dockerfile", 8, 'CMD ["node", "a.js"]', "primary"),
        evidence_item("E002", "compose.yml", 12, 'command: ["node", "b.js"]', "primary"),
    ]
    topic = TopicResult(
        topic="entrypoint",
        workload="app",
        status="answered",
        claims=[
            Claim(property_path="command", value=["node", "a.js"], evidence_refs=["E001"]),
            Claim(property_path="command", value=["node", "b.js"], evidence_refs=["E002"]),
        ],
    )
    result = check_topics([topic], evidence, repo_tools)
    assert result.topics[0].status == "contradicted"
    assert result.conflicts[0].candidates == [["node", "a.js"], ["node", "b.js"]]
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_plan_validation.py tests/assessment/test_evidence_check.py`

Expected: FAIL importing `validate_plan` and `check_topics`.

- [ ] **Step 3: Implement plan validation as one pure operation**

Validate read targets in this order so rejection output is deterministic: normalized path/range, scan membership, method compatibility, duplicate `(path, range, method)`, per-read limit, total target limit. Validate searches by pattern length, normalized scanned path prefixes, duplicate `(pattern, paths, regex)`, remaining search-call count, and match cap. Preserve rejected operations with the original target, machine reason, and human detail. Allow a second plan only when `round == 2`; merge it with cached first-round operations and count only newly accepted operations toward physical extraction.

```python
def validate_plan(
    plan: AnalysisPlan,
    scan: RepositoryScan,
    limits: RunLimits,
    prior_targets: Sequence[PlanTarget] = (),
    prior_searches: Sequence[SearchTarget] = (),
) -> ValidatedPlan:
    """Return accepted reads/searches and stable, narrow rejection records."""
```

- [ ] **Step 4: Implement the ten evidence checks and factor-based confidence**

For each claim, resolve every evidence ID and use cached `file_info`/`read_lines` observations to verify file existence, line validity, masked excerpt equality, digest equality, allowed method, visible source context, production/source-context precedence, conflicts, evidence-or-required-input presence, and Secret masking. A README value cannot override a conflicting primary value. Documentation, test, example, and development evidence may produce low confidence but cannot become the sole production fact.

Use this exact confidence function:

```python
def confidence_from(factors: ConfidenceFactors) -> Confidence:
    if factors.conflict_detected:
        return Confidence(level="low", factors=factors)
    if factors.source_context == "primary" and (
        (factors.direct_setting and factors.referenced_by_runtime_path)
        or factors.agreeing_primary_sources >= 2
    ):
        return Confidence(level="high", factors=factors)
    if factors.source_context == "primary" or factors.agreeing_primary_sources >= 1:
        return Confidence(level="medium", factors=factors)
    return Confidence(level="low", factors=factors)
```

Normalize topic status after checks: conflicts become `contradicted`; rejected claims with usable claims become `partial`; no usable claims plus a tool-format limitation becomes `unsupported`; repository-undecidable properties become `unresolved`; only enough checked evidence with no material gap stays `answered`.

- [ ] **Step 5: Add the remaining evidence cases, run, and commit**

Add tests for missing files, invalid ranges, changed digest, excerpt mismatch, unsupported extraction method, hidden source context, README/runtime conflict, test/example production promotion, unmasked secrets, claim without evidence, unresolved property without `RequiredInput`, and prompt-injection text remaining ordinary excerpt data.

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_plan_validation.py tests/assessment/test_evidence_check.py`

Expected: PASS with all five topic statuses covered.

Commit:

```bash
git add src/repository_assessment/evidence.py tests/assessment/test_plan_validation.py tests/assessment/test_evidence_check.py
git commit -m "feat(assessment): verify plans and evidence"
```

---

### Task 4: Implement the OpenAI-compatible Structured Model Adapter

**Files:**
- Create: `src/repository_assessment/openai_compatible.py`
- Create: `src/repository_assessment/recorded.py`
- Test: `tests/assessment/test_openai_compatible.py`

**Interfaces:**
- Consumes: provider-neutral `ModelRequest` and a Pydantic response model.
- Produces: `OpenAICompatibleModelClient.complete(...)` using only `POST /v1/chat/completions`.
- Produces: `RecordedModelClient.from_file(path)` using the same `StructuredModelClient` interface without network access.
- Guarantees: function-tool calls are preferred, strict JSON text is accepted as fallback, and invalid output gets at most one repair request.

- [ ] **Step 1: Write failing adapter contract tests with a fake `urlopen`**

```python
def test_function_call_arguments_are_validated_without_sdk_types(monkeypatch):
    requests = install_fake_responses(monkeypatch, [{
        "choices": [{"message": {"tool_calls": [{
            "type": "function",
            "function": {"name": "submit_analysis_plan", "arguments": '{"round":1,"targets":[]}'},
        }]}}],
    }])
    client = OpenAICompatibleModelClient(
        base_url="http://model.internal:30000",
        model="qwen3-coder",
        api_key="secret",
        timeout_seconds=30,
    )
    completion = client.complete(plan_request(), AnalysisPlan)
    assert completion.value == AnalysisPlan(round=1, targets=[])
    assert requests[0].full_url == "http://model.internal:30000/v1/chat/completions"
    assert "secret" not in completion.metadata.model_dump_json()


def test_invalid_json_gets_one_repair_then_narrow_failure(monkeypatch):
    requests = install_fake_responses(monkeypatch, [text_response("{"), text_response("still invalid")])
    client = configured_client(schema_repairs=1)
    with pytest.raises(ModelSchemaError):
        client.complete(plan_request(), AnalysisPlan)
    assert len(requests) == 2
```

- [ ] **Step 2: Run focused tests and verify the adapter is missing**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_openai_compatible.py`

Expected: FAIL importing `OpenAICompatibleModelClient`.

- [ ] **Step 3: Implement URL normalization, request construction, and response decoding**

Normalize a server root to `/v1`; preserve an existing `/v1`; reject paths ending in `/responses`. Build a plain JSON Chat Completions request containing provider-neutral messages, function tools generated from `response_model.model_json_schema()`, `tool_choice="auto"`, and deterministic sampling settings when supported (`temperature=0`). Decode the first matching function call; if absent, decode `message.content` as strict JSON.

```python
def _endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/responses"):
        raise ValueError("Responses API is not supported")
    if not root.endswith("/v1"):
        root += "/v1"
    return root + "/chat/completions"
```

Record only redacted endpoint host, model name, prompt version, SHA-256 response digest, attempt count, and whether `tool_call` or `json_text` was used. Never record headers, API keys, or full raw responses in the core result.

- [ ] **Step 4: Implement one schema repair and narrow transport errors**

On JSON/Pydantic failure, append a provider-neutral user message containing the validation error and the exact response schema, then retry once. Translate HTTP errors, timeout, invalid response shape, and exhausted repair into `ModelUnavailableError`, `ModelProtocolError`, or `ModelSchemaError`; do not return an empty successful model value.

Implement `RecordedModelClient` over a JSON array of `{stage, schema_name, value, metadata}` entries. On each `complete` call, consume exactly one entry, require matching stage and response-model class name, validate `value` with `response_model.model_validate`, and return the recorded redacted metadata. Raise `RecordedResponseMismatch` on exhausted, extra, reordered, or schema-mismatched entries; never fall back to a live endpoint.

- [ ] **Step 5: Run adapter tests and commit**

Add tests for `/v1` normalization, JSON text fallback, malformed tool arguments, unknown tool name, HTTP timeout, no choices, redacted metadata, and zero-repair configuration.

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_openai_compatible.py tests/test_llm_tool_call_demo.py`

Expected: PASS; the existing SGLang live-demo request contract remains unchanged.

Commit:

```bash
git add src/repository_assessment/openai_compatible.py src/repository_assessment/recorded.py tests/assessment/test_openai_compatible.py
git commit -m "feat(assessment): add chat completions model adapter"
```

---

### Task 5: Implement the Assessment Engine State Machine

**Files:**
- Create: `src/repository_assessment/prompts.py`
- Create: `src/repository_assessment/engine.py`
- Modify: `src/repository_assessment/__init__.py`
- Test: `tests/assessment/fakes.py`
- Test: `tests/assessment/test_engine.py`
- Test: `tests/fixtures/assessment/recorded/node-basic.json`

**Interfaces:**
- Consumes: all prior contracts, `StructuredModelClient`, `RepositoryTools`, `EventSink`, `validate_plan`, and `check_topics`.
- Produces: `assess(request, model_client, repository_tools, event_sink) -> AssessmentRun`.
- Guarantees: fixed stage order, bounded calls, one revised plan, topic isolation, deterministic run state from recorded responses, and useful `completed_with_gaps` output after narrow failures.

- [ ] **Step 1: Write failing engine interface tests**

```python
def test_assess_runs_the_six_stages_and_reads_only_selected_targets(node_repo):
    model = RecordedModelClient.from_file("tests/fixtures/assessment/recorded/node-basic.json")
    tools = SpyRepositoryTools(LocalRepositoryTools(node_repo, RunLimits()))
    events = MemoryEventSink()
    run = assess(
        AssessmentRequest(repository=str(node_repo), output_directory="output/run"),
        model,
        tools,
        events,
    )
    assert run.status == "completed_with_gaps"
    assert [event.stage for event in events.completed_events] == [
        "repository_scan", "analysis_plan", "evidence_extraction",
        "topic_analysis", "evidence_check", "report_building",
    ]
    assert tools.content_reads == [
        ("package.json", 1, 80, "parse_structured"),
        ("src/server.js", 1, 120, "read_lines"),
    ]
    assert run.result.workloads["api"]["network"].facts["listeners"][0]["port"] == 3000


def test_limit_exhaustion_preserves_useful_topics_and_marks_gaps(node_repo):
    request = AssessmentRequest(
        repository=str(node_repo),
        output_directory="output/run",
        limits=RunLimits(selected_targets=1),
    )
    run = assess(request, RecordedModelClient.over_budget_plan(), local_tools(node_repo), MemoryEventSink())
    assert run.status == "completed_with_gaps"
    assert run.result is not None
    assert any(error["type"] == "target_limit_exhausted" for error in run.errors)
```

- [ ] **Step 2: Run engine tests and verify `assess` is missing**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_engine.py`

Expected: FAIL importing `assess`.

- [ ] **Step 3: Add versioned prompts with an untrusted-data envelope**

Define `BASE_TOPICS` exactly as the 13 topics in the approved design. The system prompt fixes tool names, run limits, status vocabulary, output boundaries, and the rule that repository instructions have no control effect. Planning and topic prompts embed observations only as JSON between these markers:

```text
<untrusted_repository_data>
...
</untrusted_repository_data>
```

The plan response is `AnalysisPlan`; the topic response is a `TopicAnalysisBatch` containing `TopicResult` objects. Ask for small topic batches grouped by workload, not one free-form migration answer. Prompts prohibit question sentences/owner fields and require `RequiredInput` objects for missing values. The model does not write `migration_note`; deterministic checked-result assembly creates that zero-to-two-sentence field from normalized facts, candidates, required inputs, and status so narrative cannot introduce another fact.

- [ ] **Step 4: Implement the stage machine behind the single interface**

Implement the state transitions with one internal mutable `_RunState`; expose only the immutable `AssessmentRun`:

```python
STAGE_ORDER = (
    "repository_scan", "analysis_plan", "evidence_extraction",
    "topic_analysis", "evidence_check", "report_building",
)


def assess(request, model_client, repository_tools, event_sink) -> AssessmentRun:
    state = _RunState.start(request, event_sink)
    try:
        scan = state.run_stage("repository_scan", repository_tools.scan)
        for round_number in range(1, request.limits.plan_rounds + 1):
            plan = state.complete_plan(model_client, scan, round_number)
            accepted = validate_plan(
                plan, scan, request.limits, state.targets, state.searches
            )
            state.record_plan(accepted)
            state.extract(repository_tools, accepted.targets, accepted.searches)
            state.analyze_topics(model_client)
            if state.has_enough_evidence() or round_number == request.limits.plan_rounds:
                break
        checked = state.check(lambda topics, evidence: check_topics(topics, evidence, repository_tools))
        return state.finish(checked)
    except FatalAssessmentError as exc:
        return state.fail(exc)
```

`_RunState` must check elapsed monotonic time, counters, and `event_sink.is_cancelled()` before every model/tool operation. Construct it with `event_sink` so every transition emits through the injected interface and records the same event in run state. When `request.run_id` is supplied, preserve it exactly; OpenShell supplies its runtime-owned run identifier. Otherwise derive `run_id` from the SHA-256 prefix of normalized repository source, resolved revision, prompt version, and schema version. This fallback makes recorded local replays byte-stable and contains no timestamps or absolute temporary paths.

Fatal errors are limited to unreadable repository, model endpoint unavailable for all allowed attempts, invalid core state/output schema, or security rules preventing all safe repository access. Record parser, target, single-response, and topic failures at the narrowest level and continue when any checked result remains.

- [ ] **Step 5: Implement topic sufficiency and final run status**

Stop selecting evidence for a topic once its required properties are checked and unconflicted. Request round 2 only for explicit extraction gaps, rejected/unsupported targets with an alternative method, or unresolved conflicts that another scanned primary file could settle. Do not request more evidence merely to raise medium confidence to high.

Map checked topics into workload categories `identity`, `build_and_image`, `runtime_and_lifecycle`, `network`, `dependencies`, `configuration`, `storage_and_state`, `health_and_observability`, `resources_and_scaling`, `security_and_access`, and `deployment`. Preserve these property groups when evidence or required inputs exist:

- `identity`: name, role, source root, process type, language, framework, runtime/version, and workload relations.
- `build_and_image`: tool/command/working directory/context/definition, artifact type/path, base or builder image, image reference, OS, and architecture.
- `runtime_and_lifecycle`: containers, command/args/working directory, user/UID/GID, process count, init/migration steps, stop signal, and graceful shutdown.
- `network`: listener name/port/transport/application protocol/bind/base path, Service port/targetPort candidate, external route candidate, and outbound traffic.
- `dependencies`: type/direction/protocol, endpoint/port/TLS/auth configuration, startup behavior, and internal/external relation.
- `configuration`: key, Config/Secret class, build/runtime stage, delivery method/path, required/default state, and consumer.
- `storage_and_state`: path/purpose/read-write mode, temporary/persistent/unknown state, replica sharing, session/cache behavior, and migration need.
- `health_and_observability`: separate startup/readiness/liveness candidates plus logs, metrics, and tracing facts.
- `resources_and_scaling`: CPU/memory/temporary-storage requests/limits plus replica/autoscaling required inputs; never invent their values.
- `security_and_access`: non-root compatibility, UID/GID, privilege/capabilities, writable paths, read-only root compatibility, ServiceAccount, and Kubernetes API access.
- `deployment`: controller and companion-object candidates plus rollout, disruption, scheduling, and topology required inputs.

Add Job completion/retry/timeout/parallelism/idempotency, CronJob schedule/time-zone/deadline/concurrency, stateful identity/storage/order/backup/recovery, init/sidecar ordering/completion/shared-files/resources/lifecycle, and special platform properties only when checked claims make the condition relevant.

Return `completed` only when required topics are answered; return `completed_with_gaps` for any partial, unresolved, unsupported, contradicted, rejected, or limit-bound required topic; return `failed` only for the fatal conditions above.

- [ ] **Step 6: Add engine failure/limit tests, run, and commit**

Test plan-round limit, model-call limit, total timeout, cancellation event, cached duplicate target, a single topic schema failure, unsupported structured format, second-plan gap closure, model outage, unreadable repository, and deterministic replay from recorded responses.

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_engine.py tests/assessment/test_repository_security.py tests/assessment/test_evidence_check.py`

Expected: PASS; no engine module imports `repo_analyzer`, OpenShell, `openai`, or `urllib`.

Commit:

```bash
git add src/repository_assessment tests/assessment tests/fixtures/assessment/recorded/node-basic.json
git commit -m "feat(assessment): orchestrate bounded assessment runs"
```

---

### Task 6: Write the Four Deterministic Assessment Artifacts

**Files:**
- Create: `src/repository_assessment/writers.py`
- Test: `tests/assessment/test_writers.py`
- Test: `tests/fixtures/assessment/golden/node-basic/migration-inputs.yaml`
- Test: `tests/fixtures/assessment/golden/node-basic/migration-report.md`
- Test: `tests/fixtures/assessment/golden/node-basic/assessment-details.json`
- Test: `tests/fixtures/assessment/golden/node-basic/run-log.json`

**Interfaces:**
- Consumes: checked `AssessmentRun` and a caller-approved output directory.
- Produces: `write_artifacts(run, output_directory) -> ArtifactPaths`.
- Guarantees: stable ordering, atomic file replacement, no new narrative facts, and no full details embedded in runtime responses.

- [ ] **Step 1: Write failing golden and value-boundary tests**

```python
def test_writers_create_exact_four_files_without_question_or_owner_fields(tmp_path, checked_run):
    paths = write_artifacts(checked_run, tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "assessment-details.json", "migration-inputs.yaml",
        "migration-report.md", "run-log.json",
    ]
    yaml_text = paths.migration_inputs.read_text()
    assert "facts:" in yaml_text
    assert "kubernetes_candidates:" in yaml_text
    assert "required_inputs:" in yaml_text
    assert "owner:" not in yaml_text
    assert "question" not in yaml_text


def test_replayed_writes_are_byte_identical(tmp_path, checked_run):
    first = write_artifacts(checked_run, tmp_path / "first")
    second = write_artifacts(checked_run, tmp_path / "second")
    for field in ArtifactPaths.model_fields:
        assert getattr(first, field).read_bytes() == getattr(second, field).read_bytes()
```

- [ ] **Step 2: Run writer tests and verify the module is missing**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_writers.py`

Expected: FAIL importing `write_artifacts`.

- [ ] **Step 3: Implement developer YAML and details JSON**

Build `migration-inputs.yaml` from `AssessmentResult`, preserving workload/category order and omitting only empty categories. Do not use empty arrays, `false`, or `null` as absence proof; keep `status` or `required_inputs` when absence is unproven. Use ruamel safe dumping with explicit indentation and no anchors.

`assessment-details.json` contains the full checked topic list, evidence items, confidence factors, conflicts, rejected targets, and narrow errors. `run-log.json` contains schema/prompt versions, resolved revision, effective limits, event sequence, selected targets and purposes, evidence digests/methods, redacted model metadata, retries, errors, and final statuses. Serialize with UTF-8, sorted dynamic-map keys, two-space indentation, and one trailing newline.

- [ ] **Step 4: Implement Korean Markdown from checked fields only**

Render workload headings and direct `key: value` bullets in the same category order as YAML. The Markdown may combine a category's checked `migration_note` with its facts/candidates/required inputs but must not call the model or infer another fact. Label Kubernetes objects as candidates and conflicts as conflicts. Render no owner/question section and no readiness score.

Use atomic writes: create each file under the approved output directory with a `.tmp` suffix, `flush()` and `os.fsync()`, then `os.replace()` the four known files. If normal Markdown rendering fails after machine output is valid, write a deterministic Korean fallback report that says the narrative is unavailable and points to `migration-inputs.yaml` and `assessment-details.json`; record the narrative error without deleting or replacing valid machine results.

- [ ] **Step 5: Compare goldens, run, and commit**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_writers.py`

Expected: PASS and all four golden files match byte-for-byte.

Commit:

```bash
git add src/repository_assessment/writers.py tests/assessment/test_writers.py tests/fixtures/assessment/golden
git commit -m "feat(assessment): write migration input artifacts"
```

---

### Task 7: Add the CLI Composition Root and OpenShell Runtime Adapter

**Files:**
- Create: `src/repository_assessment/cli.py`
- Create: `integrations/openshell_assessment.py`
- Create: `openshell/policy.yaml`
- Modify: `pyproject.toml`
- Test: `tests/assessment/test_cli.py`
- Test: `tests/assessment/test_openshell_adapter.py`

**Interfaces:**
- Consumes: local repository path supplied by runtime policy, OpenAI-compatible configuration, and approved output directory.
- Produces: `repository-assessment assess ...` and a JSON-line OpenShell process adapter returning only run summary plus artifact paths.
- Guarantees: core stays runtime/provider independent; cancellation and timeout map to core signals; OpenShell policy denies arbitrary egress.

- [ ] **Step 1: Write failing CLI and runtime smoke tests**

```python
def test_cli_emits_compact_json_summary(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "compose_and_run", lambda args: completed_runtime_result(tmp_path))
    exit_code = cli.main([
        "assess", "--repo", "tests/fixtures/assessment/node-basic",
        "--output-dir", str(tmp_path), "--base-url", "https://inference.local/v1",
        "--model", "qwen3-coder",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["run_status"] == "completed_with_gaps"
    assert set(payload["artifacts"]) == {
        "migration_inputs", "migration_report", "assessment_details", "run_log",
    }
    assert "result" not in payload


def test_openshell_adapter_streams_events_and_never_returns_full_details(monkeypatch):
    output = io.StringIO()
    result = run_openshell_assessment(runtime_request(), output=output)
    assert '"stage":"repository_scan"' in output.getvalue()
    assert result["schema_version"] == "openshell-assessment-result/v1"
    assert "workloads" not in result
```

- [ ] **Step 2: Run smoke tests and verify entry points are missing**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_cli.py tests/assessment/test_openshell_adapter.py`

Expected: FAIL importing the CLI/runtime entry points.

- [ ] **Step 3: Implement the generic CLI composition root**

Add `[project.scripts] repository-assessment = "repository_assessment.cli:main"` while preserving `repo-analyzer`. The `assess` subcommand always requires `--repo` and `--output-dir`. Live mode requires `--base-url` and `--model`, reads the API key only from `--api-key-env` (default `OPENAI_API_KEY`), and constructs `OpenAICompatibleModelClient`. Offline replay mode instead requires `--recorded-responses` and constructs `RecordedModelClient`; reject mixing recorded responses with live endpoint credentials. Both modes accept `--run-id`, `--revision`, `--timeout-seconds`, and limit overrides, construct `LocalRepositoryTools(repo, limits, revision=args.revision)` and `JsonLineEventSink`, call `assess`, and then call `write_artifacts` for non-failed machine results.

Exit codes are `0` for completed, `1` for completed-with-gaps, `2` for invalid arguments/security rejection, and `3` for failed runs. Standard output is one compact JSON object; progress goes to standard error as JSON lines. Never print the API key or full assessment details.

- [ ] **Step 4: Implement the OpenShell adapter and policy**

`integrations/openshell_assessment.py` accepts a plain `OpenShellAssessmentRequest` containing sandbox-visible repository path, revision, output directory, base URL, and model. It maps runtime cancellation to a `CancellationToken`, streams `RunEvent` JSON lines, and returns:

```python
{
    "schema_version": "openshell-assessment-result/v1",
    "run_id": run.run_id,
    "run_status": run.status,
    "workload_count": len(run.result.workloads) if run.result else 0,
    "gap_count": count_gaps(run),
    "artifacts": artifact_paths.model_dump(mode="json"),
}
```

Create `openshell/policy.yaml` using OpenShell policy schema version `1`, `filesystem_policy.include_workdir: false`, `/app` and `/sandbox/repository` as explicit read-only paths, `/sandbox/output` and `/tmp` as the only explicit read-write paths, `landlock.compatibility: hard_requirement`, and unprivileged `sandbox` user/group. Do not allow GitHub, package registries, shells, curl, or arbitrary model hosts. The adapter defaults to `https://inference.local/v1`, which OpenShell routes through its configured inference provider outside normal egress rules.

- [ ] **Step 5: Validate CLI isolation and commit**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_cli.py tests/assessment/test_openshell_adapter.py
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run repository-assessment --help
```

Expected: tests PASS; help shows `assess`; importing `repository_assessment.engine` does not load `integrations.openshell_assessment`, `urllib.request`, or `repo_analyzer`.

Commit:

```bash
git add pyproject.toml src/repository_assessment/cli.py integrations/openshell_assessment.py openshell/policy.yaml tests/assessment/test_cli.py tests/assessment/test_openshell_adapter.py
git commit -m "feat(assessment): add cli and openshell adapter"
```

---

### Task 8: Cover the Eight Required Repository Scenarios

**Files:**
- Create: `tests/fixtures/assessment/node-basic/`
- Create: `tests/fixtures/assessment/java-no-container/`
- Create: `tests/fixtures/assessment/script-only/`
- Create: `tests/fixtures/assessment/monorepo/`
- Create: `tests/fixtures/assessment/readme-conflict/`
- Create: `tests/fixtures/assessment/no-production-secrets/`
- Create: `tests/fixtures/assessment/unsupported-format/`
- Create: `tests/fixtures/assessment/source-context-conflict/`
- Create: `tests/fixtures/assessment/recorded/*.json`
- Create: `tests/assessment/test_required_scenarios.py`

**Interfaces:**
- Consumes: public `assess` interface, local repository tools, recorded model adapter, evidence checker, and writers.
- Produces: an offline acceptance suite proving generic tools handle unknown stacks without changing the core.

- [ ] **Step 1: Add the eight minimal fixtures and recorded responses**

Keep each fixture under 20 text files and include only the facts needed for its scenario:

1. `node-basic`: `package.json`, `Dockerfile`, `compose.yml`, and `src/server.js`.
2. `java-no-container`: `pom.xml`, `src/main/webapp/WEB-INF/web.xml`, and an application properties file; no Docker files.
3. `script-only`: `run.sh`, `.env.example`, and a systemd unit.
4. `monorepo`: independent `api/package.json` and `worker/pyproject.toml` source roots.
5. `readme-conflict`: README port 8080 and primary runtime port 9090.
6. `no-production-secrets`: Secret key names/default placeholders but no production address/value.
7. `unsupported-format`: readable source plus one unsupported binary/proprietary config topic.
8. `source-context-conflict`: primary configuration beside test/example/development candidates.

Recorded responses must select exact fixture ranges, reference stable evidence IDs, use all five topic statuses across the suite, and contain one second-plan revision. They must not contain facts missing from their corresponding repository fixture.

- [ ] **Step 2: Write the parameterized acceptance test**

```python
@pytest.mark.parametrize(
    ("fixture", "assertion"),
    [
        ("node-basic", assert_generic_node_result),
        ("java-no-container", assert_docker_free_java_result),
        ("script-only", assert_script_runtime_result),
        ("monorepo", assert_two_workloads),
        ("readme-conflict", assert_runtime_wins_and_conflict_is_recorded),
        ("no-production-secrets", assert_required_inputs_without_values),
        ("unsupported-format", assert_topic_not_repository_is_unsupported),
        ("source-context-conflict", assert_primary_context_is_preserved),
    ],
)
def test_required_scenario(fixture, assertion, assessment_fixture_root, tmp_path):
    repo = assessment_fixture_root / fixture
    model = RecordedModelClient.from_file(
        assessment_fixture_root / "recorded" / f"{fixture}.json"
    )
    run = assess(request_for(repo, tmp_path), model, local_tools(repo), MemoryEventSink())
    assertion(run)
    assert_tree_digest_unchanged(repo)
```

- [ ] **Step 3: Run and close scenario gaps without stack-specific core branches**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_required_scenarios.py`

Expected: all eight cases PASS. Fix only generic tool, prompt, validation, or mapping behavior exposed by a failing case; do not add `if language == ...` decisions to `engine.py`. If exact Maven/Gradle parsing materially improves the Java case, add it later as an optional adapter returning `EvidenceItem`, not as a prerequisite for this acceptance gate.

- [ ] **Step 4: Run compatibility and determinism suites, then commit**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q`

Expected: all legacy and new tests PASS offline; no fixture changes after assessment; recorded-response replays produce byte-identical machine artifacts.

Commit:

```bash
git add tests/fixtures/assessment tests/assessment/test_required_scenarios.py src/repository_assessment
git commit -m "test(assessment): cover required repository scenarios"
```

---

### Task 9: Update Product Documentation and Supersede Conflicting Guidance

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/CLAUDE.md`
- Modify: `tests/CLAUDE.md`
- Modify: `docs/adr/0001-openshell-repository-assessment-package.md`
- Modify: `skills/kubernetes-repository-analyzer/SKILL.md`
- Create: `docs/ASSESSMENT.md`
- Test: `tests/assessment/test_documentation_contract.py`

**Interfaces:**
- Consumes: implemented CLI, schema versions, limits, artifact names, and OpenShell v1 policy.
- Produces: exact operator/developer instructions matching implemented behavior.

- [ ] **Step 1: Write documentation contract tests**

```python
def test_assessment_docs_match_public_contract():
    text = Path("docs/ASSESSMENT.md").read_text()
    assert "repository-assessment assess" in text
    assert "migration-inputs.yaml" in text
    assert "assessment-details.json" in text
    assert "completed_with_gaps" in text
    assert "https://inference.local/v1" in text
    assert "agent.yaml" not in text
    assert "readiness score" not in text.lower()


def test_legacy_cli_remains_documented_as_compatibility_path():
    readme = Path("README.md").read_text()
    assert "repo-analyzer analyze" in readme
    assert "compatibility" in readme.lower()
```

- [ ] **Step 2: Run documentation tests and verify the new guide is missing**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_documentation_contract.py`

Expected: FAIL because `docs/ASSESSMENT.md` does not exist.

- [ ] **Step 3: Document the implemented workflow and compatibility boundary**

`docs/ASSESSMENT.md` must show local and OpenShell commands, all four artifacts, exact status semantics, the 13 topics, default run limits, read-only/security behavior, `inference.local` configuration, and an offline recorded-response test command. Explain that OpenShell is a sandbox runtime launched with `openshell sandbox create`, not a repository-owned `agent.yaml` package system.

Update the root memory to make the LLM-led assessment the product direction while preserving the old analyzer invariants under a clearly labeled compatibility section. Update directory indexes with actual files and test names. Update the existing analyzer skill so it explicitly invokes the compatibility workflow; add a separate assessment skill only in a later change after the new CLI has proven stable.

Mark ADR 0001 as `Superseded by ADR 0002` and add a dated note explaining that current official OpenShell uses sandbox creation plus schema-v1 policies, so the obsolete custom package/`agent.yaml` assumption is not implemented. Keep its historical text intact below the supersession note.

- [ ] **Step 4: Run documentation and full regression verification**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/assessment/test_documentation_contract.py
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
git diff --check
```

Expected: documentation test PASS, full offline suite PASS, and `git diff --check` exits 0.

- [ ] **Step 5: Perform a local end-to-end recorded run and commit**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run repository-assessment assess \
  --repo tests/fixtures/assessment/node-basic \
  --output-dir output/assessment-node-basic \
  --recorded-responses tests/fixtures/assessment/recorded/node-basic.json
```

Expected: exit code `1` for `completed_with_gaps`; standard output contains only compact summary/artifact paths; exactly four files exist under `output/assessment-node-basic`; no source fixture changes appear in `git status --short`.

Commit:

```bash
git add README.md CLAUDE.md docs tests/CLAUDE.md skills/kubernetes-repository-analyzer/SKILL.md
git commit -m "docs(assessment): document llm-led workflow"
```

---

## Final Verification Gate

Before calling the implementation complete, run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run repository-assessment --help
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run repo-analyzer --help
git diff --check
git status --short
```

Expected results:

- Every legacy and new test passes offline.
- Both CLI entry points load, and `repo-analyzer analyze` behavior remains compatible.
- The engine import graph contains no OpenShell, provider SDK, `repo_analyzer`, or network transport imports.
- The eight required scenarios pass through the public `assess` interface.
- Replayed model responses produce byte-identical checked machine artifacts.
- The working tree contains only intentional implementation/documentation changes; pre-existing unrelated edits remain untouched.

Do not run a live model or OpenShell validation as part of the offline completion gate. Perform those as a separately approved validation step because they require external runtime state, network policy configuration, and model availability.
