# OpenShell Runtime Environment Design

Date: 2026-07-22

Status: Approved

## Goal

Run the repository assessment and an optional general-purpose coding agent under
the real NVIDIA OpenShell runtime instead of presenting a host-side Python demo
as the runtime boundary.

The default workflow runs `repository-assessment` in a fresh, read-only
assessment sandbox. A separate, reusable OpenCode sandbox provides an optional
interactive agent workflow. Both use the same gateway-scoped SGLang and Qwen
route through `https://inference.local`.

Success means that a developer can configure the local runtime once, assess a
local or public GitHub repository with one command, retrieve the four assessment
artifacts, and start or reconnect to a policy-constrained OpenCode workspace.

## Decisions

- Use a local OpenShell gateway with the Docker compute driver.
- Validate against OpenShell `v0.0.52` and record that version in the runtime
  files. A later upgrade is an explicit compatibility change.
- Route an existing host-level SGLang server and Qwen model through OpenShell's
  gateway-scoped `inference.local` endpoint.
- Keep `repository-assessment` as the default product workflow.
- Provide OpenCode, not Codex, as the first optional general-purpose agent.
- Use separate sandbox images and policies for assessment and OpenCode.
- Create a fresh assessment sandbox for every run and delete it after artifact
  retrieval. Reuse the OpenCode sandbox until the user explicitly deletes it.
- Accept a local repository or a public `https://github.com/...` URL. Clone
  GitHub sources on the host and upload the resulting repository at sandbox
  creation time.
- Keep ordinary network egress closed in both sandbox profiles. Model traffic
  uses `inference.local`, which OpenShell routes before ordinary network policy
  evaluation.

## Non-Goals

- Kubernetes-hosted OpenShell gateways
- private GitHub repositories, SSH repository URLs, or arbitrary Git hosts
- Codex, Claude Code, or other general-purpose agent CLIs
- model serving inside the assessment sandbox
- changing the assessment evidence, topic, or artifact contracts
- Kubernetes manifest generation, deployment, or operational-value invention
- automatic policy expansion or unattended Policy Advisor approval

## Architecture

```text
Host SGLang + Qwen
        ^
        | OpenAI-compatible provider
        |
OpenShell inference.local
        ^
        |
Local OpenShell Gateway (Docker driver)
        |
        +-- Fresh assessment sandbox
        |     custom assessment image
        |     read-only uploaded repository
        |     repository-assessment
        |
        +-- Reusable OpenCode sandbox
              project image derived from the pinned OpenShell base image
              writable uploaded workspace
              OpenCode + repository assessment skill
```

OpenShell owns the runtime boundary: the CLI controls the gateway, the gateway
creates the Docker sandbox, and the in-sandbox supervisor launches the child
process under filesystem, process, network, and inference controls. Host helper
scripts only validate input and invoke the official `openshell` CLI. They do not
implement model planning or tool selection.

## Components

### Runtime Bootstrap

The bootstrap command performs idempotent host setup and verification:

1. verify Docker Engine or Docker Desktop is available and meets OpenShell's
   supported Docker requirement;
2. install OpenShell `v0.0.52` only when the user explicitly authorizes the
   installation, otherwise report the exact install command;
3. verify the local gateway with `openshell status` and select its Docker-backed
   gateway;
4. verify the host-facing SGLang URL exposes `/v1/models` and the requested Qwen
   model;
5. derive the gateway-facing URL: a host loopback URL becomes the equivalent
   `host.openshell.internal` URL while an explicitly supplied reachable LAN URL
   remains unchanged;
6. create or update an OpenAI-compatible OpenShell provider with that
   gateway-facing URL, never a `127.0.0.1` gateway destination;
7. configure the gateway-scoped inference route with `openshell inference set`,
   including a 300-second upstream timeout;
8. verify `GET /v1/models` and one bounded `POST /v1/chat/completions` request
   through `https://inference.local` from an OpenShell sandbox.

SGLang must listen on an address reachable from the gateway. An unauthenticated
local SGLang server uses a non-secret placeholder provider key. An authenticated
server reads its key from a named host environment variable and never writes it
to this repository, the sandbox filesystem, or assessment artifacts.

### Assessment Image

The assessment image is built from a local Dockerfile and contains:

- a Python runtime compatible with the project's `>=3.12` requirement;
- the built and installed `repository-assessment` package with locked runtime
  dependencies;
- `/app` for immutable application content;
- empty `/sandbox/repository` and `/sandbox/output` locations with ownership
  suitable for the restricted `sandbox` user;
