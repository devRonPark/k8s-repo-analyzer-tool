# ADR 0001: OpenShell Repository Assessment Package

Date: 2026-07-21

## Status

Superseded by ADR 0002

On 2026-07-22 this direction was superseded. Current official OpenShell is used as
a sandbox runtime created with `openshell sandbox create` and configured with a
schema-v1 policy. The obsolete repository-owned custom package manifest assumption
described below was not implemented. The remaining text is preserved as historical
context.

## Context

The project needs an Agentic AI demo and future product packaging path for repository-backed Kubernetes migration review through OpenShell and an SGLang-hosted Qwen3-Coder model.

The existing analyzer is deterministic and evidence-backed. It reads application repositories and reports Kubernetes migration context, but it does not generate Kubernetes manifests or decide operational values. The OpenShell package must preserve that boundary while making the agent workflow visible and usable from a simple input.

The initial OpenShell packaging plan assumed a local sandbox-visible repository path and a different package namespace. For this project, the product-facing default input should be a public GitHub URL, and the actual codebase uses `repo_analyzer`, not `migration_agent`.

## Decision

Build an OpenShell-facing repository assessment package around the existing analyzer.

The package will use `repository_assessment` as the product-facing capability name and `repository-agent-openshell` as the wrapper CLI name.

The default source input is a public HTTPS GitHub URL. The v1 package supports `github.com` public HTTPS repositories only. It rejects private repositories, SSH URLs, arbitrary HTTPS hosts, and credential-bearing URLs. The package performs a shallow fetch with a 120 second timeout and records the resolved commit SHA.

Each repository assessment creates a repository assessment run. Follow-up capabilities reuse the run by `run_id` instead of fetching or analyzing the repository again.

The OpenShell result contract is a compact `openshell-capability-result/v1` Capability Run Result. Unknowns, source conflicts, and migration risks keep top-level status `analysis_complete`; they are reported through warnings, risk artifacts, next actions, and handoff questions.

The package exposes three follow-up model-visible capabilities aligned with user-visible decisions:

- `identify_migration_risks`
- `prepare_handoff_questions`
- `explain_evidence`

These capabilities are deterministic wrappers over analyzer output. The LLM may explain or summarize their outputs, but it must not invent new repository facts or operational decisions.

OpenShell packaging uses `agent.yaml`, prompt files, a source-based Docker build context, and CLI subcommands. It does not create an OpenShell `.cli` manifest or OpenCLI artifacts.

The project keeps its existing Python `>=3.12` requirement. The OpenShell Docker/runtime package must use a compatible Python runtime rather than lowering the project requirement.

Human-facing artifacts are Korean by default for the initial audience. Machine-readable JSON field names and schema identifiers remain English.

The OpenShell README and prompt examples use `spring-projects/spring-petclinic` as the default demo repository. Node.js is documented as outside the v1 supported analysis scope rather than as a generic supported stack.

## Consequences

The demo input is simple: users can provide a GitHub URL instead of first mounting a local repository.

The scope is intentionally narrow. Private repositories and non-GitHub hosts require later credential, network, and policy design.

The model-visible workflow has more than one action without exposing parser internals as tools. This keeps the agentic trace clear while preserving deterministic analysis.

Follow-up capabilities require run persistence and artifact lookup by `run_id`. This adds packaging complexity but avoids repeated fetch/analyze work and keeps subsequent answers consistent.

Top-level `analysis_complete` does not mean "ready to deploy." It means the repository assessment completed. Readiness concerns appear as migration risks, handoff questions, and next actions.

## Alternatives Considered

Use only the existing `analyze_repository` tool. This is simpler, but the demo can look like a single opaque API call and does not clearly show follow-up agent actions.

Expose parser-level tools. This would make the tool count higher, but it pushes deterministic orchestration work onto the LLM and increases schema surface area without improving product value.

Use local repository paths only. This matches the original OpenShell plan, but it makes the demo less direct for users who naturally provide GitHub URLs.

Support private repositories in v1. This improves enterprise usefulness, but it requires token handling, redaction guarantees, network policy, and audit controls that should not be rushed into the demo package.

Lower the package to Python 3.11. This may fit some base images, but it expands the compatibility surface and conflicts with the current project requirement.
