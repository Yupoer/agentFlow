Runtime Contract

Route:
- Activated input runs workflow mode.
- Non-activated input returns direct_answer mode.

Workflow mode:
1. Render Stage 1 prompt with user_input.
2. Parse and validate Stage 1 output as normalized_request.
3. Stop as blocked if Stage 1 status is blocked.
4. Render Stage 2 prompt with user_input and normalized_request.
5. Parse and validate Stage 2 output as plan.
6. Save workflow state as JSONL.
7. Return compact external output.