- no package installation step at sandbox startup.

The OpenShell Docker driver supplies and starts the supervisor. The custom image
does not implement a competing init, policy engine, or credential mechanism.

### OpenCode Image and Sandbox

The interactive path uses a project-owned image derived from an immutable digest
of the OpenShell community base image that ships OpenCode. The image bakes in a
new thin repository assessment Skill as read-only content. That Skill invokes
the `repository-assessment` product path for a formal assessment and never
silently substitutes the existing deterministic compatibility Skill. The image
also contains the minimal OpenCode configuration needed to call
`https://inference.local/v1` with the configured Qwen model.

The launcher uploads the selected repository into `/sandbox/workspace`. The
OpenShell runtime version and community base-image digest are recorded together
in `openshell/runtime.lock` so the two images are reproducible and upgraded as
one reviewed compatibility change.

The launcher creates the named sandbox when it does not exist and reconnects to
it when it does. It rejects reuse when the existing sandbox's labels identify a
different repository or runtime profile. The user must invoke the cleanup
command to delete this sandbox.

## Host Command Interface

The repository provides thin executable shell commands under
`scripts/openshell/`:

```bash
scripts/openshell/bootstrap \
  --sglang-url http://127.0.0.1:30000/v1 \
  --model Qwen/Qwen3-Coder-30B-A3B-Instruct

scripts/openshell/assess \
  --repo ./target-repository \
  --output ./output/assessment

scripts/openshell/assess \
  --github https://github.com/org/repository \
  --ref <commit-or-tag> \
  --output ./output/assessment

scripts/openshell/opencode \
  --repo ./target-repository \
  --name repository-opencode

scripts/openshell/cleanup --name repository-opencode
```

`--repo` and `--github` are mutually exclusive. The GitHub form accepts only a
public HTTPS URL on `github.com`, rejects embedded credentials, and records the
resolved commit. A supplied `--ref` is resolved by Git and does not appear in a
shell-evaluated command string.

The assessment launcher supports `--keep-sandbox` for explicit debugging. The
default behavior is cleanup after artifacts and logs have been retrieved.

## Sandbox Policies

### Assessment Policy

The static filesystem policy grants read-only access to `/usr`, `/bin`, `/lib`,
`/lib64`, `/etc`, `/app`, `/sandbox/repository`, `/proc`, and `/dev/urandom`.
The assessment image must create every listed path so `hard_requirement` cannot
fail because of an absent optional directory. The policy grants write access
only to `/sandbox/output`, `/tmp`, and `/dev/null`. It sets
`include_workdir: false`.

The process runs as user and group `sandbox`. Landlock uses
`hard_requirement`; failure to apply the complete ruleset prevents assessment
startup. Ordinary `network_policies` remain empty. No GitHub or package-registry
access is available from the assessment sandbox.

### OpenCode Policy

The OpenCode policy grants read-only access to `/usr`, `/bin`, `/lib`, `/lib64`,
`/etc`, `/opt/repository-assessment`, `/proc`, and `/dev/urandom`. It grants
read-write access to `/sandbox/workspace`, `/sandbox/.config/opencode`,
`/sandbox/.local/share/opencode`, `/tmp`, and `/dev/null`. The derived image
creates every policy path. The policy uses `include_workdir: false`, Landlock
`hard_requirement`, and the `sandbox` user and group. It does not grant ordinary
network egress. The initial implementation does not enable Policy Advisor or
automatic policy updates.

The writable OpenCode workspace is intentionally separate from the assessment
security contract. Results produced by OpenCode are explanations or exploratory
changes and are not substituted for the evidence-checked assessment artifacts.

## Assessment Data Flow

1. Validate the input source and resolve the host output path.
2. Copy a local repository, or clone a public GitHub repository with
   `GIT_TERMINAL_PROMPT=0`, into a host temporary directory whose final child is
   named `repository`. Exclude `.git` metadata but preserve all other input
   bytes, including ignored files explicitly present in the selected local
   repository scope.
3. Resolve and record the Git commit when the input is a Git repository.
4. Build or reuse the pinned assessment image.
5. Create a uniquely named sandbox with the assessment policy and upload the
   staged `repository` directory at creation time using `--no-git-ignore`.
6. Run a security preflight inside the sandbox:
   - repository read succeeds;
   - repository write fails;
   - output write succeeds;
   - an unapproved external request fails;
   - model discovery through `inference.local` succeeds.
