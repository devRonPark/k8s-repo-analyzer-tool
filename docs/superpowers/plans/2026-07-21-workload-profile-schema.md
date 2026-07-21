# Workload Profile Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit workload build/runtime/profile/relationship data to `AnalysisResult` so developer-facing and LLM answers explain repository-specific Kubernetes migration context without relying on prompt-only reconstruction.

**Architecture:** Keep the existing `components`, `workload_mappings`, and top-level finding lists for compatibility, then add a derived `workload_profiles` view that groups repository-backed facts per deployable workload. Analyzer rules continue to emit deterministic facts; a new profile assembly step converts those facts into `Image Build Profile`, `Runtime Deployment Profile`, Kubernetes candidate objects, relationships, and open decisions.

**Tech Stack:** Python, Pydantic v2, pytest, existing `repo_analyzer` parser/rule/reporter modules.

## Global Constraints

- Use additive schema evolution: do not remove or rename existing `AnalysisResult` fields in this change.
- All new profile claims must be backed by existing repository facts, existing derived findings, or explicit unresolved inputs.
- Treat Kubernetes mappings as candidates, not final manifests.
- Keep workload controller candidates separate from companion object candidates such as Service, PVC, ConfigMap, Secret, Ingress, and Gateway.
- Split build facts into `image_build_profile` and runtime facts into `runtime_deployment_profile`; do not put runtime command, ports, volumes, probes, or relationships under a single generic build method.
- Relationship facts must identify their evidence type, such as Compose `depends_on`, startup order, runtime dependency, configuration reference, or port/exposure evidence.
- Negative claims remain scoped to scanned repository facts.
- Preserve deterministic output ordering.

---

## Problem Statement

Current analyzer output has the facts developers need, but they are scattered:

- `Component` contains flat fields such as `build_tool`, `build_command`, `command`, `container_ports`, `environment`, `depends_on`, and `workload_candidate`.
- Top-level lists such as `networking`, `configuration`, `secrets`, `storage`, `runtime_dependencies`, `startup_order`, `health_checks`, `build_time_constraints`, and `container_image` hold related facts separately.
- `workload_mappings` mixes workload controller and companion object wording in one string, for example `Deployment + ClusterIP Service`.
- The LLM prompt must reassemble build method, runtime behavior, Kubernetes candidates, and relationships from scattered fields. This creates brittle answers when repository shapes differ.

The schema should instead expose a workload-centered handoff directly.

## Target Schema Shape

Add these models to `src/repo_analyzer/models.py`.

```python
RelationshipType = Literal[
    "startup_order",
    "runtime_dependency",
    "configuration_reference",
    "network_consumer",
    "build_time_binding",
]

KubernetesObjectKind = Literal[
    "Deployment",
    "StatefulSet",
    "Job",
    "CronJob",
    "DaemonSet",
    "init_container",
    "Service",
    "PVC",
    "ConfigMap",
    "Secret",
    "Ingress",
    "Gateway",
]

class WorkloadRelationship(_Model):
    source: str
    target: str
    relationship_type: RelationshipType
    description: str
    confidence: Confidence
    evidence: list[Evidence] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)

class ImageBuildProfile(_Model):
    build_tool: str | None = None
    build_command: str | None = None
    build_context: str | None = None
    dockerfile: str | None = None
    build_args: list[str] = Field(default_factory=list)
    build_artifact: str | None = None
    packaging: str | None = None
    image: str | None = None
    base_image: str | None = None
    builder_image: str | None = None
    image_source: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

class ExposureCandidate(_Model):
    port: int
    source: str
    confidence: Confidence
    service_candidate: bool
    description: str
    evidence: list[Evidence] = Field(default_factory=list)

class ProbeCandidateProfile(_Model):
    probe_type: str
    value: str
    confidence: Confidence
    evidence: list[Evidence] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)

class KubernetesObjectCandidate(_Model):
    kind: KubernetesObjectKind
    name: str | None = None
    candidate_role: Literal["workload_controller", "companion_object"]
    confidence: Confidence
    rationale: str
    evidence: list[Evidence] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)

class RuntimeDeploymentProfile(_Model):
    runtime: str | None = None
    language: str | None = None
    frameworks: list[str] = Field(default_factory=list)
    application_server: str | None = None
    command: list[str] | None = None
    workers: int | None = None
    container_ports: list[int] = Field(default_factory=list)
    published_ports: list[str] = Field(default_factory=list)
    context_path: str | None = None
    environment: list[str] = Field(default_factory=list)
    configmap_candidates: list[str] = Field(default_factory=list)
    secret_candidates: list[str] = Field(default_factory=list)
    volumes: list[str] = Field(default_factory=list)
    probe_candidates: list[ProbeCandidateProfile] = Field(default_factory=list)
    kubernetes_candidates: list[KubernetesObjectCandidate] = Field(default_factory=list)
    relationships: list[WorkloadRelationship] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

class WorkloadProfile(_Model):
    name: str
    role: str | None = None
    source_files: list[str] = Field(default_factory=list)
    image_build_profile: ImageBuildProfile
    runtime_deployment_profile: RuntimeDeploymentProfile
```

