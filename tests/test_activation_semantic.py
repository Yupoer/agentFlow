import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stage_llm(prompt: str) -> str:
    if "Stage 2" in prompt:
        return json.dumps(
            {
                "status": "ready",
                "summary": "review-first plan",
                "steps": [
                    {"id": "step-1", "title": "Draft", "action": "draft plan", "owner": "hermes", "depends_on": []},
                ],
                "risks": [],
                "artifacts": ["plan"],
                "blockers": [],
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "status": "ready",
            "objective": "Create backend SWE interview prep workflow",
            "constraints": ["review before build"],
            "context": {},
            "success_criteria": ["plan is reviewable"],
            "blockers": [],
        },
        ensure_ascii=False,
    )


def test_explicit_prefix_has_priority_and_extracts_payload():
    from runtime.activation import parse_activation

    result = parse_activation("啟用 workflow：建立測試計畫")

    assert result.mode == "workflow"
    assert result.activated is True
    assert result.trigger == "explicit_prefix"
    assert result.user_input == "建立測試計畫"
    assert result.execution_requested is True


def test_semantic_detector_requires_workflow_intent_and_action_terms():
    from runtime.activation import parse_activation

    result = parse_activation("我現在要你建一個關於 backend swe interview prep 的 workflow")

    assert result.mode == "workflow"
    assert result.activated is True
    assert result.trigger == "semantic_detector"
    assert result.user_input.startswith("我現在要你建一個")


def test_semantic_detector_stays_direct_when_only_one_term_group_matches():
    from runtime.activation import parse_activation

    assert parse_activation("workflow 是什麼？").mode == "direct_answer"
    assert parse_activation("幫我規劃今天晚餐").mode == "direct_answer"


def test_review_first_terms_mark_execution_false():
    from runtime.activation import parse_activation

    result = parse_activation("建一個 backend prep workflow，先給我看，我修正後再建立")

    assert result.mode == "workflow"
    assert result.trigger == "semantic_detector"
    assert result.execution_requested is False


def test_orchestrator_plan_only_semantic_request_stops_after_stage2(tmp_path):
    from runtime.orchestrator import WorkflowOrchestrator

    result = WorkflowOrchestrator(
        llm=_stage_llm,
        use_delegate=False,
        state_path=tmp_path / "state.jsonl",
    ).run("我現在要你建一個關於 backend swe interview prep 的 workflow，先給我看，我修正後再建立")

    assert result["status"] == "ready"
    assert result["activation_trigger"] == "semantic_detector"
    assert result["execution"] is False
    assert result["execution_requested"] is False
    assert result["objective"] == "Create backend SWE interview prep workflow"
    assert result["summary"] == "review-first plan"
    assert result["executor_output"] is None

    rows = [json.loads(line) for line in (tmp_path / "state.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["execution_requested"] is False
    assert rows[-1]["executor_output"] is None
