# OpenShell Assessment Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `repository-assessment` end to end inside a fresh, read-only NVIDIA OpenShell sandbox backed by the existing host SGLang/Qwen server.

**Architecture:** A small standard-library Python host launcher owns safe argument handling and official `openshell` CLI invocation; executable shell files are stable user-facing entry points only. A pinned custom image contains the assessment package, OpenShell applies the static policy, and the launcher stages input, creates the sandbox, runs preflight and assessment, downloads four artifacts, then cleans up.

**Tech Stack:** Python 3.12, Bash, Docker 28+, NVIDIA OpenShell v0.0.52, OpenShell policy schema v1, SGLang OpenAI-compatible Chat Completions, pytest, ruamel.yaml, uv 0.11.26.

## Global Constraints

- Validate against OpenShell `v0.0.52`; upgrades require an explicit lock-file and acceptance-test change.
- Use only a local Docker-backed gateway; Kubernetes, Podman, and MicroVM drivers are out of scope.
- SGLang stays on the host and must be reachable by the gateway through `host.openshell.internal` or an explicitly reachable LAN URL.
- Sandbox model calls use `https://inference.local/v1`; no direct SGLang or public model endpoint is allowed in sandbox network policy.
- Assessment repositories are read-only; only `/sandbox/output`, `/tmp`, and `/dev/null` are writable.
- Accept local repositories and public credential-free `https://github.com/OWNER/REPOSITORY` URLs only.
- Preserve exactly `migration-inputs.yaml`, `migration-report.md`, `assessment-details.json`, and `run-log.json` as assessment artifacts.
- Do not change assessment evidence, topic, output, or status semantics.
- Do not commit provider credentials, `.openshell-runtime/`, downloaded artifacts, or live model responses.
- Preserve unrelated dirty-worktree changes and stage only files named by each task.

---

## File Map

- `scripts/openshell_runtime.py` — typed host orchestration, input validation, subprocess arrays, staging, artifact publication, and cleanup.
- `scripts/openshell/common` — shell wrapper shared preamble that finds the repository root and executes the host launcher.
- `scripts/openshell/bootstrap` — stable bootstrap command.
- `scripts/openshell/assess` — stable assessment command.
- `openshell/runtime.lock` — committed OpenShell, uv, Python image, and assessment-image identifiers.
- `openshell/assessment/Dockerfile` — locked assessment runtime image.
- `.dockerignore` — excludes secrets, VCS state, caches, outputs, docs, and fixtures from the image context.
- `openshell/policy.yaml` — strict assessment policy.
- `tests/assessment/openshell_fakes.py` — reusable fake command runner for host-launcher tests.
- `tests/assessment/test_openshell_host.py` — host validation, bootstrap, lifecycle, and publication tests.
- `tests/assessment/test_openshell_runtime_contract.py` — policy, lock, image, and documentation contract tests.
- `scripts/openshell/acceptance-assessment` — offline/live OpenShell acceptance driver.
- `docs/ASSESSMENT.md` — supported setup and runbook.
- `docs/validation/2026-07-22-openshell-runtime-validation.md` — actual local runtime evidence; no model response bodies or credentials.

### Task 1: Host Launcher Boundary and Input Contracts

**Files:**
- Create: `scripts/openshell_runtime.py`
- Create: `scripts/openshell/common`
- Create: `scripts/openshell/bootstrap`
- Create: `scripts/openshell/assess`
- Create: `tests/assessment/openshell_fakes.py`
- Create: `tests/assessment/test_openshell_host.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `RuntimeLock`, `RuntimeState`, `CommandRunner.run(args, *, check, env, capture_output)`, `validate_github_url(url)`, `gateway_url(host_url)`, `load_runtime_lock(path)`, `load_runtime_state(path)`, `main(argv)`.
- Consumes: only Python standard library and repository-relative files.

- [ ] **Step 1: Write failing validation and wrapper tests**

```python
# tests/assessment/test_openshell_host.py
from pathlib import Path

import pytest

from scripts.openshell_runtime import gateway_url, validate_github_url


