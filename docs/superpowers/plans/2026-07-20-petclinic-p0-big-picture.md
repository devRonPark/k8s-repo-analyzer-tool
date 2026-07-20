# PetClinic P0 Big Picture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Spring PetClinic golden JSON answer the seven Kubernetes migration overview questions without requiring developers to read source code.

**Architecture:** Keep the existing parser -> rule -> reporter flow. Repository facts must be extracted by Python parsers, then Spring Boot rules convert those facts into deterministic `Finding` and `Unresolved` entries. Do not add LLM behavior, manifest generation, operational defaults, or Spring PetClinic-specific conditionals.

**Tech Stack:** Python 3.12, Pydantic models, pytest, existing `repo_analyzer` parser/rule/reporter modules.

## Global Constraints

- Keep the existing Parser and Rule structure.
- Repository facts are extracted by Python parsers.
- Do not add LLM functionality.
- Do not add manifest generation.
- Do not infer operational values.
- Do not hardcode Spring PetClinic-specific strings in production code.
- Extend existing golden tests.
- Run only PetClinic-related targeted tests after implementation.
- Exclude operational security audit, session internals, cache consistency, and SQL race analysis.

---

## File Structure

- Create `src/repo_analyzer/parsers/readme.py`: parse README title, concise application description sentence, and fenced command blocks.
- Modify `src/repo_analyzer/analyzer.py`: replace raw README line lists with parsed README facts.
- Modify `src/repo_analyzer/rules/spring_boot.py`: consume README facts, emit improved application summary, ConfigMap grouping, service candidate summary, and per-profile migration input bundles.
- Modify `src/repo_analyzer/reporters/markdown_reporter.py`: make ConfigMap counts include profile selection and improve quick answers.
- Modify `tests/test_golden_spring_petclinic.py`: extend existing PetClinic golden assertions only.
- Regenerate `examples/spring-petclinic-analysis.json` and `examples/spring-petclinic-report.md`.

---

### Task 1: Parse README Big-Picture Facts

**Files:**
- Create: `src/repo_analyzer/parsers/readme.py`
- Modify: `src/repo_analyzer/analyzer.py`
- Test: `tests/test_golden_spring_petclinic.py`

**Interfaces:**
- Produces: `ReadmeFile(path: str, title: Located | None, application_description: Located | None, commands: list[Located])`
- Consumes: raw README text and path from `analyzer.py`

- [ ] **Step 1: Write the failing golden test**

Add to `tests/test_golden_spring_petclinic.py`:

```python
def test_readme_application_description_is_surfaced(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    summary = _config(result, "application.summary")
    assert summary is not None
    assert "Spring PetClinic Sample Application" in summary.value
    assert "Spring Boot" in summary.value
    assert "Maven" in summary.value and "Gradle" in summary.value
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_golden_spring_petclinic.py::test_readme_application_description_is_surfaced
```

Expected: FAIL because `application.summary` currently does not include the README title or README description sentence.

- [ ] **Step 3: Implement the README parser**

Create `src/repo_analyzer/parsers/readme.py`:

```python
"""README parser for high-level repository facts."""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import Located


@dataclass
class ReadmeFile:
    path: str
    title: Located | None = None
    application_description: Located | None = None
    commands: list[Located] = field(default_factory=list)


def parse_readme(text: str, path: str) -> ReadmeFile:
    parsed = ReadmeFile(path=path)
    in_fence = False
    for index, raw in enumerate(text.splitlines()):
        line_no = index + 1
        line = raw.strip()
        if line.startswith("# ") and parsed.title is None:
            title = line.removeprefix("# ").split("[", 1)[0].strip()
            if title:
                parsed.title = Located(title, "heading.h1", line_no, line_no)
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and line and not line.startswith("#"):
            parsed.commands.append(Located(line, "fenced-command", line_no, line_no))
        if parsed.application_description is None and " application " in f" {line.lower()} ":
            parsed.application_description = Located(line, "application-description", line_no, line_no)
    return parsed
```

Update `analyzer.py` imports and README parsing:

```python
from .parsers.readme import ReadmeFile, parse_readme

readmes: dict[str, ReadmeFile] = {
    rel: parse_readme(_read(root, rel), rel) for rel in inventory.readme_files
}
```

Update the `analyze_kubernetes_p0()` call type and downstream signatures as needed.

