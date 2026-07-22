# OpenShell OpenCode Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable OpenCode sandbox that uses the validated OpenShell/SGLang foundation while keeping formal repository assessment available as an immutable, evidence-bounded Skill.

**Architecture:** A project image derived from the pinned OpenShell community base installs `repository-assessment`, a global OpenCode config, and a new product-path Skill. The host launcher creates or reconnects to a labeled writable workspace, while OpenShell keeps ordinary egress closed and routes the fixed client model alias through the gateway-selected Qwen model.

**Tech Stack:** NVIDIA OpenShell v0.0.52, OpenShell community base image, OpenCode, OpenCode `opencode.json`, OpenCode Agent Skills, Docker, Python 3.12 host launcher, pytest, SGLang Chat Completions.

## Global Constraints

- Complete `2026-07-22-openshell-assessment-runtime-implementation.md` first; this plan consumes its lock, launcher, runner, bootstrap state, and acceptance evidence.
- Before creating the Skill, invoke `skill-creator` and `superpowers:writing-skills` and follow their current instructions.
- Resolve the OpenShell community base image to an immutable `sha256:` digest and commit that digest in `openshell/runtime.lock` before building.
- Keep the OpenCode workspace writable but never treat OpenCode explanations or edits as evidence-checked assessment artifacts.
- Keep ordinary network egress empty; the only model path is `https://inference.local/v1`.
- Use the fixed OpenCode model alias `openshell/gateway-model`; OpenShell rewrites it to the gateway-selected Qwen model.
- Keep OpenCode config and the repository assessment Skill read-only under `/opt/repository-assessment`.
- Reconnect only when sandbox labels match both the canonical repository identity and runtime profile.
- Never auto-delete a reusable OpenCode sandbox; deletion requires `scripts/openshell/cleanup --name NAME`.
- Do not add Codex, Claude Code, private GitHub credentials, package-registry egress, or Policy Advisor.

---

## File Map

- `openshell/runtime.lock` — gains the immutable OpenCode base image and derived image name.
- `openshell/opencode/Dockerfile` — derived image with OpenCode, package, immutable config, and Skill.
- `openshell/opencode/opencode.json` — fixed custom OpenAI-compatible provider routed through `inference.local`.
- `openshell/opencode/policy.yaml` — writable workspace and state, immutable config/Skill, no ordinary egress.
- `skills/repository-assessment/SKILL.md` — new product assessment Skill; existing compatibility Skill remains unchanged.
- `scripts/openshell_runtime.py` — create/reconnect/delete OpenCode lifecycle.
- `scripts/openshell/opencode` — stable OpenCode entry point.
- `scripts/openshell/cleanup` — explicit sandbox deletion entry point.
- `tests/assessment/test_openshell_opencode.py` — image/config/Skill/policy and host lifecycle tests.
- `scripts/openshell/acceptance-opencode` — bounded non-interactive and reconnect acceptance.
- `docs/ASSESSMENT.md` — OpenCode usage and trust-boundary documentation.
- `docs/validation/2026-07-22-openshell-opencode-validation.md` — actual smoke evidence without model response bodies.

### Task 1: Immutable OpenCode Image, Config, Policy, and Product Skill

**Files:**
- Modify: `openshell/runtime.lock`
- Create: `openshell/opencode/Dockerfile`
- Create: `openshell/opencode/opencode.json`
- Create: `openshell/opencode/policy.yaml`
- Create: `skills/repository-assessment/SKILL.md`
- Create: `tests/assessment/test_openshell_opencode.py`

**Interfaces:**
- Consumes: assessment package source and the immutable community base image digest.
- Produces: `RuntimeLock.opencode_base_image: str`, `RuntimeLock.opencode_image: str`, image `repository-assessment-opencode:0.1.0`, provider alias `openshell/gateway-model`, and Skill name `repository-assessment`.

- [ ] **Step 1: Invoke the required Skill-authoring guidance**

Read and apply `skill-creator` and `superpowers:writing-skills` before writing `SKILL.md`. Preserve the plan's exact behavior boundary: the Skill invokes the product CLI and reports its artifacts; it does not analyze repository facts itself.

- [ ] **Step 2: Resolve and record the immutable base image**

Run: `docker buildx imagetools inspect ghcr.io/nvidia/openshell-community/sandboxes/base:latest --format '{{json .Manifest.Digest}}'`

