import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_orchestrator_runs_stage4_after_stage3_and_writes_verifier_output(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator

    def delegate_task(**kwargs):
        goal = kwargs["goal"]
        if "stage1" in goal:
            summary = json.dumps(
                {
                    "status": "ready",
                    "objective": "verify execution",
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
                    "summary": "execute one step",
                    "steps": [
                        {"id": "a", "title": "A", "action": "run a", "owner": "hermes", "depends_on": []},
                    ],
                    "risks": [],
                    "artifacts": [],
                    "blockers": [],
                }
            )
        else:
            step_id = goal.split("step_id=")[1].split()[0]
            summary = json.dumps({"step_id": step_id, "status": "done", "output": "done", "error": None})
        return json.dumps({"results": [{"task_index": 0, "status": "completed", "summary": summary}]})

    result = WorkflowOrchestrator(
        delegate_task=delegate_task,
        parent_agent=object(),
        state_path=tmp_path / "state.jsonl",
    ).run("啟用 workflow：執行並驗證")

    assert result["status"] == "ready"
    assert result["verification_summary"] == "verification ready: 1 pass, 0 fail, 0 skipped"
    assert result["final_output"]["steps"] == [
        {"step_id": "a", "status": "done", "verdict": "pass", "output": "done"}
    ]

    rows = [json.loads(line) for line in (tmp_path / "state.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["verifier_output"]["status"] == "ready"


def test_orchestrator_stage4_blocks_stage3_partial_without_live_delegate(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator, demo_llm

    result = WorkflowOrchestrator(
        llm=demo_llm,
        delegate_task=None,
        parent_agent=None,
        state_path=tmp_path / "state.jsonl",
    ).run("啟用 workflow：建立最小測試計畫")

    assert result["status"] == "blocked"
    assert result["verification_summary"] == "verification blocked: 0 pass, 1 fail, 1 skipped"
    assert result["final_output"]["steps"][0]["verdict"] == "fail"
    assert result["final_output"]["steps"][1]["verdict"] == "skipped"