def test_gateway_url_rewrites_only_loopback_host() -> None:
    assert gateway_url("http://127.0.0.1:30000/v1") == (
        "http://host.openshell.internal:30000/v1"
    )
    assert gateway_url("http://10.0.0.8:30000/v1") == "http://10.0.0.8:30000/v1"


@pytest.mark.parametrize(
    "url",
    [
        "ssh://github.com/acme/app",
        "https://gitlab.com/acme/app",
        "https://token@github.com/acme/app",
        "https://github.com/acme",
    ],
)
def test_github_url_rejects_unsupported_or_credentialed_sources(url: str) -> None:
    with pytest.raises(ValueError):
        validate_github_url(url)


def test_shell_entry_points_delegate_without_evaluating_arguments() -> None:
    for name in ("bootstrap", "assess"):
        text = Path(f"scripts/openshell/{name}").read_text()
        assert 'exec python3 "$PROJECT_ROOT/scripts/openshell_runtime.py"' in text
        assert '"$@"' in text
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_host.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.openshell_runtime'`.

- [ ] **Step 3: Implement the typed boundary and wrappers**

```python
# scripts/openshell_runtime.py
from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence
from urllib.parse import urlsplit, urlunsplit

ARTIFACT_NAMES = (
    "migration-inputs.yaml",
    "migration-report.md",
    "assessment-details.json",
    "run-log.json",
)


@dataclass(frozen=True)
class RuntimeLock:
    openshell_version: str
    uv_version: str
    python_image: str
    assessment_image: str


@dataclass(frozen=True)
class RuntimeState:
    model: str
    provider: str
    host_url: str
    gateway_url: str


class CommandRunner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
        env: Mapping[str, str] | None = None,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(self, args, *, check=True, env=None, capture_output=False):
        return subprocess.run(
            list(args),
            check=check,
            env=None if env is None else dict(env),
            capture_output=capture_output,
            text=True,
        )


def gateway_url(host_url: str) -> str:
    parsed = urlsplit(host_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("SGLang URL must be an absolute HTTP(S) URL")
    hostname = "host.openshell.internal" if parsed.hostname in {"127.0.0.1", "localhost"} else parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path.rstrip("/"), "", ""))


def validate_github_url(url: str) -> str:
    parsed = urlsplit(url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("only public https://github.com URLs are supported")
    if parsed.username or parsed.password or len(parts) != 2 or parsed.query or parsed.fragment:
        raise ValueError("GitHub URL must identify one credential-free repository")
    repository = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    return f"https://github.com/{parts[0]}/{repository}.git"


def load_runtime_lock(path: Path) -> RuntimeLock:
    return RuntimeLock(**json.loads(path.read_text(encoding="utf-8")))


def load_runtime_state(path: Path) -> RuntimeState:
    return RuntimeState(**json.loads(path.read_text(encoding="utf-8")))
```

```python
# tests/assessment/openshell_fakes.py
from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.openshell_runtime import ARTIFACT_NAMES


class FakeRunner:
    def __init__(
        self,
        *,
        assessment_exit: int = 0,
        download_exit: int = 0,
        create_downloaded_artifacts: bool = False,
        provider_exists: bool = False,
    ) -> None:
        self.assessment_exit = assessment_exit
        self.download_exit = download_exit
        self.create_downloaded_artifacts = create_downloaded_artifacts
        self.provider_exists = provider_exists
        self.commands: list[tuple[str, ...]] = []

    def run(self, args, *, check=True, env=None, capture_output=False):
        command = tuple(str(value) for value in args)
        self.commands.append(command)
        returncode = 0
        if command[:3] == ("openshell", "provider", "get") and not self.provider_exists:
            returncode = 1
        if command[:3] == ("openshell", "sandbox", "download"):
            returncode = self.download_exit
            if returncode == 0 and self.create_downloaded_artifacts:
                output = Path(command[-1]) / "output"
                output.mkdir(parents=True, exist_ok=True)
                for name in ARTIFACT_NAMES:
                    (output / name).write_text(f"artifact: {name}\n", encoding="utf-8")
        if "repository-assessment" in command:
            returncode = self.assessment_exit
        result = subprocess.CompletedProcess(command, returncode, stdout="", stderr="")
        if check and returncode:
            raise subprocess.CalledProcessError(returncode, command)
        return result
```

