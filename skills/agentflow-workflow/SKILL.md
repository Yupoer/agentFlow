---
name: agentflow-workflow
description: Activate the AgentFlow workflow MVP runtime for explicit workflow prefixes or conservative semantic workflow design/planning requests.
version: 0.1.1
---

# AgentFlow Workflow

Use this skill when the user explicitly asks to run the workflow runtime, or when the request conservatively matches a workflow-design/planning intent.

## Activation

### 1. Explicit prefix, highest priority

If the message starts with one of these prefixes, route directly to `workflow` mode:

- `啟用 workflow：`
- `啟用 workflow:`
- `workflow：`
- `workflow:`

### 2. Semantic detector, secondary and conservative

Route to `workflow` mode only when both groups appear in the same message:

- Workflow intent term: `workflow`, `流程`, `多階段`, `stage`
- Action term: `建`, `建立`, `設計`, `規劃`, `plan`, `拆步驟`, `先給我計劃`

Examples that should trigger:

- `建一個 incident response workflow`
- `幫我設計一個多階段流程`
- `plan 一個 workflow，先給我看`

Examples that should not trigger by semantic detector alone:

- `workflow 是什麼？`
- `幫我規劃今天晚餐`
- `這個流程哪裡有問題？`

## Plan-only / review-first marker

If the message contains any of these terms, set `execution=false` / `execution_requested=false` and stop after Stage 1/2 planning instead of directly building or executing:

- `先給我看`
- `我修正後再建立`
- `先 review`
- `先review`

## Runtime behavior

1. Parse activation payload as `user_input`.
2. Run Stage 1 Request Normalizer.
3. Validate `normalized_request` against `schemas/stage1-normalized-request.schema.json`.
4. Run Stage 2 Planner.
5. Validate `plan` against `schemas/stage2-plan.schema.json`.
6. If `execution_requested=false`, save state and return compact output without Stage 3 build/execution.
7. Otherwise continue to Stage 3+ when available.
8. Save `workflow_state` as JSONL.
9. Return compact external output.

Keep this system code-first. Prefer repairing runtime, schemas, prompts, and tests over adding documentation.
