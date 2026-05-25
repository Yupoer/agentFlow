# Workflow Tool Comparison Demo

Small demo artifact for AgentFlow's review-first workflow path.

This case starts from a user request:

```text
啟用 workflow：
分析 LangGraph、Prefect、Temporal 三個 workflow 工具，
每個工具各輸出一份 JSON 摘要（包含 use_case、pros、cons）到桌面workflow資料夾，
最後組裝成一份 comparison.md 比較表。
先給我看計畫，我確認後再執行。
```

## What this demo shows

```text
request normalization
  -> plan-only review gate
  -> user approval
  -> web research
  -> JSON artifacts
  -> Markdown comparison
  -> deterministic validation
```

## Demo output

Read the generated comparison here:

- [comparison.md](./comparison.md)

Structured artifacts:

- [langgraph.json](./langgraph.json)
- [prefect.json](./prefect.json)
- [temporal.json](./temporal.json)
- [workflow_state.json](./workflow_state.json)

## Why this exists

The content comparison is intentionally small. The useful part is the workflow behavior:

- stops before execution when asked to show the plan first
- resumes only after approval
- writes multiple artifacts
- validates JSON structure and Markdown output
- keeps an inspectable workflow state file

Use this as a smoke-test fixture or documentation demo for agent workflow orchestration.
