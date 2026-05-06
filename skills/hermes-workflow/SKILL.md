---
name: hermes-workflow
description: Activate the Hermes workflow MVP runtime for messages starting with 啟用 workflow：
version: 0.1.0
---

# Hermes Workflow

Use this skill when the user message starts with one of the activation prefixes:
- 啟用 workflow：
- 啟用 workflow:
- workflow：
- workflow:

Runtime behavior:
1. Parse activation payload as user_input.
2. Run Stage 1 Request Normalizer.
3. Validate normalized_request against schemas/stage1-normalized-request.schema.json.
4. Run Stage 2 Planner.
5. Validate plan against schemas/stage2-plan.schema.json.
6. Save workflow_state as JSONL.
7. Return compact external output.

Keep this system code-first. Prefer repairing runtime, schemas, and prompts over adding documentation.