```bash
# scripts/openshell/common
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
export PROJECT_ROOT
```

```bash
# scripts/openshell/bootstrap
#!/usr/bin/env bash
source "$(dirname -- "$0")/common"
exec python3 "$PROJECT_ROOT/scripts/openshell_runtime.py" bootstrap "$@"
```

```bash
# scripts/openshell/assess
#!/usr/bin/env bash
source "$(dirname -- "$0")/common"
exec python3 "$PROJECT_ROOT/scripts/openshell_runtime.py" assess "$@"
```

Append `/.openshell-runtime/` to `.gitignore`, implement argparse subcommands that call functions added in Tasks 3 and 4, and make the three shell files executable.

- [ ] **Step 4: Run focused tests**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_host.py`

Expected: all tests pass.

- [ ] **Step 5: Commit the host boundary**

```bash
git add .gitignore scripts/openshell_runtime.py scripts/openshell tests/assessment/openshell_fakes.py tests/assessment/test_openshell_host.py
git commit -m "feat(openshell): add host runtime boundary"
```

### Task 2: Locked Assessment Image and Static Policy

**Files:**
- Create: `openshell/runtime.lock`
- Create: `openshell/assessment/Dockerfile`
- Create: `.dockerignore`
- Modify: `openshell/policy.yaml`
- Create: `tests/assessment/test_openshell_runtime_contract.py`
- Modify: `tests/assessment/test_openshell_adapter.py`

**Interfaces:**
- Consumes: `load_runtime_lock()` and the package entry point `repository-assessment`.
- Produces: image `repository-assessment-openshell:0.1.0` and schema-v1 policy at `openshell/policy.yaml`.

- [ ] **Step 1: Write failing policy, image, and lock tests**

```python
def test_assessment_policy_has_exact_static_boundary() -> None:
    policy = YAML(typ="safe").load(Path("openshell/policy.yaml").read_text())
    filesystem = policy["filesystem_policy"]
    assert filesystem["read_only"] == [
        "/usr", "/bin", "/lib", "/lib64", "/etc", "/app",
        "/sandbox/repository", "/proc", "/dev/urandom",
    ]
    assert filesystem["read_write"] == ["/sandbox/output", "/tmp", "/dev/null"]
    assert filesystem["include_workdir"] is False
    assert policy["landlock"] == {"compatibility": "hard_requirement"}
    assert policy["process"] == {"run_as_user": "sandbox", "run_as_group": "sandbox"}
    assert policy["network_policies"] == {}


def test_assessment_image_uses_frozen_uv_environment() -> None:
    dockerfile = Path("openshell/assessment/Dockerfile").read_text()
    assert "ghcr.io/astral-sh/uv:0.11.26" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "pip install" not in dockerfile
    assert "repository-assessment" in dockerfile
```

- [ ] **Step 2: Verify the contract tests fail**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_runtime_contract.py tests/assessment/test_openshell_adapter.py`

Expected: failures report missing Dockerfile/lock and incomplete filesystem lists.

- [ ] **Step 3: Implement the exact lock, Dockerfile, ignore file, and policy**

```json
{
  "openshell_version": "v0.0.52",
  "uv_version": "0.11.26",
  "python_image": "python:3.12.11-slim-bookworm",
  "assessment_image": "repository-assessment-openshell:0.1.0"
}
```

```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.26 AS uv
FROM python:3.12.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && mkdir -p /sandbox/repository /sandbox/output /tmp /lib64 \
    && chmod 1777 /sandbox/output /tmp \
    && repository-assessment --help >/dev/null
CMD ["repository-assessment", "--help"]
```

```text
.git
.venv
.env
.openshell-runtime
output
__pycache__
.pytest_cache
docs
examples
tests
```

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
    - /app
    - /sandbox/repository
    - /proc
    - /dev/urandom
  read_write:
    - /sandbox/output
    - /tmp
    - /dev/null
landlock:
  compatibility: hard_requirement
process:
  run_as_user: sandbox
  run_as_group: sandbox
network_policies: {}
```

- [ ] **Step 4: Run static tests and build the image**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_runtime_contract.py tests/assessment/test_openshell_adapter.py`