7. Execute `repository-assessment assess` against `/sandbox/repository` and
   write to `/sandbox/output`.
8. Download `/sandbox/output` and bounded OpenShell diagnostics to separate host
   staging locations for every assessment exit status.
9. Atomically replace only the four known artifact files under the requested
   output path. Preserve unrelated existing files. Keep runtime diagnostics out
   of the four-artifact directory and emit their retained sibling path only when
   an infrastructure failure needs investigation.
10. Delete the assessment sandbox unless the user selected `--keep-sandbox` or
    output retrieval failed.

Creation-time staging avoids writable repository access after the supervisor
applies the static filesystem policy. The launcher accounts for OpenShell upload
basename semantics so the in-sandbox path is exactly `/sandbox/repository`.

## Failure Handling

Failures are classified at the boundary where they occur:

- missing or unsupported Docker/OpenShell: environment setup failure before a
  sandbox is created;
- unreachable SGLang or missing model: inference bootstrap failure with the
  checked URL and model name, excluding credentials;
- provider or route failure: OpenShell inference configuration failure with the
  relevant `provider get` or `inference get` diagnostic command;
- policy denial: sandbox failure with the denied path or host and an
  `openshell logs <name> --source sandbox` recovery command;
- assessment exit `1`: valid `completed_with_gaps` result whose artifacts are
  still published;
- assessment configuration or run failure: preserve any `run-log.json` and
  OpenShell logs before cleanup;
- artifact download failure: retain the sandbox and print its exact name plus
  the manual download and cleanup commands;
- cleanup failure: retain the primary run result and report the leftover
  sandbox without masking the original exit status.

No retry loop creates multiple assessment sandboxes automatically. A user can
rerun the command after correcting an environment or policy problem.

## Verification

### Static Tests

- validate both YAML files against the expected schema-v1 structure;
- assert assessment repository access is read-only and output access is
  read-write;
- assert OpenCode workspace access is read-write;
- assert both policies run as `sandbox` and omit ordinary egress;
- verify launcher argument validation and command construction without shell
  evaluation of repository URLs, refs, or paths.

### Image Smoke Test

Build the assessment image and run `repository-assessment --help` under
OpenShell. Confirm the installed package imports without network access or a
runtime dependency installation step.

### Offline OpenShell Acceptance

Run the committed `node-basic` recorded-response fixture inside an assessment
sandbox. Assert:

- the repository cannot be changed;
- the output directory is writable;
- ordinary egress is denied;
- the run produces exactly the four versioned assessment artifacts;
- artifacts can be downloaded before sandbox deletion.

### Live SGLang Acceptance

Run the same small fixture through `inference.local` and the configured SGLang
Qwen model. Assert the model discovery and Chat Completions path work, the run
reaches a documented assessment status, the four artifacts are retrievable, and
no credential value occurs in an artifact or sandbox log collected by the
launcher.

### OpenCode Acceptance

Create the reusable OpenCode sandbox, read repository files, load the repository
analyzer Skill, and complete one bounded non-interactive prompt through
`inference.local`. Re-run the launcher and verify it reconnects to the same
matching sandbox. Delete it with the cleanup command.

## Acceptance Criteria

- One bootstrap command configures and verifies the local Docker gateway and
  SGLang-backed `inference.local` route.
- One assessment command accepts either a local path or public GitHub HTTPS URL.
- The assessment and all its model requests execute under the OpenShell
  supervisor and assessment policy.
- The uploaded assessment repository is not writable from the sandbox.
- The four assessment artifacts are present on the host after a completed or
  completed-with-gaps run.
- Provider credentials are absent from sandbox files, collected logs, and
  assessment artifacts.
- A reusable OpenCode sandbox can be created, reconnected, and explicitly
  deleted.
- Static, offline OpenShell, live SGLang, policy-negative, and OpenCode smoke
  tests pass on the target local machine.

## Authoritative Runtime References

- [NVIDIA OpenShell repository](https://github.com/NVIDIA/OpenShell)
- [OpenShell installation](https://docs.nvidia.com/openshell/latest/about/installation)
- [Manage sandboxes](https://docs.nvidia.com/openshell/latest/sandboxes/manage-sandboxes)
- [Inference routing](https://docs.nvidia.com/openshell/latest/sandboxes/inference-routing)
- [Policy schema](https://docs.nvidia.com/openshell/latest/reference/policy-schema)
- [Sandbox compute drivers](https://docs.nvidia.com/openshell/latest/reference/sandbox-compute-drivers)
