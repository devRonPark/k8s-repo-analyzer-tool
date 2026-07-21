# Agent Tool Implementation Patterns in Open Source Agent Runtimes

Date: 2026-07-21

Question: how do GitHub/open-source agent runtimes usually design tools, and what does that imply for a repo-analyzer + OpenShell + SGLang Qwen3-Coder-30B-A3B-Instruct demo?

Scope: primary sources only: official project documentation and source files for OpenAI Agents SDK, LangGraph, OpenHands, smolagents, CrewAI, LlamaIndex, Semantic Kernel, AutoGen, and SGLang.

## Summary

Open-source agent runtimes do not require "many small tools" for a convincing agent demo. The common pattern is a small, typed tool surface where each tool is a meaningful capability. A single deep domain tool can be legitimate if it has a strict schema, deterministic execution, structured observations, and visible trace events.

For this repository, the current `analyze_repository` tool is defensible as a deep domain tool: it does repository inventory, parser orchestration, evidence collection, warning classification, unresolved operational-input extraction, and Kubernetes migration question generation. The weak part is not the tool count itself. The weak part is that the demo trace can look like one opaque API call unless OpenShell shows a clear Plan -> Action -> Observation -> Decision loop.

Recommendation: keep `analyze_repository` intact for the demo, and add trace/reporting around it before splitting parsers into separate tools. If another deterministic tool is added, make it a downstream decision tool such as `assess_demo_readiness`, `extract_followup_questions`, or `get_evidence_detail`, not a low-level parser tool.

## Common Patterns

### 1. Tools Are Typed Capabilities, Not Necessarily Tiny Functions

OpenAI Agents SDK lists several tool categories, including hosted tools, local runtime tools, function tools, agents-as-tools, and deferred tool search. Its function-tool path wraps Python functions and derives names, descriptions, and JSON schemas from function signatures/docstrings.[^openai-tools]

LlamaIndex explicitly documents higher-level utility tools. `OnDemandLoaderTool` can load data, index it, and query it inside one tool call; `LoadAndSearchToolSpec` splits a large-output tool into a load tool and a search tool when that helps control context size.[^llamaindex-tools]

OpenHands documents tools as Action -> Observation capabilities, with direct/simple tools and stateful factory-created tools depending on runtime configuration needs.[^openhands-tool-system]

Implication: a single coarse `analyze_repository` tool is not automatically "too thin" for an agent demo. It should be judged by whether it exposes a meaningful capability and returns useful structured observations.

### 2. Schemas Are Code-Owned and Strict

OpenAI Agents SDK can generate tool schemas from Python function signatures and Pydantic models, while custom function tools provide an explicit name, description, JSON schema, and invocation handler.[^openai-tools]

CrewAI custom tools use either a decorator or a `BaseTool` subclass with a Pydantic `args_schema`.[^crewai-tools]

smolagents requires tool attributes such as `name`, `description`, `inputs`, and `output_type`, validates names and input schemas, and can render the tool signature for prompts.[^smolagents-tools]

OpenHands uses Pydantic Action and Observation models to generate schemas and validate arguments.[^openhands-tool-system]

Implication: the repo analyzer should keep schema ownership in code. Avoid relying on prompt-only contracts for arguments, result shapes, or warning semantics.

### 3. Execution Loop Is Runtime Infrastructure

Semantic Kernel separates function advertising and function choice behavior. It supports `Auto`, `Required`, and `None`/`NoneInvoke` style behavior, where the model may choose functions, must choose functions, or cannot choose functions.[^semantic-kernel-choice]

LangGraph's prebuilt `ToolNode` centralizes tool execution and documents patterns for parallel tool execution, error handling, state injection, store injection, runtime context, and conditional routing based on tool calls.[^langgraph-tool-node]

OpenHands describes the agent as a reasoning-action loop: query the LLM, parse tool calls into action events, optionally pause for confirmation, execute tools, then append observation events.[^openhands-agent]