Then add this field to `AnalysisResult` after `components`:

```python
workload_profiles: list[WorkloadProfile] = Field(default_factory=list)
```

## File Structure

- Modify `src/repo_analyzer/models.py`: define the new Pydantic models and `AnalysisResult.workload_profiles`.
- Modify `src/repo_analyzer/rules/kubernetes_p0.py`: add `_emit_workload_profiles(result)` and call it from `_finalize_result()` before migration questions are generated.
- Modify `src/repo_analyzer/reporters/markdown_reporter.py`: render a profile-first workload section when `workload_profiles` exists, while keeping legacy output details as needed.
- Modify `src/repo_analyzer/reporters/brief_reporter.py`: prefer `workload_profiles` for build/run, ports/services, relationships, and open decisions.
- Modify `scripts/llm_tool_call_demo.py`: include `workload_profiles` in deterministic brief material and reduce prompt burden where schema now carries explicit structure.
- Modify tests under `tests/`: add schema-focused tests first, then reporter/LLM prompt tests.

## Task 1: Add Workload Profile Models

**Files:**
- Modify: `src/repo_analyzer/models.py`
- Test: `tests/test_workload_profiles_schema.py`

**Interfaces:**
- Produces: `AnalysisResult.workload_profiles: list[WorkloadProfile]`
- Produces: model types named `ImageBuildProfile`, `RuntimeDeploymentProfile`, `WorkloadRelationship`, `ExposureCandidate`, `ProbeCandidateProfile`, and `KubernetesObjectCandidate`

- [ ] **Step 1: Write the failing schema test**

```python
from repo_analyzer.models import (
    AnalysisResult,
    ImageBuildProfile,
    KubernetesObjectCandidate,
    RepositoryMetadata,
    RuntimeDeploymentProfile,
    WorkloadProfile,
)


def test_analysis_result_accepts_explicit_workload_profiles():
    result = AnalysisResult(
        repository=RepositoryMetadata(name="repo", profile="kubernetes-p0", file_count=1),
        workload_profiles=[
            WorkloadProfile(
                name="backend",
                source_files=["compose.yml", "backend/Dockerfile"],
                image_build_profile=ImageBuildProfile(
                    build_context="./backend",
                    dockerfile="backend/Dockerfile",
                    build_tool="Dockerfile",
                    image_source="local_build",
                ),
                runtime_deployment_profile=RuntimeDeploymentProfile(
                    runtime="FastAPI",
                    language="Python",
                    container_ports=[8000],
                    kubernetes_candidates=[
                        KubernetesObjectCandidate(
                            kind="Deployment",
                            candidate_role="workload_controller",
                            confidence="derived",
                            rationale="stateless HTTP application",
                        ),
                        KubernetesObjectCandidate(
                            kind="Service",
                            candidate_role="companion_object",
                            confidence="derived",
                            rationale="inbound container port evidence",
                        ),
                    ],
                ),
            )
        ],
    )

    dumped = result.model_dump()
    assert dumped["workload_profiles"][0]["image_build_profile"]["dockerfile"] == "backend/Dockerfile"
    assert dumped["workload_profiles"][0]["runtime_deployment_profile"]["kubernetes_candidates"][0]["kind"] == "Deployment"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles_schema.py`

Expected: FAIL because `ImageBuildProfile` or `workload_profiles` is not defined.