- [ ] **Step 4: Emit README-backed summary**

In `spring_boot.py`, update README type hints and summary construction so `application.summary` starts with the README title and description when present, then appends existing technology/table facts.

Expected PetClinic value shape:

```text
Spring PetClinic Sample Application - Spring Petclinic is a Spring Boot application built using Maven or Gradle. Runtime: Spring Boot web application backed by relational tables: owners, pets, specialties, types, vet_specialties, vets, visits
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_golden_spring_petclinic.py::test_readme_application_description_is_surfaced
```

Expected: PASS.

---

### Task 2: Surface Build/Run Alternatives Without Changing Build Selection

**Files:**
- Modify: `src/repo_analyzer/rules/spring_boot.py`
- Test: `tests/test_golden_spring_petclinic.py`

**Interfaces:**
- Consumes: `ReadmeFile.commands`
- Produces: configuration findings `run.command.gradle`, `run.command.maven`, `image.build_command.maven` when commands are explicitly present in README.

- [ ] **Step 1: Write the failing golden test**

```python
def test_readme_run_commands_are_available_without_switching_build_system(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    subjects = {f.subject: f for f in result.configuration}
    assert subjects["build.system"].value == "gradle"
    assert subjects["run.command.gradle"].value == "./gradlew bootRun"
    assert subjects["run.command.maven"].value == "./mvnw spring-boot:run"
    assert subjects["image.build_command.maven"].value == "./mvnw spring-boot:build-image"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_golden_spring_petclinic.py::test_readme_run_commands_are_available_without_switching_build_system
```

Expected: FAIL because README commands are not parsed into findings yet.

- [ ] **Step 3: Implement generic command emission**

Add helper in `spring_boot.py`:

```python
def _emit_readme_commands(result: AnalysisResult, readmes: dict[str, ReadmeFile]) -> None:
    wanted = {
        "./gradlew bootRun": "run.command.gradle",
        "./mvnw spring-boot:run": "run.command.maven",
        "./mvnw spring-boot:build-image": "image.build_command.maven",
    }
    for readme in readmes.values():
        for cmd in readme.commands:
            subject = wanted.get(str(cmd.value))
            if subject is None:
                continue
            result.configuration.append(
                Finding(
                    subject=subject,
                    value=cmd.value,
                    confidence="explicit",
                    kubernetes_effect="README-declared developer/build command; recorded as repository fact, not selected as the production build path",
                    evidence=[Evidence(path=readme.path, selector=cmd.selector, symbol="command", start_line=cmd.start_line, end_line=cmd.end_line)],
                )
            )
```

Call it from `analyze_spring_boot()` after `_emit_artifact_and_run()`.

- [ ] **Step 4: Run test to verify it passes**

Run the same test command. Expected: PASS.

---

### Task 3: Make ConfigMap/Secret Answer Profile-Aware

**Files:**
- Modify: `src/repo_analyzer/rules/spring_boot.py`
- Modify: `src/repo_analyzer/reporters/markdown_reporter.py`
- Test: `tests/test_golden_spring_petclinic.py`

**Interfaces:**
- Produces: `config.SPRING_PROFILES_ACTIVE` as a ConfigMap candidate.
- Produces: `profile.<name>.kubernetes_inputs` with ConfigMap keys and Secret keys.

- [ ] **Step 1: Write the failing golden test**

```python
def test_profile_kubernetes_inputs_group_configmap_and_secret_keys(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    pg = _config(result, "profile.postgres.kubernetes_inputs")
    assert pg.value == {
        "configmap_keys": ["SPRING_PROFILES_ACTIVE", "POSTGRES_URL"],
        "secret_keys": ["POSTGRES_USER", "POSTGRES_PASS"],
    }
    profile = _config(result, "config.SPRING_PROFILES_ACTIVE")
    assert "ConfigMap key candidate" in profile.kubernetes_effect
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_golden_spring_petclinic.py::test_profile_kubernetes_inputs_group_configmap_and_secret_keys
```

Expected: FAIL because profile input bundles are absent and `SPRING_PROFILES_ACTIVE` is not counted as a ConfigMap candidate.

- [ ] **Step 3: Implement profile input bundle**

In `_emit_profiles_and_datasources()`, change `config.SPRING_PROFILES_ACTIVE.kubernetes_effect` to include:

```text
ConfigMap key candidate. Set SPRING_PROFILES_ACTIVE=postgres or =mysql to switch to an external database; unset means the embedded H2 default.
```

After each `profile.<profile>.required_env` finding, append:

```python
result.configuration.append(
    Finding(
        subject=f"profile.{profile}.kubernetes_inputs",
        value={
            "configmap_keys": ["SPRING_PROFILES_ACTIVE"] + [name for name in required_env if name.endswith("_URL")],
            "secret_keys": [name for name in required_env if not name.endswith("_URL")],
        },
        confidence="derived",
        kubernetes_effect=f"complete env input set to run the '{profile}' profile in Kubernetes",
        evidence=[_prop_ev(e, props.path) for e in (url, user, pwd) if e is not None],
    )
)
```

- [ ] **Step 4: Update markdown quick answer count**

Because `config.SPRING_PROFILES_ACTIVE` now includes `ConfigMap key candidate`, the existing reporter count should become `3 ConfigMap keys`. If grouping should be shown, add a short `Profile input bundles` subsection under Configuration & Secrets.

- [ ] **Step 5: Run test to verify it passes**

Run the same test command. Expected: PASS.

---

### Task 4: Add Service Candidate Summary Without Guessing Exposure

**Files:**
- Modify: `src/repo_analyzer/rules/spring_boot.py`
- Test: `tests/test_golden_spring_petclinic.py`

**Interfaces:**
- Produces: `networking` finding `service.app`.
- Consumes: existing `component.container_ports`.

- [ ] **Step 1: Write the failing golden test**

```python
def test_app_service_candidate_separates_target_port_from_operational_exposure(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    service = _in_section(result, "networking", "service.app")
    assert service.value == {
        "kind": "Service",
        "target_port": 8080,
        "port": "unresolved",
        "type": "unresolved",
    }
    assert service.confidence == "derived"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_golden_spring_petclinic.py::test_app_service_candidate_separates_target_port_from_operational_exposure
```

Expected: FAIL because only `service.target_port` exists.

- [ ] **Step 3: Implement service candidate finding**

In `_emit_port()`, after `service.target_port`, append:

```python
result.networking.append(
    Finding(
        subject="service.app",
        value={"kind": "Service", "target_port": port, "port": "unresolved", "type": "unresolved"},
        confidence="derived",
        kubernetes_effect="Kubernetes Service is needed for the app; targetPort is repository-derived, while Service port/type are operational choices.",
        evidence=evidence,
    )
)
```

Use `_DEFAULT_HTTP_PORT` in the default branch and explicit `server.port` in the explicit branch.

- [ ] **Step 4: Run test to verify it passes**

Run the same test command. Expected: PASS.

---

### Task 5: Regenerate Golden Artifacts And Run PetClinic Targeted Tests

**Files:**
- Modify: `examples/spring-petclinic-analysis.json`
- Modify: `examples/spring-petclinic-report.md`

**Interfaces:**
- Consumes: analyzer output from the previous tasks.
- Produces: committed golden artifacts reflecting the new JSON/report facts.

- [ ] **Step 1: Regenerate artifacts**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run repo-analyzer analyze --repo tests/fixtures/spring-petclinic --build-system gradle --git-ref f182358d02e4a68e52bdbabf55ca7800288511e7 --json-output examples/spring-petclinic-analysis.json --markdown-output examples/spring-petclinic-report.md
```

Expected: command exits 0 and reports `spring-petclinic`.

- [ ] **Step 2: Run only PetClinic-related targeted tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_golden_spring_petclinic.py tests/test_petclinic_k8s_ground_truth.py
```

Expected: all tests in those two files pass.

- [ ] **Step 3: Inspect diff for scope**

Run:

```bash
git diff --stat
```

Expected: changes limited to README parser/analyzer/rules/reporter, PetClinic golden test, and PetClinic example outputs.

---

## Self-Review

- Spec coverage: The plan covers the remaining P0 gaps: README-backed app identity, run command alternatives, ConfigMap/Secret grouping, Service candidate summary, and regenerated golden artifacts.
- Placeholder scan: No TBD/TODO placeholders remain.
- Type consistency: `ReadmeFile`, `Located`, `Finding`, and `Unresolved` usage matches existing repo patterns.
- Scope check: The plan avoids LLMs, manifest generation, operational value guessing, PetClinic hardcoding in production code, and non-P0 audit topics.