Expected: all tests pass.

Run: `docker build -f openshell/assessment/Dockerfile -t repository-assessment-openshell:0.1.0 .`

Expected: build succeeds and the final `repository-assessment --help` check exits zero.

- [ ] **Step 5: Commit the runtime image and policy**

```bash
git add .dockerignore openshell/runtime.lock openshell/assessment/Dockerfile openshell/policy.yaml tests/assessment/test_openshell_runtime_contract.py tests/assessment/test_openshell_adapter.py
git commit -m "feat(openshell): add assessment sandbox image"
```

### Task 3: Idempotent SGLang Bootstrap and Inference Verification

**Files:**
- Modify: `scripts/openshell_runtime.py`
- Modify: `tests/assessment/openshell_fakes.py`
- Modify: `tests/assessment/test_openshell_host.py`

**Interfaces:**
- Consumes: `RuntimeLock`, `gateway_url()`, environment variable named by `--api-key-env`.
- Produces: `.openshell-runtime/config.json` containing `RuntimeState`; provider name `repository-sglang-` plus the first 12 hex characters of SHA-256 over the gateway URL and key-variable name.

- [ ] **Step 1: Write failing bootstrap command-sequence tests**

```python
def test_bootstrap_configures_hashed_provider_and_inference(tmp_path: Path) -> None:
    runner = FakeRunner()
    state = bootstrap_runtime(
        project_root=tmp_path,
        host_url="http://127.0.0.1:30000/v1",
        model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
        api_key_env=None,
        install=False,
        runner=runner,
        probe=lambda url: {"data": [{"id": "Qwen/Qwen3-Coder-30B-A3B-Instruct"}]},
    )
    assert state.gateway_url == "http://host.openshell.internal:30000/v1"
    assert any(command[:3] == ("openshell", "provider", "create") for command in runner.commands)
    assert ("openshell", "inference", "set", "--provider", state.provider,
            "--model", state.model, "--timeout", "300") in runner.commands
    saved = json.loads((tmp_path / ".openshell-runtime/config.json").read_text())
    assert "api_key" not in json.dumps(saved).lower()
```

- [ ] **Step 2: Run the test and verify `bootstrap_runtime` is missing**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_host.py -k bootstrap`

Expected: failure reports that `bootstrap_runtime` is not defined.

- [ ] **Step 3: Implement bootstrap without secret-bearing process arguments**

Implement `bootstrap_runtime(...) -> RuntimeState` to:

```python
provider_seed = f"{gateway_endpoint}\0{api_key_env or 'unused'}".encode()
provider = "repository-sglang-" + hashlib.sha256(provider_seed).hexdigest()[:12]
provider_exists = runner.run(
    ["openshell", "provider", "get", provider], check=False, capture_output=True
).returncode == 0
if not provider_exists:
    credential = "OPENAI_API_KEY" if api_key_env else "OPENAI_API_KEY=unused"
    child_env = dict(os.environ)
    if api_key_env:
        child_env["OPENAI_API_KEY"] = os.environ[api_key_env]
    runner.run(
        ["openshell", "provider", "create", "--name", provider, "--type", "openai",
         "--credential", credential, "--config", f"OPENAI_BASE_URL={gateway_endpoint}"],
        env=child_env,
    )
runner.run([
    "openshell", "inference", "set", "--provider", provider,
    "--model", model, "--timeout", "300",
])
```

Before configuration, enforce Docker major version at least 28, exact OpenShell version `0.0.52`, `openshell status`, and an exact model ID in the host `/v1/models` response. With `--install`, invoke the official installer using an environment variable rather than interpolating into a shell pipeline; without it, print the pinned install command and fail when OpenShell is missing. Write runtime state with mode `0600`. Verify inference with a uniquely named `--no-keep` sandbox and a bounded `curl https://inference.local/v1/chat/completions` request containing `max_tokens: 1`.