- [ ] **Step 3: Add the model definitions**

Add the model classes from the Target Schema Shape section to `src/repo_analyzer/models.py`.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles_schema.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/repo_analyzer/models.py tests/test_workload_profiles_schema.py
git commit -m "feat: add workload profile schema"
```

## Task 2: Assemble Profiles From Existing Component Facts

**Files:**
- Modify: `src/repo_analyzer/rules/kubernetes_p0.py`
- Test: `tests/test_workload_profiles.py`

**Interfaces:**
- Consumes: `AnalysisResult.components`, `AnalysisResult.workload_mappings`, `AnalysisResult.networking`, `AnalysisResult.configuration`, `AnalysisResult.secrets`, `AnalysisResult.storage`, `AnalysisResult.health_checks`, `AnalysisResult.container_image`
- Produces: `_emit_workload_profiles(result: AnalysisResult) -> None`

- [ ] **Step 1: Write the failing integration test**

```python
from repo_analyzer.analyzer import analyze_repository


def _profile(result, name):
    return next(profile for profile in result.workload_profiles if profile.name == name)


def test_full_stack_fastapi_profiles_group_build_and_runtime(golden_repo):
    result = analyze_repository(str(golden_repo), git_ref="4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8")

    assert [profile.name for profile in result.workload_profiles] == [
        "db",
        "adminer",
        "prestart",
        "backend",
        "frontend",
    ]

    backend = _profile(result, "backend")
    assert backend.image_build_profile.build_context == "./backend"
    assert backend.image_build_profile.dockerfile == "backend/Dockerfile"
    assert backend.runtime_deployment_profile.runtime == "FastAPI"
    assert backend.runtime_deployment_profile.command[:2] == ["fastapi", "run"]
    assert backend.runtime_deployment_profile.container_ports == [8000]
    assert any(c.kind == "Deployment" and c.candidate_role == "workload_controller" for c in backend.runtime_deployment_profile.kubernetes_candidates)
    assert any(c.kind == "Service" and c.candidate_role == "companion_object" for c in backend.runtime_deployment_profile.kubernetes_candidates)

    prestart = _profile(result, "prestart")
    assert any(c.kind == "Job" for c in prestart.runtime_deployment_profile.kubernetes_candidates)
    assert not any(c.kind == "Service" for c in prestart.runtime_deployment_profile.kubernetes_candidates)
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles.py::test_full_stack_fastapi_profiles_group_build_and_runtime`

Expected: FAIL because `workload_profiles` is empty.

- [ ] **Step 3: Implement `_emit_workload_profiles`**

Implementation rules:

```python
def _finalize_result(result: AnalysisResult) -> AnalysisResult:
    _emit_source_conflict_warnings(result)
    _emit_workload_profiles(result)
    _emit_migration_questions(result)
    return result