Expected: one JSON string matching `"sha256:[0-9a-f]{64}"`. Add the returned full reference and `"opencode_image": "repository-assessment-opencode:0.1.0"` to `openshell/runtime.lock`. Reject an empty or non-digest result; do not fall back to `:latest` in the Dockerfile build.

- [ ] **Step 3: Write failing static contract tests**

```python
def test_opencode_config_routes_fixed_alias_through_inference_local() -> None:
    config = json.loads(Path("openshell/opencode/opencode.json").read_text())
    assert config["model"] == "openshell/gateway-model"
    provider = config["provider"]["openshell"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"] == {
        "baseURL": "https://inference.local/v1",
        "apiKey": "unused",
    }
    assert set(provider["models"]) == {"gateway-model"}
    assert config["permission"]["skill"] == {
        "*": "deny",
        "repository-assessment": "allow",
    }


def test_opencode_policy_separates_immutable_config_and_writable_state() -> None:
    policy = YAML(typ="safe").load(Path("openshell/opencode/policy.yaml").read_text())
    filesystem = policy["filesystem_policy"]
    assert "/opt/repository-assessment" in filesystem["read_only"]
    assert filesystem["read_write"] == [
        "/sandbox/workspace", "/sandbox/.local/share/opencode", "/tmp", "/dev/null"
    ]
    assert policy["network_policies"] == {}
    assert policy["landlock"]["compatibility"] == "hard_requirement"


def test_product_skill_does_not_reuse_compatibility_analyzer() -> None:
    skill = Path("skills/repository-assessment/SKILL.md").read_text()
    assert "repository-assessment assess" in skill
    assert "repo-analyzer analyze" not in skill
    assert "Do not infer repository facts" in skill
```

- [ ] **Step 4: Run tests and verify missing-file failures**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_opencode.py`

Expected: failures identify missing config, policy, image, and Skill.

- [ ] **Step 5: Implement config, policy, Skill, and image**

Extend the host lock type before loading the expanded JSON:

```python
@dataclass(frozen=True)
class RuntimeLock:
    openshell_version: str
    uv_version: str
    python_image: str
    assessment_image: str
    opencode_base_image: str
    opencode_image: str
```

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "openshell/gateway-model",
  "provider": {
    "openshell": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "OpenShell Gateway",
      "options": {
        "baseURL": "https://inference.local/v1",
        "apiKey": "unused"
      },
      "models": {
        "gateway-model": {
          "name": "Gateway-selected Qwen model"
        }
      }
    }
  },
  "permission": {
    "skill": {
      "*": "deny",
      "repository-assessment": "allow"
    }
  }
}
```

````markdown
---
name: repository-assessment
description: Run the evidence-checked repository assessment product for Kubernetes migration when the user asks to assess the current repository or produce the four formal migration assessment artifacts.
compatibility: opencode
---

# Repository Assessment

Use the installed `repository-assessment assess` CLI. Do not infer repository
facts yourself and do not substitute `repo-analyzer analyze`.

Run:

```bash
repository-assessment assess \
  --repo . \
  --output-dir ./output/repository-assessment \
  --base-url https://inference.local/v1 \
  --model gateway-model
```

Treat exit `0` as completed and exit `1` as completed with gaps. Read and explain
only `migration-inputs.yaml`, `migration-report.md`, `assessment-details.json`,
and `run-log.json`. Do not infer repository facts that are absent from those
artifacts. On exit `2` or `3`, report the failed stage and preserve the run log.
````

```yaml
version: 1
filesystem_policy:
  include_workdir: false
  read_only:
    - /usr
    - /bin
    - /lib
    - /lib64
    - /etc
    - /opt/repository-assessment
    - /proc
    - /dev/urandom
  read_write:
    - /sandbox/workspace
    - /sandbox/.local/share/opencode
    - /tmp
    - /dev/null
landlock:
  compatibility: hard_requirement
process:
  run_as_user: sandbox
  run_as_group: sandbox
network_policies: {}
```

```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.26 AS uv
ARG OPENCODE_BASE_IMAGE
FROM ${OPENCODE_BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    XDG_CONFIG_HOME=/opt/repository-assessment/opencode \
    XDG_DATA_HOME=/sandbox/.local/share
USER root
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && mkdir -p /opt/repository-assessment/opencode/skills/repository-assessment \
                /sandbox/workspace /sandbox/.local/share/opencode /lib64 \
    && chmod 1777 /sandbox/workspace /sandbox/.local/share/opencode /tmp \
    && opencode --version >/dev/null \
    && repository-assessment --help >/dev/null
COPY openshell/opencode/opencode.json /opt/repository-assessment/opencode/opencode.json
COPY skills/repository-assessment/SKILL.md /opt/repository-assessment/opencode/skills/repository-assessment/SKILL.md
CMD ["opencode"]
```

