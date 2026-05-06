import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _state(status="ready", errors=None):
    from runtime.state_store import WorkflowState

    state = WorkflowState.create(mode="workflow", raw_input="啟用 workflow：x", user_input="x")
    state.status = status
    state.normalized_request = {"objective": "ship api tests"}
    state.plan = {"summary": "plan api tests"}
    state.executor_output = {
        "status": "ready",
        "step_results": [
            {"step_id": "a", "status": "done", "output": "created test matrix", "error": None},
            {"step_id": "b", "status": "failed", "output": "", "error": "missing env"},
        ],
        "blockers": ["missing env"],
    }
    state.verifier_output = {
        "status": "partial",
        "verdicts": [
            {"step_id": "a", "verdict": "pass", "reason": "done step produced output"},
            {"step_id": "b", "verdict": "fail", "reason": "missing env"},
        ],
        "summary": "verification partial: 1 pass, 1 fail, 0 skipped",
        "blockers": ["missing env"],
    }
    state.blockers = ["missing env"]
    state.errors = errors or []
    return state


def test_writer_assembles_final_output_from_state():
    from runtime.writer import Stage5Writer

    output = Stage5Writer().run(_state())

    assert output["status"] == "partial"
    assert output["objective"] == "ship api tests"
    assert output["plan_summary"] == "plan api tests"
    assert output["verification_summary"] == "verification partial: 1 pass, 1 fail, 0 skipped"
    assert output["steps"] == [
        {"step_id": "a", "status": "done", "verdict": "pass", "output": "created test matrix"},
        {"step_id": "b", "status": "failed", "verdict": "fail", "output": ""},
    ]
    assert output["blockers"] == ["missing env"]
    assert output["errors"] == []


def test_writer_status_follows_verifier_unless_state_has_errors():
    from runtime.writer import Stage5Writer

    state = _state(errors=["runtime error"])
    state.verifier_output["status"] = "ready"
    state.verifier_output["blockers"] = []
    output = Stage5Writer().run(state)

    assert output["status"] == "error"
    assert output["errors"] == ["runtime error"]


def test_writer_merges_missing_verdict_as_skipped():
    from runtime.writer import Stage5Writer

    state = _state()
    state.verifier_output["verdicts"] = []
    output = Stage5Writer().run(state)

    assert output["steps"][0]["verdict"] == "skipped"
    assert output["steps"][1]["verdict"] == "skipped"
