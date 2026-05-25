# AgentFlow

Reusable AI Agent Workflow Runtime.

AgentFlow turns complex AI-agent requests from one-shot prompt responses into structured, resumable, and verifiable multi-stage workflows.

## What problem this solves

Prompt-only agents are hard to control when a task has multiple steps, tool calls, side effects, and verification requirements.

This runtime adds a stable workflow contract:

```text
natural language request
  -> request normalization
  -> dependency-aware planning
  -> delegated execution
  -> deterministic verification
  -> final assembly
```

The goal is not to replace Airflow or Temporal. This is an agent-specific workflow layer focused on:

- unstable natural-language inputs
- structured LLM stage outputs
- delegated subagent execution
- toolset boundaries
- side-effect approval gates
- resumable workflow state
- artifact-based verification

## Architecture

```text
Stage 1  Request Normalizer  -> normalized_request
Stage 2  Planner             -> plan
Stage 3  Executor            -> executor_output / executor_results
Stage 4  Verifier            -> verifier_output
Stage 5  Writer / Assembler  -> final_output
```

### Stage 1: Request Normalizer

Converts a user request into structured JSON:

- objective
- constraints
- context
- success criteria
- blockers

Stage 1 does not plan or execute. It only clarifies the request contract.

### Stage 2: Planner

Turns the normalized request into a dependency-aware plan.

Each step can include:

- `id`
- `title`
- `action`
- `owner`
- `depends_on`
- `toolsets`
- `expected_artifacts`
- `verification`
- `requires_approval`
- `approval_status`

### Stage 3: Executor

Executes plan steps in dependency order using a pluggable `delegate_task` adapter.

Important behavior:

- passes `step.toolsets` to subagents
- checks missing or unsupported toolsets before execution
- skips dependent steps when dependencies fail
- detects unresolved dependency cycles
- retries retryable LLM/delegate failures
- blocks and preserves partial progress on quota / rate-limit failures
- requires explicit approval for side-effect steps
- does not use LLM fallback when real delegated execution is unavailable

### Stage 4: Verifier

Deterministic verification layer. It does not call an LLM.

It checks executor results and artifact evidence such as:

- non-empty output for completed steps
- file artifacts
- URL artifacts
- JSON / Markdown artifacts
- email / message evidence when available
- failed or skipped step reasons

### Stage 5: Writer / Assembler

Deterministically assembles final output from workflow state, plan, execution results, and verification results.

External callers receive compact output instead of verbose internal traces.

## Activation

Explicit workflow prefixes:

```text
啟用 workflow：
啟用 workflow:
workflow：
workflow:
```

Example:

```bash
python runtime/orchestrator.py "啟用 workflow：建立一個研究並寄信的 agent workflow"
```

Semantic activation is conservative. A message enters workflow mode only when it contains both:

```text
workflow intent term: workflow / 流程 / 多階段 / stage
action term: 建 / 建立 / 設計 / 規劃 / plan / 拆步驟 / 先給我計劃
```

Review-first markers disable execution and stop after Stage 1/2 planning:

```text
先給我看
我修正後再建立
先 review
先review
```

## Standalone vs delegated mode

```text
standalone
- no live parent_agent context, or no delegate_task
- Stage 1/2 can use a fallback llm callable in tests
- Stage 3 reports delegate unavailable instead of pretending execution succeeded

delegated
- has live parent_agent + delegate_task
- Stage 3 can execute plan steps through Hermes subagents
```

## Workflow state and resume

Workflow state is appended to JSONL:

```text
.hermes-workflow-state.jsonl
```

Resume behavior:

```text
has normalized_request, no plan          -> continue from Stage 2
has plan, no executor_output             -> continue from Stage 3
has executor_output, no verifier_output  -> continue from Stage 4
has verifier_output, no final_output      -> continue from Stage 5
has final_output                          -> return final_output
```

CLI:

```bash
python runtime/orchestrator.py --resume
python runtime/orchestrator.py --resume <workflow_id>
```

## Reusable workflow templates

Templates live under:

```text
workflows/*.yaml
```

Current examples include:

- `research_email_digest.yaml`
- `taiwan_job_search.yaml`
- `taiwan_job_interview_prep.yaml`
- `taiwan_job_application_batch.yaml`

## Run tests

```bash
python -m compileall -q runtime
pytest tests/ -q
```

## Project layout

```text
runtime/                  workflow runtime implementation
schemas/                  Stage 1-5 JSON schemas
prompts/                  Stage 1/2 prompt templates
kernel/                   kernel and routing rules
skills/hermes-workflow/   optional Hermes Agent skill draft and usage notes
workflows/                reusable workflow templates
tests/                    pytest coverage
manifest.json             runtime manifest
```

## Current status

This is an MVP / personal prototype, not a production-grade distributed workflow platform.

Implemented core capabilities:

- five-stage workflow skeleton
- schema validation
- semantic activation
- review-first planning mode
- delegated executor path
- toolset dispatch
- side-effect approval gate
- deterministic verifier / writer
- JSONL state persistence
- resume support
- reusable workflow templates
- pytest coverage

Known areas for future hardening:

- richer artifact verification
- stronger permission model
- observability and tracing
- concurrency control
- production scheduling
- deeper integration with live agent runtime contexts