```

For each `Component`:

- Copy source files, image, build context, Dockerfile, build args, build tool, build command, artifact, packaging into `ImageBuildProfile`.
- Copy language, frameworks, application server, runtime, command, workers, ports, published ports, context path, environment, secrets, volumes, health check, and unresolved into `RuntimeDeploymentProfile`.
- Add `KubernetesObjectCandidate` entries by parsing `WorkloadMapping.kubernetes_kind` conservatively:
  - Contains `StatefulSet` -> workload controller candidate `StatefulSet`.
  - Starts with `Job` -> workload controller candidate `Job`.
  - Contains `Deployment` -> workload controller candidate `Deployment`.
  - Contains `Service` and does not contain `no Service` -> companion object candidate `Service`.
  - Persistent volume evidence for the component -> companion object candidate `PVC`.
  - Component environment entries that are not secret candidates -> companion object candidate `ConfigMap`.
  - Component secret candidates -> companion object candidate `Secret`.
- Do not emit Service candidates for jobs, init/prestart workloads, or no-inbound-port workers.
- Pull `image.base` from `result.container_image` into `base_image` only when there is exactly one profile or the evidence path matches the component Dockerfile.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles.py::test_full_stack_fastapi_profiles_group_build_and_runtime`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/repo_analyzer/rules/kubernetes_p0.py tests/test_workload_profiles.py
git commit -m "feat: assemble workload profiles"
```

## Task 3: Add Workload Relationships

**Files:**
- Modify: `src/repo_analyzer/rules/kubernetes_p0.py`
- Test: `tests/test_workload_profiles.py`

**Interfaces:**
- Consumes: `Component.depends_on`, `Component.runtime_dependencies`, `AnalysisResult.startup_order`, `AnalysisResult.build_time_constraints`
- Produces: `RuntimeDeploymentProfile.relationships: list[WorkloadRelationship]`

- [ ] **Step 1: Extend the failing test**

```python
def test_full_stack_fastapi_profiles_include_relationships(golden_repo):
    result = analyze_repository(str(golden_repo), git_ref="4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8")

    prestart = _profile(result, "prestart")
    prestart_relationships = {(rel.source, rel.target, rel.relationship_type) for rel in prestart.runtime_deployment_profile.relationships}
    assert ("prestart", "db", "startup_order") in prestart_relationships

    backend = _profile(result, "backend")
    relationships = {(rel.source, rel.target, rel.relationship_type) for rel in backend.runtime_deployment_profile.relationships}
    assert ("backend", "db", "startup_order") in relationships
    assert ("backend", "prestart", "startup_order") in relationships
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles.py::test_full_stack_fastapi_profiles_include_relationships`

Expected: FAIL because relationships are empty.

- [ ] **Step 3: Populate relationships conservatively**

Implementation rules:

- For every `Component.depends_on`, add `WorkloadRelationship(source=component.name, target=dependency, relationship_type="startup_order")`.
- If a dependency service exists in `result.components`, classify it as an internal workload relationship.
- If the target is not a detected component, keep the relationship but describe it as unresolved/external target evidence.
- For `result.build_time_constraints` subjects such as `frontend.vite_api_url_binding`, add a `build_time_binding` relationship only when the finding evidence or value names another detected component; otherwise record it as an open decision instead of inventing a target.
- For runtime dependency strings, avoid parsing arbitrary prose into targets unless the dependency name exactly matches a detected component name.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles.py::test_full_stack_fastapi_profiles_include_relationships`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/repo_analyzer/rules/kubernetes_p0.py tests/test_workload_profiles.py
git commit -m "feat: add workload relationships"
```

## Task 4: Make Reporters Profile-First

**Files:**
- Modify: `src/repo_analyzer/reporters/markdown_reporter.py`
- Modify: `src/repo_analyzer/reporters/brief_reporter.py`
- Test: `tests/test_markdown_reporter.py`
- Test: `tests/test_brief_reporter.py`

**Interfaces:**
- Consumes: `AnalysisResult.workload_profiles`
- Produces: Markdown sections that group build/runtime/relationships per workload

- [ ] **Step 1: Write failing reporter tests**

Test expectations:

```python
def test_markdown_reporter_uses_workload_profiles(result):
    markdown = to_markdown(result)
    assert "## 1. Workload profiles" in markdown
    assert "Image build profile" in markdown
    assert "Runtime deployment profile" in markdown
    assert "Workload relationships" in markdown
    assert "Deployment candidate" in markdown
    assert "Service candidate" in markdown
```

```python
def test_brief_reporter_groups_build_and_runtime_by_workload(result):
    brief = to_brief(result)
    assert "backend" in brief
    assert "Image build" in brief
    assert "Runtime deployment" in brief
    assert "backend -> db" in brief
```

- [ ] **Step 2: Run the focused reporter tests and verify they fail**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_markdown_reporter.py tests/test_brief_reporter.py`

Expected: FAIL because reporters still read the legacy shape first.

- [ ] **Step 3: Update `markdown_reporter.py`**

Implementation rules:

- Rename the first rendered section from component-flat output to profile-first output when `result.workload_profiles` is present.
- For each profile, render:
  - source files
  - image build profile
  - runtime deployment profile
  - Kubernetes workload controller candidates
  - companion object candidates
  - workload relationships
  - unresolved decisions
- Keep existing later sections for evidence-rich details until a later cleanup removes redundancy.

- [ ] **Step 4: Update `brief_reporter.py`**

Implementation rules:

- Keep the seven migration questions, but enrich answers from `workload_profiles`.
- For build/run, render workload-name-prefixed `Image build` and `Runtime deployment` summaries.
- For ports/services, distinguish `Deployment/StatefulSet/Job` workload controller candidates from `Service/PVC/ConfigMap/Secret/Ingress/Gateway` companion candidates.
- For relationships, render compact arrows from `WorkloadRelationship`.

