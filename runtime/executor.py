from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

try:
    from runtime.tool_registry import HermesToolRegistry
    from runtime.validator import (
        LLMQuotaExceededError,
        ValidationError,
        is_llm_quota_exceeded,
        is_retryable_llm_error,
        parse_json_object,
        validate_stage3_step_result,
        validate_stage_output,
    )
except ModuleNotFoundError:
    from tool_registry import HermesToolRegistry
    from validator import (
        LLMQuotaExceededError,
        ValidationError,
        is_llm_quota_exceeded,
        is_retryable_llm_error,
        parse_json_object,
        validate_stage3_step_result,
        validate_stage_output,
    )

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LLM_QUOTA_BLOCKED_REASON = "LLM quota exceeded, workflow paused"
DELEGATE_UNAVAILABLE_ERROR = "delegate_task unavailable; Stage 3 requires Hermes delegate_task"
DelegateTaskFn = Callable[..., str]


class Stage3Executor:
    def __init__(
        self,
        *,
        delegate_task: DelegateTaskFn | None,
        parent_agent: Any | None,
        schema_path: str | Path | None = None,
        tool_registry: HermesToolRegistry | None = None,
    ) -> None:
        self.delegate_task = delegate_task
        self.parent_agent = parent_agent
        self.schema_path = Path(schema_path) if schema_path else PROJECT_ROOT / "schemas" / "stage3-executor-output.schema.json"
        self.executor_output: dict[str, Any] | None = None
        self.tool_registry = tool_registry or HermesToolRegistry()

    def run(self, plan: dict[str, Any], *, previous_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        steps = list(plan.get("steps") or [])
        step_by_id = {step.get("id", ""): step for step in steps if step.get("id")}
        completed = {r.get("step_id"): r for r in (previous_results or []) if r.get("status") == "done" and r.get("step_id") in step_by_id}
        pending = [step for step in steps if step.get("id") and step.get("id") not in completed]
        results: list[dict[str, Any]] = list(completed.values())
        status_by_id: dict[str, str] = {str(step_id): "done" for step_id in completed}

        while pending:
            progressed = False
            next_pending: list[dict[str, Any]] = []

            for step in pending:
                step_id = step["id"]
                deps = list(step.get("depends_on") or [])
                missing = [dep for dep in deps if dep not in step_by_id]
                failed_deps = [dep for dep in deps if status_by_id.get(dep) in {"failed", "skipped"}]

                if missing:
                    result = self._skipped(step_id, f"missing dependencies: {', '.join(missing)}")
                elif failed_deps:
                    result = self._skipped(step_id, f"dependency failed or skipped: {', '.join(failed_deps)}")
                elif all(status_by_id.get(dep) == "done" for dep in deps):
                    try:
                        result = self._execute_step(step)
                    except LLMQuotaExceededError as exc:
                        output = {
                            "status": "blocked",
                            "step_results": results,
                            "blockers": [LLM_QUOTA_BLOCKED_REASON],
                        }
                        validate_stage_output("stage3", output, self.schema_path)
                        self.executor_output = output
                        setattr(exc, "executor_output", output)
                        raise
                else:
                    next_pending.append(step)
                    continue

                validate_stage3_step_result(result)
                results.append(result)
                status_by_id[step_id] = result["status"]
                progressed = True

            if not progressed:
                for step in next_pending:
                    step_id = step["id"]
                    result = self._skipped(step_id, "unresolved dependency cycle")
                    validate_stage3_step_result(result)
                    results.append(result)
                    status_by_id[step_id] = result["status"]
                break

            pending = next_pending

        output = self._executor_output(results)
        validate_stage_output("stage3", output, self.schema_path)
        self.executor_output = output
        return output

    def _execute_step(self, step: dict[str, Any]) -> dict[str, Any]:
        step_id = step["id"]
        unavailable_toolsets = self.tool_registry.missing(list(step.get("toolsets") or []))
        if unavailable_toolsets:
            return self._skipped(step_id, f"missing or unsupported toolsets: {', '.join(unavailable_toolsets)}")
        if step.get("requires_approval") and step.get("approval_status") != "approved":
            return self._skipped(step_id, "side-effect step requires explicit approval")
        if self.delegate_task is None or self.parent_agent is None:
            return self._failed(step_id, DELEGATE_UNAVAILABLE_ERROR)

        backoffs = (1, 2, 4)
        for attempt in range(len(backoffs) + 1):
            try:
                return self._execute_step_once(step)
            except LLMQuotaExceededError:
                raise
            except Exception as exc:
                if is_llm_quota_exceeded(exc):
                    raise LLMQuotaExceededError(LLM_QUOTA_BLOCKED_REASON) from exc
                if attempt < len(backoffs) and is_retryable_llm_error(exc):
                    time.sleep(backoffs[attempt])
                    continue
                return self._failed(step_id, str(exc) or exc.__class__.__name__)

        return self._failed(step_id, "unreachable executor retry state")

    def _execute_step_once(self, step: dict[str, Any]) -> dict[str, Any]:
        step_id = step["id"]
        raw_delegate_result = self.delegate_task(
            goal=(
                f"Run Hermes Workflow Stage 3 Executor step_id={step_id} "
                "Return one valid JSON string only with keys: step_id, status, output, error, artifacts. "
                "status must be done, failed, or skipped. No markdown, code fences, explanations, or surrounding text."
            ),
            context=(
                "Execute this workflow plan step. Final response must be exactly one JSON object string matching:\n"
                '{"step_id":"string","status":"done|failed|skipped","output":"string","error":"string|null",'
                '"artifacts":[{"type":"file|url|email|message|json|markdown|other","uri":"string","status":"created|verified|pending|missing","description":"string"}]}\n\n'
                f"Step JSON:\n{json.dumps(step, ensure_ascii=False, indent=2)}"
            ),
            toolsets=list(step.get("toolsets") or []),
            role="leaf",
            parent_agent=self.parent_agent,
        )
        summary = self._extract_delegate_summary(raw_delegate_result)
        data = parse_json_object(_strip_json_code_fence(summary.strip()))
        data.setdefault("artifacts", [])
        validate_stage3_step_result(data)
        if data["step_id"] != step_id:
            raise ValidationError(f"stage3 step result step_id mismatch: expected {step_id}, got {data['step_id']}")
        return data

    def _extract_delegate_summary(self, raw_delegate_result: str) -> str:
        try:
            result = json.loads(raw_delegate_result)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid delegate_task envelope JSON: {exc}") from exc

        if isinstance(result, dict) and result.get("error"):
            raise _exception_from_delegate_error(str(result["error"]))

        results = result.get("results") if isinstance(result, dict) else None
        if not isinstance(results, list) or not results:
            raise RuntimeError("delegate_task returned no results")

        first = results[0]
        if not isinstance(first, dict):
            raise RuntimeError("delegate_task returned malformed result")

        if first.get("status") != "completed":
            error = first.get("error") or first.get("summary") or first.get("status") or "delegate_task failed"
            raise _exception_from_delegate_error(str(error))

        summary = first.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise RuntimeError("delegate_task completed without JSON summary")
        return summary

    def _executor_output(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        failed_or_skipped = [r for r in results if r["status"] in {"failed", "skipped"}]
        blockers = [r["error"] for r in failed_or_skipped if r.get("error")]
        return {
            "status": "partial" if failed_or_skipped else "ready",
            "step_results": results,
            "blockers": blockers,
        }

    def _failed(self, step_id: str, error: str) -> dict[str, Any]:
        return {"step_id": step_id, "status": "failed", "output": "", "error": error, "artifacts": []}

    def _skipped(self, step_id: str, error: str) -> dict[str, Any]:
        return {"step_id": step_id, "status": "skipped", "output": "", "error": error, "artifacts": []}


def _strip_json_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _exception_from_delegate_error(message: str) -> Exception:
    exc = RuntimeError(message)
    status_match = re.search(r"\b(429|5\d\d)\b", message)
    if status_match:
        setattr(exc, "status_code", int(status_match.group(1)))
    return exc
