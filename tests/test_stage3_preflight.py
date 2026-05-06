import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_stage3_preflight_marks_standalone_when_delegate_unavailable(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator, demo_llm

    result = WorkflowOrchestrator(
        llm=demo_llm,
        delegate_task=None,
        parent_agent=None,
        state_path=tmp_path / "state.jsonl",
    ).run("啟用 workflow：建立最小測試計畫")

    assert result["execution_mode"] == "standalone"
    assert result["stage3_available"] is False
    assert result["partial_reason"] == "delegate_task unavailable; Stage 3 requires Hermes delegate_task"
    assert result["final_output"]["execution_mode"] == "standalone"
    assert result["final_output"]["stage3_available"] is False


def test_stage3_preflight_marks_delegated_when_parent_and_delegate_exist(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator

    def delegate_task(**kwargs):
        raise AssertionError("preflight should not call delegate_task")

    orchestrator = WorkflowOrchestrator(
        delegate_task=delegate_task,
        parent_agent=object(),
        state_path=tmp_path / "state.jsonl",
    )
    state = orchestrator._new_state_with_stage3_preflight("啟用 workflow：x")

    assert state.execution_mode == "delegated"
    assert state.stage3_available is True
    assert state.partial_reason == ""
