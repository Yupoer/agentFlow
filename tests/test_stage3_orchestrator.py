import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_orchestrator_runs_stage3_and_writes_executor_output(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator

    def delegate_task(**kwargs):
        goal = kwargs["goal"]
        if "stage1" in goal:
            summary = json.dumps(
                {
                    "status": "ready",
                    "objective": "execute strategy",
                    "constraints": [],
                    "context": {},
                    "success_criteria": [],
                    "blockers": [],
                }
            )
        elif "stage2" in goal:
            summary = json.dumps(
                {
                    "status": "ready",
                    "summary": "execute two steps",
                    "steps": [
                        {"id": "a", "title": "A", "action": "run a", "owner": "hermes", "depends_on": []},
                        {"id": "b", "title": "B", "action": "run b", "owner": "hermes", "depends_on": ["a"]},
                    ],
                    "risks": [],
                    "artifacts": [],
                    "blockers": [],
                }
            )
        else:
            step_id = goal.split("step_id=")[1].split()[0]
            summary = json.dumps({"step_id": step_id, "status": "done", "output": f"done {step_id}", "error": None})
        return json.dumps({"results": [{"task_index": 0, "status": "completed", "summary": summary}]})

    result = WorkflowOrchestrator(
        delegate_task=delegate_task,
        parent_agent=object(),
        state_path=tmp_path / "state.jsonl",
    ).run("啟用 workflow：執行")

    assert result["status"] == "ready"
    assert [r["status"] for r in result["steps"]] == ["done", "done"]


def test_orchestrator_stage3_quota_blocks_and_writes_progress(tmp_path, monkeypatch):
    from runtime.orchestrator import WorkflowOrchestrator

    monkeypatch.setattr("runtime.executor.time.sleep", lambda _seconds: None)
    stage3_calls = []

    def delegate_task(**kwargs):
        goal = kwargs["goal"]
        if "stage1" in goal:
            summary = json.dumps(
                {
                    "status": "ready",
                    "objective": "quota progress",
                    "constraints": [],
                    "context": {},
                    "success_criteria": [],
                    "blockers": [],
                }
            )
        elif "stage2" in goal:
            summary = json.dumps(
                {
                    "status": "ready",
                    "summary": "quota after first step",
                    "steps": [
                        {"id": "a", "title": "A", "action": "run a", "owner": "hermes", "depends_on": []},
                        {"id": "b", "title": "B", "action": "quota b", "owner": "hermes", "depends_on": []},
                        {"id": "c", "title": "C", "action": "never c", "owner": "hermes", "depends_on": []},
                    ],
                    "risks": [],
                    "artifacts": [],
                    "blockers": [],
                }
            )
        else:
            step_id = goal.split("step_id=")[1].split()[0]
            stage3_calls.append(step_id)
            if step_id == "b":
                exc = RuntimeError("quota exceeded")
                exc.status_code = 429
                raise exc
            summary = json.dumps({"step_id": step_id, "status": "done", "output": f"done {step_id}", "error": None})
        return json.dumps({"results": [{"task_index": 0, "status": "completed", "summary": summary}]})

    state_path = tmp_path / "state.jsonl"
    result = WorkflowOrchestrator(
        delegate_task=delegate_task,
        parent_agent=object(),
        state_path=state_path,
    ).run("啟用 workflow：執行到 quota")

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "LLM quota exceeded, workflow paused"
    assert stage3_calls == ["a", "b"]
    assert result["steps"] == [{"step_id": "a", "status": "done", "verdict": "pass", "output": "done a"}]

    rows = [json.loads(line) for line in state_path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["status"] == "blocked"
    assert rows[-1]["executor_results"][0]["step_id"] == "a"