The static test must assert `pip install` is absent and `uv sync --frozen --no-dev --no-editable` is present.

- [ ] **Step 6: Run static tests and build from the digest**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_opencode.py tests/assessment/test_documentation_contract.py`

Expected: all tests pass and the existing compatibility Skill test remains unchanged.

Run with the exact locked reference: `docker build -f openshell/opencode/Dockerfile --build-arg OPENCODE_BASE_IMAGE="$(python3 -c 'import json; print(json.load(open("openshell/runtime.lock"))["opencode_base_image"])')" -t repository-assessment-opencode:0.1.0 .`

Expected: image builds, `opencode --version` succeeds, `repository-assessment --help` succeeds, and no runtime package download is required.

- [ ] **Step 7: Commit the OpenCode runtime content**

```bash
git add openshell/runtime.lock openshell/opencode skills/repository-assessment/SKILL.md tests/assessment/test_openshell_opencode.py
git commit -m "feat(openshell): add OpenCode sandbox image"
```

### Task 2: Reusable OpenCode Lifecycle and Explicit Cleanup

**Files:**
- Modify: `scripts/openshell_runtime.py`
- Create: `scripts/openshell/opencode`
- Create: `scripts/openshell/cleanup`
- Modify: `tests/assessment/test_openshell_opencode.py`

**Interfaces:**
- Consumes: `RuntimeLock`, `RuntimeState`, `CommandRunner`, local repository path, and sandbox name.
- Produces: `launch_opencode(project_root, repository, name, prompt, runner) -> int` and `delete_sandbox(name, runner) -> None`.

- [ ] **Step 1: Write failing create/reconnect/cleanup tests**

```python
def test_opencode_creates_labeled_workspace_then_executes(tmp_path: Path) -> None:
    runner = FakeRunner(sandbox_exists=False)
    exit_code = launch_opencode(
        project_root=PROJECT_ROOT,
        repository=PROJECT_ROOT / "tests/fixtures/assessment/node-basic",
        name="repository-opencode",
        prompt="List the available skills and stop.",
        runner=runner,
    )
    assert exit_code == 0
    create = next(command for command in runner.commands if command[:3] == ("openshell", "sandbox", "create"))
    assert "profile=repository-opencode-v1" in create
    assert any(value.startswith("repository=") for value in create)
    assert "--no-git-ignore" in create
    assert runner.commands[-1][:3] == ("openshell", "sandbox", "exec")


def test_opencode_reconnect_rejects_repository_label_mismatch() -> None:
    runner = FakeRunner(sandbox_exists=True, sandbox_labels={
        "profile": "repository-opencode-v1", "repository": "different"
    })
    with pytest.raises(ValueError, match="different repository"):
        launch_fixture_opencode(runner)


def test_cleanup_deletes_only_exact_validated_name() -> None:
    runner = FakeRunner(sandbox_exists=True)
    delete_sandbox("repository-opencode", runner)
    assert runner.commands == [("openshell", "sandbox", "delete", "repository-opencode")]
```

- [ ] **Step 2: Run tests and verify missing lifecycle functions**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_opencode.py -k 'create or reconnect or cleanup'`

Expected: failures report missing `launch_opencode` and `delete_sandbox`.

- [ ] **Step 3: Implement canonical labels and create/reconnect behavior**

Compute repository identity as SHA-256 over the canonical local path plus resolved Git commit, never over repository content. Query `openshell sandbox list -o json`. When absent, build the locked image and create:

Extend `FakeRunner` with `sandbox_exists: bool = False` and
`sandbox_labels: dict[str, str] | None = None`. For
`openshell sandbox list -o json`, return a JSON array containing the requested
name and labels only when `sandbox_exists` is true; this is the single fake
contract used by the create and reconnect tests.

```python
runner.run([
    "openshell", "sandbox", "create", "--name", name,
    "--from", lock.opencode_image,
    "--policy", str(project_root / "openshell/opencode/policy.yaml"),
    "--label", "profile=repository-opencode-v1",
    "--label", f"repository={repository_identity}",
    "--no-git-ignore", "--upload", f"{staged_repository}:/sandbox/workspace",
    "--", "/bin/true",
])
```