SGLang provides OpenAI-compatible tool-call parsing for supported model/parser pairs, but the application still owns validation, dispatch, execution, and feeding tool results back to the model.[^sglang-tool-parser]

Implication: OpenShell should own the loop and trace. The tool should return deterministic observations; the runtime should display the model's selected action, validated arguments, execution result, and next decision.

### 4. Action/Observation Is a First-Class Display Boundary

OpenHands explicitly models tool execution as `Action -> Observation` and gives Action a `visualize` property and Observation a `to_llm_content` property.[^openhands-tool-system] Its agent architecture says CLI/GUI style interfaces consume SDK events, rather than making the tool itself responsible for UI.[^openhands-overview]

OpenAI Agents SDK tracing records LLM generations, tool calls, handoffs, guardrails, and custom events.[^openai-tracing]

LlamaIndex documents streaming/debugging of tool schemas and execution events; it also supports `return_direct` when a tool result should end the loop instead of being rewritten by the agent.[^llamaindex-tools]

Implication: demo trace should be outside the core analyzer:

```text
Plan
Action: analyze_repository(...)
Observation: tool_ok=true, statuses=..., warnings=...
Decision: demo-ready | caution | not-demo-ready
```

Do not expose raw chain-of-thought. Show a compact, auditable action/observation trace.

### 5. Approval and Risk Controls Belong Outside the Prompt

OpenHands describes direct execution and confirmation modes, with security analysis before execution and risk-based blocking or confirmation.[^openhands-agent]

Semantic Kernel function choice can restrict which functions are advertised or disable function calling entirely.[^semantic-kernel-choice]

CrewAI documents error handling, caching, and asynchronous tool support as tool capabilities.[^crewai-tools]

Implication: for this demo, `analyze_repository` can remain read-only and low-risk. If OpenShell exposes shell/file/network tools during the same demo, those should have explicit approval, allowlists, timeouts, and output caps. Do not rely on the model prompt to enforce safety.

### 6. Tool Count Should Follow User-Visible Decisions

The useful split is not "one parser per file type." It is "one tool per agent decision boundary." Splitting Dockerfile, Compose, Maven, Gradle, Spring, Python settings, and SQL parsing into separate tools would increase schema surface area and make the model coordinate details that the deterministic analyzer already handles better.

Better additional tools are downstream of the analysis result:

- `assess_demo_readiness`: deterministic pass/caution/fail for demo use, based on `tool_ok`, question statuses, warnings, coverage, and known contradiction rules.
- `extract_followup_questions`: converts unresolved operational inputs into questions for platform/application owners.
- `get_evidence_detail`: retrieves concise evidence for a specific finding or migration-question answer.
- `render_migration_brief`: returns a stable Markdown brief when the demo needs deterministic output instead of LLM rewriting.

Implication: if the demo feels too single-step, add one or two decision/reporting tools. Do not split the existing analyzer's internal parser pipeline into model-visible tools.

## Comparison Table

| Project | Tool design pattern | Trace/observation pattern | Relevant lesson |
| --- | --- | --- | --- |
| OpenAI Agents SDK | Function tools, hosted tools, local runtime tools, agents-as-tools, deferred tool search | Built-in tracing with model generations and tool calls | A small typed tool surface plus trace is normal |
| LangGraph | `ToolNode` executes tool calls with error handling, injection, wrappers, and parallelism | Graph state/messages route to tool execution and back | Runtime owns orchestration; tools stay focused |
| OpenHands | Action, Observation, Executor, ToolDefinition | Event-driven action/observation loop; CLI/GUI consume events | Display trace outside tool internals |
| smolagents | Tool classes define name, description, inputs, output type, setup, forward | Tool signatures and structured output can be rendered to prompts | Tool metadata quality matters |
| CrewAI | Decorator or `BaseTool` with Pydantic args schema | Verbose crew/task execution, error handling, caching | Tool count can be broad, but schemas remain explicit |
| LlamaIndex | FunctionTool, QueryEngineTool, ToolSpecs, utility load/search tools | Tool schema debugging, streaming events, optional `return_direct` | Coarse tools are accepted when they encapsulate useful workflows |
| Semantic Kernel | Plugins/functions advertised with Auto/Required/None choice | Kernel invokes selected functions and continues the prompt loop | Function exposure and choice policy are runtime controls |
| SGLang | OpenAI-compatible tool parser | Application must execute tools and feed results back | SGLang is model serving/parser, not the agent runtime |

