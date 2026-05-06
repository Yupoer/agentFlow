from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

try:
    from runtime.activation import parse_activation
    from runtime.executor import Stage3Executor
    from runtime.renderer import render_file
    from runtime.state_store import JsonlStateStore, WorkflowState, compact_output
    from runtime.verifier import Stage4Verifier
    from runtime.writer import Stage5Writer
    from runtime.validator import (
        LLMQuotaExceededError,
        ValidationError,
        is_llm_quota_exceeded,
        is_retryable_llm_error,
        parse_json_object,
        validate_stage_output,
    )
except ModuleNotFoundError:
    from activation import parse_activation
    from executor import Stage3Executor
    from renderer import render_file
    from state_store import JsonlStateStore, WorkflowState, compact_output
    from verifier import Stage4Verifier
    from writer import Stage5Writer
    from validator import (
        LLMQuotaExceededError,
        ValidationError,
        is_llm_quota_exceeded,
        is_retryable_llm_error,
        parse_json_object,
        validate_stage_output,
    )

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HERMES_AGENT_ROOT = Path.home() / ".hermes" / "hermes-agent"
LLM_QUOTA_BLOCKED_REASON = "LLM quota exceeded, workflow paused"
STAGE3_DELEGATE_UNAVAILABLE_REASON = "delegate_task unavailable; Stage 3 requires Hermes delegate_task"

DelegateTaskFn = Callable[..., str]
LlmFn = Callable[[str], str]


def _load_native_delegate_task() -> DelegateTaskFn | None:
    try:
        from tools.delegate_tool import delegate_task

        return delegate_task
    except Exception:
        pass

    if HERMES_AGENT_ROOT.exists() and str(HERMES_AGENT_ROOT) not in sys.path:
        sys.path.insert(0, str(HERMES_AGENT_ROOT))

    try:
        from tools.delegate_tool import delegate_task

        return delegate_task
    except Exception:
        return None