- [ ] **Step 4: Run bootstrap tests**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_host.py -k bootstrap`

Expected: all bootstrap tests pass, including missing model, missing key environment variable, and version mismatch cases.

- [ ] **Step 5: Commit bootstrap**

```bash
git add scripts/openshell_runtime.py tests/assessment/openshell_fakes.py tests/assessment/test_openshell_host.py
git commit -m "feat(openshell): configure SGLang inference route"
```

### Task 4: Assessment Sandbox Lifecycle and Artifact Publication

**Files:**
- Modify: `scripts/openshell_runtime.py`
- Modify: `tests/assessment/test_openshell_host.py`

**Interfaces:**
- Consumes: committed `RuntimeLock`, local `RuntimeState`, one local path or validated GitHub URL, optional Git ref, optional recorded-response path.
- Produces: `AssessmentLaunchResult(exit_code: int, sandbox_name: str, artifact_paths: tuple[Path, ...])` and four atomically published host artifacts.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_assess_creates_uploads_executes_downloads_and_deletes(tmp_path: Path) -> None:
    runner = FakeRunner(assessment_exit=1, create_downloaded_artifacts=True)
    result = launch_assessment(
        project_root=PROJECT_ROOT,
        repository=PROJECT_ROOT / "tests/fixtures/assessment/node-basic",
        github_url=None,
        git_ref=None,
        output_directory=tmp_path / "result",
        recorded_responses=PROJECT_ROOT / "tests/fixtures/assessment/recorded/node-basic.json",
        keep_sandbox=False,
        runner=runner,
    )
    assert result.exit_code == 1
    assert {path.name for path in result.artifact_paths} == set(ARTIFACT_NAMES)
    create = next(command for command in runner.commands if command[:3] == ("openshell", "sandbox", "create"))
    assert "--no-git-ignore" in create
    assert any(command[:3] == ("openshell", "sandbox", "download") for command in runner.commands)
    assert runner.commands[-1][:3] == ("openshell", "sandbox", "delete")


def test_download_failure_retains_sandbox_and_prints_recovery_command(tmp_path: Path) -> None:
    runner = FakeRunner(download_exit=1)
    with pytest.raises(ArtifactDownloadError) as error:
        launch_recorded_fixture(tmp_path, runner)
    assert error.value.sandbox_name.startswith("repository-assessment-")
    assert not any(command[:3] == ("openshell", "sandbox", "delete") for command in runner.commands)
```

- [ ] **Step 2: Run tests and verify the launcher is missing**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_host.py -k 'assess or download'`

Expected: failures report missing `launch_assessment` and `ArtifactDownloadError`.

- [ ] **Step 3: Implement safe staging and lifecycle**

Use `tempfile.TemporaryDirectory`, `shutil.copytree(..., symlinks=True, ignore=shutil.ignore_patterns('.git'))`, and subprocess argument arrays. For GitHub input, execute with `GIT_TERMINAL_PROMPT=0`:

```python
runner.run(["git", "init", str(staged_repository)])
runner.run(["git", "-C", str(staged_repository), "remote", "add", "origin", github_url])
runner.run(["git", "-C", str(staged_repository), "fetch", "--depth", "1", "origin", git_ref or "HEAD"])
runner.run(["git", "-C", str(staged_repository), "checkout", "--detach", "FETCH_HEAD"])
```

Build the locked image, then create with:

```python
runner.run([
    "openshell", "sandbox", "create", "--name", sandbox_name,
    "--from", lock.assessment_image, "--policy", str(policy_path),
    "--no-git-ignore", "--upload", f"{staged_repository}:/sandbox",
    "--", "/bin/true",
])
```

Run separate preflight commands for repository read, repository write denial, output write, external network denial, and `inference.local/v1/models`. Then execute `repository-assessment assess` with either recorded responses or the saved model route. Treat assessment exits 0 and 1 as publishable. Download to a temporary host directory; validate all four regular files; write each to a sibling temporary file in the requested output directory, `fsync`, then `os.replace`. Delete only the named sandbox and only after successful retrieval unless `--keep-sandbox` is set.

- [ ] **Step 4: Run lifecycle and full host tests**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_host.py`

Expected: all tests pass, including path spaces, malicious refs, credentialed URLs, exit 1 publication, preservation of unrelated output files, and cleanup-failure precedence.

- [ ] **Step 5: Commit lifecycle orchestration**

```bash
git add scripts/openshell_runtime.py tests/assessment/test_openshell_host.py
git commit -m "feat(openshell): run isolated repository assessments"
```

