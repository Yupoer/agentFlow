import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_orchestrator_runs_stage5_and_compact_output_prefers_final_output(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator

    def delegate_task(**kwargs):
        goal = kwargs["goal"]
        if "stage1" in goal:
            summary = json.dumps(
                {
                    "status": "ready",
                    "objective": "final api tests",
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
                    "summary": "assemble final output",
                    "steps": [
                        {"id": "a", "title": "A", "action": "run a", "owner": "agentflow", "depends_on": []},
                    ],
                    "risks": [],
                    "artifacts": [],
                    "blockers": [],
                }
            )
        else:
            step_id = goal.split("step_id=")[1].split()[0]
            summary = json.dumps({"step_id": step_id, "status": "done", "output": "done a", "error": None})
        return json.dumps({"results": [{"task_index": 0, "status": "completed", "summary": summary}]})

    state_path = tmp_path / "state.jsonl"
    result = WorkflowOrchestrator(
        delegate_task=delegate_task,
        parent_agent=object(),
        state_path=state_path,
    ).run("啟用 workflow：執行並組裝")

    assert result["status"] == "ready"
    assert result["objective"] == "final api tests"
    assert result["plan_summary"] == "assemble final output"
    assert result["steps"] == [{"step_id": "a", "status": "done", "verdict": "pass", "output": "done a"}]
    assert "executor_output" not in result
    assert "verifier_output" not in result
    assert result["final_output"]["status"] == "ready"

    rows = [json.loads(line) for line in state_path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["executor_output"]["status"] == "ready"
    assert rows[-1]["verifier_output"]["status"] == "ready"
    assert rows[-1]["final_output"]["status"] == "ready"


def test_orchestrator_stage5_error_compact_output_on_validation_error(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator

    def bad_llm(_prompt: str) -> str:
        return "{}"

    result = WorkflowOrchestrator(
        llm=bad_llm,
        use_delegate=False,
        state_path=tmp_path / "state.jsonl",
    ).run("啟用 workflow：壞輸出")

    assert result["status"] == "error"
    assert result["errors"]
    assert result["final_output"]["status"] == "error"