- [ ] **Step 5: Run reporter tests and verify they pass**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_markdown_reporter.py tests/test_brief_reporter.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/repo_analyzer/reporters/markdown_reporter.py src/repo_analyzer/reporters/brief_reporter.py tests/test_markdown_reporter.py tests/test_brief_reporter.py
git commit -m "feat: render workload profiles"
```

## Task 5: Reduce LLM Prompt Reconstruction Burden

**Files:**
- Modify: `scripts/llm_tool_call_demo.py`
- Test: `tests/test_llm_tool_call_demo.py`

**Interfaces:**
- Consumes: `AnalysisResult.workload_profiles`
- Produces: final-answer instruction that tells the LLM to explain structured profiles rather than infer profiles from scattered sections

- [ ] **Step 1: Write a failing prompt test**

```python
def test_final_answer_instruction_prefers_workload_profiles():
    payload = {
        "ok": True,
        "analysis": {
            "schema_version": "1.0",
            "repository": {"name": "repo", "profile": "kubernetes-p0", "git_ref": None, "file_count": 1},
            "workload_profiles": [
                {
                    "name": "backend",
                    "source_files": ["compose.yml"],
                    "image_build_profile": {"dockerfile": "backend/Dockerfile"},
                    "runtime_deployment_profile": {
                        "runtime": "FastAPI",
                        "container_ports": [8000],
                        "kubernetes_candidates": [
                            {
                                "kind": "Deployment",
                                "candidate_role": "workload_controller",
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

    instruction = _build_final_answer_instruction(payload)

    assert "workload_profiles" in instruction
    assert "infer" not in instruction.lower()
    assert "structured workload profiles" in instruction
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py::test_final_answer_instruction_prefers_workload_profiles`

Expected: FAIL because the prompt still relies on the deterministic brief and scattered facts.

- [ ] **Step 3: Update the LLM instruction**

Implementation rules:

- Include a compact serialized `workload_profiles` section in the instruction.
- Tell the model that profile fields are already grouped and should be explained as structured workload profiles.
- Keep guardrails for candidates, scanned-facts-only negative claims, and unresolved operational values.
- Keep the existing deterministic brief as fallback context.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_llm_tool_call_demo.py::test_final_answer_instruction_prefers_workload_profiles`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/llm_tool_call_demo.py tests/test_llm_tool_call_demo.py
git commit -m "feat: make LLM prompt use workload profiles"
```

## Task 6: Golden Output and Backward Compatibility Verification

**Files:**
- Modify: existing golden-oriented tests as needed under `tests/`

**Interfaces:**
- Consumes: all previous tasks
- Produces: passing full test suite with existing JSON consumers still valid

- [ ] **Step 1: Add backward compatibility assertions**

Add assertions to existing golden tests:

```python
def test_legacy_component_fields_remain_populated(result):
    backend = next(component for component in result.components if component.name == "backend")
    assert backend.dockerfile == "backend/Dockerfile"
    assert backend.container_ports == [8000]
    assert backend.workload_candidate

    mapping = next(mapping for mapping in result.workload_mappings if mapping.component == "backend")
    assert "Deployment" in mapping.kubernetes_kind
```

- [ ] **Step 2: Run the full test suite**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q`

Expected: PASS.

- [ ] **Step 3: Run a dry-run transcript check**

Run: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run python scripts/llm_tool_call_demo.py --mode dry-run --repo tests/fixtures/full-stack-fastapi`

Expected: JSON transcript contains `tool_output.summary.ok=true`; analyzer output validation does not fail.

- [ ] **Step 4: Commit final compatibility updates**

```bash
git add tests
git commit -m "test: verify workload profile compatibility"
```

## Self-Review

- Spec coverage: The plan addresses explicit build/runtime/profile/relationship schema, profile assembly, reporter use, LLM use, and backward compatibility.
- Placeholder scan: No task uses incomplete-work markers or unspecified implementation steps.
- Type consistency: Later tasks consume the model names and fields introduced in Task 1.
- Scope check: This is one coherent additive schema change. It does not remove legacy fields or redesign parser internals.
