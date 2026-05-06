# Usage

Smoke test:
python runtime/orchestrator.py "啟用 workflow：建立測試計畫"

Python usage:
from runtime.activation import activate
result = activate("啟用 workflow：建立測試計畫", llm=my_llm_callable)

The llm callable must accept one prompt string and return one JSON string matching the active stage contract.

Final output:
After Stage 5, compact output prioritizes `final_output`: status, objective, summary, plan/execution/verification summaries, merged step statuses/verdicts, blockers, and errors. Internal stage outputs remain persisted in workflow_state JSONL.

Resume blocked workflow:
python runtime/orchestrator.py --resume [workflow_id]

Python resume:
from runtime.orchestrator import WorkflowOrchestrator
result = WorkflowOrchestrator(llm=my_llm_callable).resume(workflow_id="optional-id")
