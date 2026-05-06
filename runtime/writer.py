from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from runtime.state_store import WorkflowState
    from runtime.validator import validate_stage_output
except ModuleNotFoundError:
    from state_store import WorkflowState
    from validator import validate_stage_output

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Stage5Writer:
    def __init__(self, *, schema_path: str | Path | None = None) -> None:
        self.schema_path = Path(schema_path) if schema_path else PROJECT_ROOT / "schemas" / "stage5-final-output.schema.json"

    def run(self, state: WorkflowState) -> dict[str, Any]:
        normalized_request = state.normalized_request or {}
        plan = state.plan or {}
        executor_output = state.executor_output or {}
        verifier_output = state.verifier_output or {}

        steps = self._steps(executor_output, verifier_output)
        output = {
            "status": self._status(state, verifier_output),
            "objective": str(normalized_request.get("objective") or state.objective or ""),
            "summary": self._summary(state, verifier_output),
            "plan_summary": str(plan.get("summary") or state.summary or ""),
            "execution_summary": self._execution_summary(executor_output),
            "verification_summary": str(verifier_output.get("summary") or ""),
            "steps": steps,
            "blockers": _dedupe(list(state.blockers or []) + list(verifier_output.get("blockers") or []) + list(executor_output.get("blockers") or [])),
            "errors": list(state.errors or []),
            "execution_mode": state.execution_mode,
            "stage3_available": state.stage3_available,
            "partial_reason": state.partial_reason,
        }
        validate_stage_output("stage5", output, self.schema_path)
        return output

    def _status(self, state: WorkflowState, verifier_output: dict[str, Any]) -> str:
        if state.errors:
            return "error"
        status = verifier_output.get("status") or state.status
        return status if status in {"ready", "partial", "blocked", "error"} else "error"

    def _summary(self, state: WorkflowState, verifier_output: dict[str, Any]) -> str:
        if state.errors:
            return "workflow ended with errors"
        status = verifier_output.get("status") or state.status
        if status == "ready":
            return "workflow completed successfully"
        if status == "blocked":
            return "workflow is blocked"
        if status == "partial":
            return "workflow completed partially"
        return "workflow final output assembled"

    def _execution_summary(self, executor_output: dict[str, Any]) -> str:
        counts = {"done": 0, "failed": 0, "skipped": 0}
        for result in executor_output.get("step_results") or []:
            status = result.get("status")
            if status in counts:
                counts[status] += 1
        return f"execution: {counts['done']} done, {counts['failed']} failed, {counts['skipped']} skipped"

    def _steps(self, executor_output: dict[str, Any], verifier_output: dict[str, Any]) -> list[dict[str, str]]:
        verdict_by_id = {
            verdict.get("step_id"): verdict.get("verdict")
            for verdict in verifier_output.get("verdicts") or []
            if verdict.get("step_id")
        }
        steps = []
        for result in executor_output.get("step_results") or []:
            step_id = str(result.get("step_id") or "")
            steps.append(
                {
                    "step_id": step_id,
                    "status": str(result.get("status") or "skipped"),
                    "verdict": str(verdict_by_id.get(step_id) or "skipped"),
                    "output": str(result.get("output") or ""),
                }
            )
        return steps


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output
