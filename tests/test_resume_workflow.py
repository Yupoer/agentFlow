import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _envelope(summary):
    return json.dumps({"results": [{"task_index": 0, "status": "completed", "summary": json.dumps(summary)}]})


def _state(tmp_path, **updates):
    from runtime.state_store import JsonlStateStore, WorkflowState

    state = WorkflowState.create(mode="workflow", raw_input="啟用 workflow：resume", user_input="resume")
    for key, value in updates.items():
        setattr(state, key, value)
    JsonlStateStore(tmp_path / "state.jsonl").append(state)
    return state


def test_resume_from_blocked_after_stage2_continues_at_stage3(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator

    calls = []

    def delegate_task(**kwargs):
        goal = kwargs["goal"]
        calls.append(goal)
        step_id = goal.split("step_id=")[1].split()[0]
        return _envelope({"step_id": step_id, "status": "done", "output": "resumed", "error": None})

    original = _state(
        tmp_path,
        status="blocked",
        normalized_request={"status": "ready", "objective": "resume objective", "constraints": [], "context": {}, "success_criteria": [], "blockers": []},
        objective="resume objective",
        plan={
            "status": "ready",
            "summary": "resume plan",
            "steps": [{"id": "a", "title": "A", "action": "run a", "owner": "hermes", "depends_on": []}],
            "risks": [],
            "artifacts": [],
            "blockers": [],
        },
        summary="resume plan",
        steps=[{"id": "a", "title": "A", "action": "run a", "owner": "hermes", "depends_on": []}],
        blockers=["LLM quota exceeded, workflow paused"],
    )

    result = WorkflowOrchestrator(
        delegate_task=delegate_task,
        parent_agent=object(),
        state_path=tmp_path / "state.jsonl",
    ).resume(workflow_id=original.workflow_id)

    assert result["status"] == "ready"
    assert result["steps"] == [{"step_id": "a", "status": "done", "verdict": "pass", "output": "resumed"}]
    assert not any("stage1" in call or "stage2" in call for call in calls)


def test_resume_from_blocked_after_stage3_continues_at_stage4(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator

    def delegate_task(**kwargs):
        raise AssertionError("resume from stage4 must not call delegate_task")

    original = _state(
        tmp_path,
        status="blocked",
        normalized_request={"status": "ready", "objective": "resume objective", "constraints": [], "context": {}, "success_criteria": [], "blockers": []},
        objective="resume objective",
        plan={"status": "ready", "summary": "resume plan", "steps": [], "risks": [], "artifacts": [], "blockers": []},
        summary="resume plan",
        executor_output={
            "status": "ready",
            "step_results": [{"step_id": "a", "status": "done", "output": "already done", "error": None}],
            "blockers": [],
        },
        executor_results=[{"step_id": "a", "status": "done", "output": "already done", "error": None}],
    )

    result = WorkflowOrchestrator(
        delegate_task=delegate_task,
        parent_agent=object(),
        state_path=tmp_path / "state.jsonl",
    ).resume(workflow_id=original.workflow_id)

    assert result["status"] == "ready"
    assert result["verification_summary"] == "verification ready: 1 pass, 0 fail, 0 skipped"
    assert result["steps"][0]["output"] == "already done"


def test_resume_returns_existing_final_output_without_rerun(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator

    final_output = {
        "status": "ready",
        "objective": "done",
        "summary": "workflow completed successfully",
        "plan_summary": "plan",
        "execution_summary": "execution: 1 done, 0 failed, 0 skipped",
        "verification_summary": "verification ready: 1 pass, 0 fail, 0 skipped",
        "steps": [{"step_id": "a", "status": "done", "verdict": "pass", "output": "ok"}],
        "blockers": [],
        "errors": [],
        "execution_mode": "delegated",
        "stage3_available": True,
        "partial_reason": "",
    }
    original = _state(tmp_path, status="ready", final_output=final_output)

    result = WorkflowOrchestrator(state_path=tmp_path / "state.jsonl").resume(workflow_id=original.workflow_id)

    assert result["final_output"] == final_output
    assert result["steps"] == final_output["steps"]
