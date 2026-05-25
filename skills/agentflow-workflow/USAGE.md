# AgentFlow Workflow Usage

## Quick Start

Explicit activation:

```text
啟用 workflow：幫我把這個需求整理成可執行計畫，先標準化目標、限制與成功條件，再產生分步 plan JSON。
```

Semantic activation also works, conservatively, when a message contains both:

```text
workflow intent: workflow / 流程 / 多階段 / stage
action: 建 / 建立 / 設計 / 規劃 / plan / 拆步驟 / 先給我計劃
```

Example:

```text
我現在要你建一個關於 incident response 的 workflow，先給我看，我修正後再建立
```

This routes to workflow mode and sets:

```json
{
  "activation_trigger": "semantic_detector",
  "execution": false,
  "execution_requested": false
}
```

because the request contains review-first terms.

## Review-first / plan-only terms

If any of these appear, the runtime stops after Stage 1/2 and does not directly build or execute:

```text
先給我看
我修正後再建立
先 review
先review
```

## Runtime flow

1. Parse activation.
2. Stage 1: Request Normalizer.
3. Validate Stage 1 JSON.
4. Stage 2: Planner.
5. Validate Stage 2 JSON.
6. If `execution_requested=false`, return the reviewable plan.
7. Otherwise continue to Stage 3+ when available.
8. Save compact state as JSONL.