### Task 5: Offline and Live Acceptance, Documentation, and Final Verification

**Files:**
- Create: `scripts/openshell/acceptance-assessment`
- Modify: `docs/ASSESSMENT.md`
- Modify: `tests/assessment/test_documentation_contract.py`
- Create: `docs/validation/2026-07-22-openshell-runtime-validation.md`

**Interfaces:**
- Consumes: `scripts/openshell/bootstrap`, `scripts/openshell/assess`, local Docker/OpenShell, and existing recorded fixture.
- Produces: reproducible offline acceptance command, opt-in live acceptance command, and credential-free validation evidence.

- [ ] **Step 1: Write failing documentation assertions**

```python
def test_assessment_docs_use_runtime_launchers() -> None:
    text = Path("docs/ASSESSMENT.md").read_text()
    assert "scripts/openshell/bootstrap" in text
    assert "scripts/openshell/assess" in text
    assert "--recorded-responses" in text
    assert "OpenShell v0.0.52" in text
    assert "host.openshell.internal" in text
    assert "openshell sandbox create --policy openshell/policy.yaml --name repository-assessment" not in text
```

- [ ] **Step 2: Run documentation tests and verify failure**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_documentation_contract.py`

Expected: the new launcher assertions fail against the old manual commands.

- [ ] **Step 3: Add acceptance driver and update the runbook**

```bash
#!/usr/bin/env bash
source "$(dirname -- "$0")/common"
MODE="${1:-offline}"
case "$MODE" in
  offline)
    exec "$PROJECT_ROOT/scripts/openshell/assess" \
      --repo "$PROJECT_ROOT/tests/fixtures/assessment/node-basic" \
      --recorded-responses "$PROJECT_ROOT/tests/fixtures/assessment/recorded/node-basic.json" \
      --output "$PROJECT_ROOT/output/openshell-offline"
    ;;
  live)
    exec "$PROJECT_ROOT/scripts/openshell/assess" \
      --repo "$PROJECT_ROOT/tests/fixtures/assessment/node-basic" \
      --output "$PROJECT_ROOT/output/openshell-live"
    ;;
  *) echo "usage: $0 [offline|live]" >&2; exit 2 ;;
esac
```

Document the pinned installer, SGLang bind requirement, bootstrap, local/GitHub assessment commands, exit statuses, `--keep-sandbox`, manual download recovery, cleanup, and logs. The validation note must record commands, versions, statuses, policy-negative results, artifact names, and credential scan results, but no prompt or model response body.

- [ ] **Step 4: Run static and offline verification**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q tests/assessment/test_openshell_host.py tests/assessment/test_openshell_runtime_contract.py tests/assessment/test_openshell_adapter.py tests/assessment/test_documentation_contract.py`

Expected: all focused tests pass.

Run: `scripts/openshell/acceptance-assessment offline`

Expected: OpenShell creates the sandbox, preflight proves read-only repository and denied egress, four artifacts are downloaded, and the sandbox is deleted.

- [ ] **Step 5: Install/configure the pinned runtime and run live verification**

Run with explicit installation approval: `scripts/openshell/bootstrap --install --sglang-url http://127.0.0.1:30000/v1 --model Qwen/Qwen3-Coder-30B-A3B-Instruct`

Expected: Docker and OpenShell versions pass, the exact model is found, `openshell inference get` reports the hashed provider/model/300-second timeout, and sandbox Chat Completions returns success.

Run: `scripts/openshell/acceptance-assessment live`

Expected: exit 0 or documented exit 1 with all four artifacts retrieved and no provider credential in artifacts or retained diagnostics.

- [ ] **Step 6: Run the full suite and commit acceptance evidence**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -q`

Expected: all tests pass. If pre-existing unrelated dirty changes fail tests, record the exact baseline failure separately and verify every OpenShell-focused test still passes before proceeding.

```bash
git add scripts/openshell/acceptance-assessment docs/ASSESSMENT.md tests/assessment/test_documentation_contract.py docs/validation/2026-07-22-openshell-runtime-validation.md
git commit -m "docs(openshell): verify assessment runtime"
```