## Recommendation for This Demo

Use the current tool as the main domain capability:

```text
analyze_repository(repository_path, profile="kubernetes-p0", build_system="auto")
```

Then make OpenShell display a compact agent trace:

```text
Goal
- Kubernetes migration review for <repo>

Plan
1. Inspect repository through deterministic analyzer
2. Check evidence coverage, warning codes, and unresolved inputs
3. Produce migration brief
4. Decide demo readiness

Action
- analyze_repository(repo=..., profile=kubernetes-p0)

Observation
- tool_ok=true
- question_statuses={...}
- warnings=[...]
- source_coverage={...}

Decision
- demo-ready for Java/Python migration review
- caution or not-demo-ready for generic Node.js support
```

For the current branch, this is stronger than adding many tools. The visible agentic behavior comes from the loop and judgment:

1. The model selects or follows the repo-analysis action.
2. The runtime executes a deterministic, evidence-backed tool.
3. The model interprets only the tool output.
4. The runtime or prompt forces missing facts to remain unresolved.
5. The final answer includes risks and concrete follow-up decisions.

## When to Add More Tools

Add tools when they create a new decision point, not when they merely expose internal implementation details.

Add `assess_demo_readiness` if stakeholders need stable pass/caution/fail output. This would reduce demo risk because the model would not be solely responsible for deciding whether Node.js results are acceptable.

Add `extract_followup_questions` if the demo includes a handoff to platform/application owners. This makes the agent feel more proactive without weakening the analyzer boundary.

Add `get_evidence_detail` if the presenter needs to ask "why did you say that?" live. This gives a second action after the initial analysis and makes the evidence-backed nature of the tool visible.

Avoid parser-level tools unless the goal changes to interactive forensic exploration. Parser-level tools increase token/schema surface area and ask the LLM to orchestrate logic that the deterministic analyzer already handles.

## Sources

[^openai-tools]: OpenAI Agents SDK, "Tools" — https://github.com/openai/openai-agents-python/blob/main/docs/tools.md
[^openai-tracing]: OpenAI Agents SDK, "Tracing" — https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md
[^langgraph-tool-node]: LangGraph source, `tool_node.py` — https://github.com/langchain-ai/langgraph/blob/main/libs/prebuilt/langgraph/prebuilt/tool_node.py
[^openhands-tool-system]: OpenHands SDK docs, "Tool System & MCP" — https://docs.openhands.dev/sdk/arch/tool-system
[^openhands-agent]: OpenHands SDK docs, "Agent" — https://docs.openhands.dev/sdk/arch/agent
[^openhands-overview]: OpenHands SDK docs, "Overview" — https://docs.openhands.dev/sdk/arch/overview
[^smolagents-tools]: Hugging Face smolagents source, `tools.py` — https://github.com/huggingface/smolagents/blob/main/src/smolagents/tools.py
[^crewai-tools]: CrewAI docs, "Tools" — https://docs.crewai.com/en/concepts/tools
[^llamaindex-tools]: LlamaIndex docs, "Tools" — https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/tools/
[^semantic-kernel-choice]: Microsoft Semantic Kernel docs, "Function Choice Behaviors" — https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion/function-calling/function-choice-behaviors
[^sglang-tool-parser]: SGLang docs, "Tool Parser" — https://docs.sglang.io/docs/advanced_features/tool_parser