Account for upload basename semantics so OpenCode's working directory is exactly `/sandbox/workspace/repository`, then execute with `--workdir /sandbox/workspace/repository`. With a prompt, run `opencode run PROMPT`; without it, run interactive `opencode` with TTY inherited from `openshell sandbox exec`. When the sandbox exists, require exact profile and repository labels before exec. Validate sandbox names with `^[a-z0-9][a-z0-9-]{0,62}$` before any CLI call.

- [ ] **Step 4: Add stable shell entry points**

```bash
#!/usr/bin/env bash
source "$(dirname -- "$0")/common"
exec python3 "$PROJECT_ROOT/scripts/openshell_runtime.py" opencode "$@"
```

```bash
#!/usr/bin/env bash
source "$(dirname -- "$0")/common"
exec python3 "$PROJECT_ROOT/scripts/openshell_runtime.py" cleanup "$@"
```

Add argparse forms `opencode --repo PATH --name NAME [--prompt TEXT]` and `cleanup --name NAME`. Make both executable.

- [ ] **Step 5: Run lifecycle tests and commit**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_opencode.py tests/assessment/test_openshell_host.py`

Expected: all tests pass, including name injection, missing runtime state, label mismatch, path spaces, reconnect without upload, and exact cleanup target.

```bash
git add scripts/openshell_runtime.py scripts/openshell/opencode scripts/openshell/cleanup tests/assessment/test_openshell_opencode.py
git commit -m "feat(openshell): manage reusable OpenCode sandbox"
```

### Task 3: OpenCode Acceptance, Documentation, and Final Verification

**Files:**
- Create: `scripts/openshell/acceptance-opencode`
- Modify: `docs/ASSESSMENT.md`
- Modify: `tests/assessment/test_documentation_contract.py`
- Create: `docs/validation/2026-07-22-openshell-opencode-validation.md`

**Interfaces:**
- Consumes: completed assessment runtime, active inference route, OpenCode image and lifecycle commands.
- Produces: bounded skill/model/reconnect smoke evidence and user runbook.

- [ ] **Step 1: Write failing documentation assertions**

```python
def test_assessment_docs_explain_opencode_trust_boundary() -> None:
    text = Path("docs/ASSESSMENT.md").read_text()
    assert "scripts/openshell/opencode" in text
    assert "scripts/openshell/cleanup" in text
    assert "repository-opencode-v1" in text
    assert "OpenCode 결과는 evidence-checked 산출물을 대체하지 않습니다" in text
```

- [ ] **Step 2: Add a bounded acceptance driver**

```bash
#!/usr/bin/env bash
source "$(dirname -- "$0")/common"
NAME="repository-opencode-acceptance"
"$PROJECT_ROOT/scripts/openshell/opencode" \
  --repo "$PROJECT_ROOT/tests/fixtures/assessment/node-basic" \
  --name "$NAME" \
  --prompt "Load the repository-assessment skill, list its four permitted artifact names, and stop without changing files."
"$PROJECT_ROOT/scripts/openshell/opencode" \
  --repo "$PROJECT_ROOT/tests/fixtures/assessment/node-basic" \
  --name "$NAME" \
  --prompt "Print only the current working directory and stop."
"$PROJECT_ROOT/scripts/openshell/cleanup" --name "$NAME"
```

- [ ] **Step 3: Update documentation and run focused tests**

Document create, reconnect, non-interactive prompt, interactive use, explicit cleanup, writable workspace, immutable config/Skill, denied ordinary egress, and the formal assessment trust boundary.

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_opencode.py tests/assessment/test_documentation_contract.py`

Expected: all tests pass.

- [ ] **Step 4: Run live OpenCode acceptance and record evidence**

Run: `scripts/openshell/acceptance-opencode`

Expected: first prompt loads the `repository-assessment` Skill through `inference.local`, second invocation reconnects to the same labeled sandbox, no workspace file changes, and cleanup deletes the exact sandbox.

Record OpenShell/OpenCode/image versions, commands, exit statuses, matching sandbox ID across reconnect, denied-egress observation, and cleanup result in `docs/validation/2026-07-22-openshell-opencode-validation.md`. Do not record model response bodies or credentials.

- [ ] **Step 5: Run full verification and commit**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q`

Expected: all tests pass. Confirm `git status --short` contains no runtime state, downloaded artifacts, or unplanned generated files.

```bash
git add scripts/openshell/acceptance-opencode docs/ASSESSMENT.md tests/assessment/test_documentation_contract.py docs/validation/2026-07-22-openshell-opencode-validation.md
git commit -m "docs(openshell): verify OpenCode runtime"
```