class WorkflowOrchestrator:
    def __init__(
        self,
        llm: LlmFn | None = None,
        *,
        project_root: str | Path | None = None,
        state_path: str | Path | None = None,
        delegate_task: DelegateTaskFn | None = None,
        parent_agent: Any | None = None,
        use_delegate: bool = True,
    ) -> None:
        self.llm = llm
        self.delegate_task = delegate_task or _load_native_delegate_task()
        self.parent_agent = parent_agent
        self.use_delegate = use_delegate
        self.root = Path(project_root) if project_root else PROJECT_ROOT
        self.state_store = JsonlStateStore(state_path or self.root / ".hermes-workflow-state.jsonl")

    def _new_state_with_stage3_preflight(self, message: str) -> WorkflowState:
        activation = parse_activation(message)
        state = WorkflowState.create(
            mode=activation.mode,
            raw_input=activation.raw_input,
            user_input=activation.user_input,
        )
        self._apply_stage3_preflight(state)
        return state

    def _apply_stage3_preflight(self, state: WorkflowState) -> None:
        state.stage3_available = self.delegate_task is not None and self.parent_agent is not None
        state.execution_mode = "delegated" if state.stage3_available else "standalone"
        state.partial_reason = "" if state.stage3_available else STAGE3_DELEGATE_UNAVAILABLE_REASON

    def resume(self, workflow_id: str | None = None) -> dict[str, Any]:
        row = self.state_store.get(workflow_id)
        if row is None:
            state = WorkflowState.create(mode="workflow", raw_input="resume", user_input="resume")
            self._apply_stage3_preflight(state)
            state.status = "error"
            state.errors = ["no resumable workflow state found"]
            state.final_output = Stage5Writer(
                schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
            ).run(state)
            return compact_output(state)

        state = WorkflowState.from_dict(row)
        if state.final_output is not None:
            return compact_output(state)
        self._apply_stage3_preflight(state)

        if state.status == "error" and not self._is_resumable(state):
            state.errors = state.errors or ["workflow is not resumable from error state"]
            state.final_output = Stage5Writer(
                schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
            ).run(state)
            return compact_output(state)
        if state.status != "blocked" and not self._is_resumable(state):
            state.status = "blocked"
            state.blockers = ["workflow state is not resumable"]
            state.final_output = Stage5Writer(
                schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
            ).run(state)
            return compact_output(state)

        try:
            state.blockers = []
            state.errors = []
            output = self._continue_from_state(state)
            self.state_store.append(state)
            return output
        except LLMQuotaExceededError as exc:
            return self._blocked_for_quota(state, getattr(exc, "executor_output", None))
        except ValidationError as exc:
            state.status = "error"
            state.errors = [str(exc)]
            state.final_output = Stage5Writer(
                schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
            ).run(state)
            self.state_store.append(state)
            return compact_output(state)
        except Exception as exc:
            state.status = "error"
            state.errors = [f"runtime error: {exc}"]
            state.final_output = Stage5Writer(
                schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
            ).run(state)
            self.state_store.append(state)
            return compact_output(state)

    def _is_resumable(self, state: WorkflowState) -> bool:
        return bool(state.normalized_request or state.plan or state.executor_output or state.verifier_output)

    def _continue_from_state(self, state: WorkflowState) -> dict[str, Any]:
        if state.normalized_request and not state.plan:
            plan = self._run_stage(
                stage_name="stage2",
                prompt_path=self.root / "prompts" / "stage2-planner.md",
                schema_path=self.root / "schemas" / "stage2-plan.schema.json",
                variables={
                    "user_input": state.user_input,
                    "normalized_request": state.normalized_request,
                },
            )
            state.plan = plan
            state.summary = plan["summary"]
            state.steps = plan["steps"]
            state.risks = plan["risks"]
            state.blockers = plan["blockers"]
            if plan["status"] == "blocked":
                state.status = "blocked"
                state.final_output = Stage5Writer(
                    schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
                ).run(state)
                return compact_output(state)

        if state.plan and not state.executor_output:
            executor_output = Stage3Executor(
                delegate_task=self.delegate_task,
                parent_agent=self.parent_agent,
                schema_path=self.root / "schemas" / "stage3-executor-output.schema.json",
            ).run(state.plan)
            state.executor_output = executor_output
            state.executor_results = executor_output["step_results"]

        if state.executor_output and not state.verifier_output:
            state.verifier_output = Stage4Verifier(
                schema_path=self.root / "schemas" / "stage4-verifier-output.schema.json",
            ).run(state.executor_output)

        if state.verifier_output and not state.final_output:
            state.status = state.verifier_output["status"]
            state.blockers = state.verifier_output["blockers"]
            state.final_output = Stage5Writer(
                schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
            ).run(state)
            return compact_output(state)

        state.status = "blocked"
        state.blockers = ["workflow state is not resumable"]
        state.final_output = Stage5Writer(
            schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
        ).run(state)
        return compact_output(state)

    def run(self, message: str) -> dict[str, Any]:
        activation = parse_activation(message)
        state = self._new_state_with_stage3_preflight(message)

        if activation.mode == "direct_answer":
            state.status = "direct_answer"
            self.state_store.append(state)
            return compact_output(state)

        if not activation.user_input:
            state.status = "blocked"
            state.blockers = ["workflow activation payload is empty"]
            self.state_store.append(state)
            return compact_output(state)

        try:
            normalized_request = self._run_stage(
                stage_name="stage1",
                prompt_path=self.root / "prompts" / "stage1-request-normalizer.md",
                schema_path=self.root / "schemas" / "stage1-normalized-request.schema.json",
                variables={"user_input": activation.user_input},
            )
            state.normalized_request = normalized_request
            state.objective = normalized_request["objective"]

            if normalized_request["status"] == "blocked":
                state.status = "blocked"
                state.blockers = normalized_request["blockers"]
                self.state_store.append(state)
                return compact_output(state)

            plan = self._run_stage(
                stage_name="stage2",
                prompt_path=self.root / "prompts" / "stage2-planner.md",
                schema_path=self.root / "schemas" / "stage2-plan.schema.json",
                variables={
                    "user_input": activation.user_input,
                    "normalized_request": normalized_request,
                },
            )
            state.plan = plan
            state.summary = plan["summary"]
            state.steps = plan["steps"]
            state.risks = plan["risks"]
            state.blockers = plan["blockers"]
            if plan["status"] == "blocked":
                state.status = "blocked"
                self.state_store.append(state)
                return compact_output(state)

            if plan["steps"]:
                executor_output = Stage3Executor(
                    delegate_task=self.delegate_task,
                    parent_agent=self.parent_agent,
                    schema_path=self.root / "schemas" / "stage3-executor-output.schema.json",
                ).run(plan)
                state.executor_output = executor_output
                state.executor_results = executor_output["step_results"]
                verifier_output = Stage4Verifier(
                    schema_path=self.root / "schemas" / "stage4-verifier-output.schema.json",
                ).run(executor_output)
                state.verifier_output = verifier_output
                state.status = verifier_output["status"]
                state.blockers = verifier_output["blockers"]
                state.final_output = Stage5Writer(
                    schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
                ).run(state)
                self.state_store.append(state)
                return compact_output(state)

            state.status = "ready"
            self.state_store.append(state)
            return compact_output(state)
        except LLMQuotaExceededError as exc:
            return self._blocked_for_quota(state, getattr(exc, "executor_output", None))
        except ValidationError as exc:
            state.status = "error"
            state.errors = [str(exc)]
            state.final_output = Stage5Writer(
                schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
            ).run(state)
            self.state_store.append(state)
            return compact_output(state)
        except Exception as exc:
            state.status = "error"
            state.errors = [f"runtime error: {exc}"]
            state.final_output = Stage5Writer(
                schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
            ).run(state)
            self.state_store.append(state)
            return compact_output(state)

    def _blocked_for_quota(self, state: WorkflowState, executor_output: dict[str, Any] | None = None) -> dict[str, Any]:
        state.status = "blocked"
        state.blockers = [LLM_QUOTA_BLOCKED_REASON]
        if executor_output is not None:
            state.executor_output = executor_output
            state.executor_results = executor_output.get("step_results", [])
            state.verifier_output = Stage4Verifier(
                schema_path=self.root / "schemas" / "stage4-verifier-output.schema.json",
            ).run(executor_output)
        state.final_output = Stage5Writer(
            schema_path=self.root / "schemas" / "stage5-final-output.schema.json",
        ).run(state)

        state_dict = state.to_dict()
        state_dict["blocked_reason"] = LLM_QUOTA_BLOCKED_REASON
        with self.state_store.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(state_dict, ensure_ascii=False, sort_keys=True) + "\n")

        output = compact_output(state)
        output["blocked_reason"] = LLM_QUOTA_BLOCKED_REASON
        return output

    def _run_stage(
        self,
        *,
        stage_name: str,
        prompt_path: Path,
        schema_path: Path,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = render_file(prompt_path, variables)
        raw_output = self._run_stage_prompt(stage_name, prompt)
        data = parse_json_object(raw_output)
        validate_stage_output(stage_name, data, schema_path)
        return data

    def _run_stage_prompt(self, stage_name: str, prompt: str) -> str:
        backoffs = (1, 2, 4)
        for attempt in range(len(backoffs) + 1):
            try:
                return self._run_stage_prompt_once(stage_name, prompt)
            except Exception as exc:
                if is_llm_quota_exceeded(exc):
                    raise LLMQuotaExceededError(LLM_QUOTA_BLOCKED_REASON) from exc
                if attempt >= len(backoffs) or not is_retryable_llm_error(exc):
                    raise
                time.sleep(backoffs[attempt])

        raise RuntimeError("unreachable LLM retry state")

    def _run_stage_prompt_once(self, stage_name: str, prompt: str) -> str:
        if self.use_delegate and self.delegate_task is not None:
            delegated_output = self._try_delegate_stage(stage_name, prompt)
            if delegated_output is not None:
                return delegated_output

        if self.llm is None:
            raise RuntimeError("delegate_task is unavailable and no fallback llm callable was provided")
        return self.llm(prompt)

    def _try_delegate_stage(self, stage_name: str, prompt: str) -> str | None:
        if self.delegate_task is None or self.parent_agent is None:
            return None

        goal = (
            f"Run Hermes Workflow {stage_name}. Return the stage output as one valid JSON string only. "
            "Do not add markdown, code fences, explanations, or surrounding text."
        )
        context = (
            "Execute this exact stage prompt and make your final response the JSON object string it requests:\n\n"
            f"{prompt}"
        )

        try:
            raw_delegate_result = self.delegate_task(
                goal=goal,
                context=context,
                toolsets=[],
                role="leaf",
                parent_agent=self.parent_agent,
            )
        except Exception as exc:
            if is_llm_quota_exceeded(exc) or is_retryable_llm_error(exc):
                raise
            return None

        return self._extract_delegate_stage_output(raw_delegate_result)

    def _extract_delegate_stage_output(self, raw_delegate_result: str) -> str | None:
        try:
            result = json.loads(raw_delegate_result)
        except json.JSONDecodeError:
            return None

        if isinstance(result, dict) and result.get("error"):
            return None

        results = result.get("results") if isinstance(result, dict) else None
        if not isinstance(results, list) or not results:
            return None

        first = results[0]
        if not isinstance(first, dict):
            return None
        if first.get("status") not in {"completed", "failed", "interrupted", "timeout", "error"}:
            return None
        if first.get("status") != "completed":
            raise RuntimeError(f"delegate_task subagent failed: {first.get('error') or first.get('status')}")

        summary = first.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        return _strip_json_code_fence(summary.strip())


def _strip_json_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def demo_llm(prompt: str) -> str:
    if "Stage 2" in prompt:
        return json.dumps(
            {
                "status": "ready",
                "summary": "Build and verify the minimal workflow plan.",
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Create MVP files",
                        "action": "Write runtime, schemas, prompts, kernel files, and skill files.",
                        "owner": "hermes",
                        "depends_on": [],
                    },
                    {
                        "id": "step-2",
                        "title": "Run smoke tests",
                        "action": "Validate Python syntax, JSON files, and orchestrator output.",
                        "owner": "hermes",
                        "depends_on": ["step-1"],
                    },
                ],
                "risks": [],
                "artifacts": ["hermes-workflow"],
                "blockers": [],
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "status": "ready",
            "objective": "Build a minimal executable Hermes workflow runtime.",
            "constraints": ["code-first", "minimal files", "schema validated"],
            "context": {},
            "success_criteria": ["Python syntax passes", "JSON validates", "workflow returns compact output"],
            "blockers": [],
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    orchestrator = WorkflowOrchestrator(llm=demo_llm)
    if len(sys.argv) > 1 and sys.argv[1] == "--resume":
        workflow_id = sys.argv[2] if len(sys.argv) > 2 else None
        result = orchestrator.resume(workflow_id=workflow_id)
    else:
        message = sys.argv[1] if len(sys.argv) > 1 else "啟用 workflow：建立測試計畫"
        result = orchestrator.run(message)
    print(json.dumps(result, ensure_ascii=False, indent=2))
