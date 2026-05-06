from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from runtime.validator import validate_stage_output
except ModuleNotFoundError:
    from validator import validate_stage_output

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Stage4Verifier:
    def __init__(self, *, schema_path: str | Path | None = None) -> None:
        self.schema_path = Path(schema_path) if schema_path else PROJECT_ROOT / "schemas" / "stage4-verifier-output.schema.json"

    def run(self, executor_output: dict[str, Any]) -> dict[str, Any]:
        step_results = list(executor_output.get("step_results") or [])
        verdicts = [self._verdict_for(result) for result in step_results]
        blockers = list(executor_output.get("blockers") or [])

        for verdict in verdicts:
            if verdict["verdict"] == "fail" and verdict["reason"] == "done step has empty output":
                blockers.append(f"done step has empty output: {verdict['step_id']}")
            elif verdict["verdict"] == "fail" and verdict["reason"]:
                blockers.append(verdict["reason"])
            elif verdict["verdict"] == "skipped" and verdict["reason"]:
                blockers.append(verdict["reason"])

        blockers = _dedupe(blockers)
        status = self._status(executor_output, verdicts, blockers)
        output = {
            "status": status,
            "verdicts": verdicts,
            "summary": self._summary(status, verdicts),
            "blockers": blockers,
        }
        validate_stage_output("stage4", output, self.schema_path)
        return output

    def _verdict_for(self, result: dict[str, Any]) -> dict[str, str]:
        step_id = str(result.get("step_id") or "")
        status = result.get("status")
        if status == "done" and str(result.get("output") or "").strip():
            return {"step_id": step_id, "verdict": "pass", "reason": "done step produced output"}
        if status == "done":
            return {"step_id": step_id, "verdict": "fail", "reason": "done step has empty output"}
        if status == "failed":
            return {"step_id": step_id, "verdict": "fail", "reason": str(result.get("error") or "step failed")}
        if status == "skipped":
            return {"step_id": step_id, "verdict": "skipped", "reason": str(result.get("error") or "step skipped")}
        return {"step_id": step_id, "verdict": "fail", "reason": f"unknown step_result status: {status}"}

    def _status(self, executor_output: dict[str, Any], verdicts: list[dict[str, str]], blockers: list[str]) -> str:
        if executor_output.get("status") == "blocked" or executor_output.get("blockers"):
            return "blocked"
        if any(verdict["verdict"] == "fail" for verdict in verdicts):
            return "partial"
        if all(verdict["verdict"] == "pass" for verdict in verdicts):
            return "ready"
        return "partial"

    def _summary(self, status: str, verdicts: list[dict[str, str]]) -> str:
        counts = {"pass": 0, "fail": 0, "skipped": 0}
        for verdict in verdicts:
            counts[verdict["verdict"]] += 1
        return f"verification {status}: {counts['pass']} pass, {counts['fail']} fail, {counts['skipped']} skipped"


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output
