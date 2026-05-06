import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_verifier_passes_done_steps_with_non_empty_output():
    from runtime.verifier import Stage4Verifier

    executor_output = {
        "status": "ready",
        "step_results": [
            {"step_id": "a", "status": "done", "output": "created file", "error": None},
            {"step_id": "b", "status": "done", "output": "tests passed", "error": None},
        ],
        "blockers": [],
    }

    output = Stage4Verifier().run(executor_output)

    assert output["status"] == "ready"
    assert [v["verdict"] for v in output["verdicts"]] == ["pass", "pass"]
    assert output["blockers"] == []


def test_verifier_marks_failed_and_skipped_results_partial():
    from runtime.verifier import Stage4Verifier

    executor_output = {
        "status": "partial",
        "step_results": [
            {"step_id": "a", "status": "failed", "output": "", "error": "boom"},
            {"step_id": "b", "status": "skipped", "output": "", "error": "dependency failed"},
            {"step_id": "c", "status": "done", "output": "ok", "error": None},
        ],
        "blockers": ["boom", "dependency failed"],
    }

    output = Stage4Verifier().run(executor_output)

    assert output["status"] == "blocked"
    assert {v["step_id"]: v["verdict"] for v in output["verdicts"]} == {
        "a": "fail",
        "b": "skipped",
        "c": "pass",
    }
    assert output["blockers"] == ["boom", "dependency failed"]


def test_verifier_blocks_when_executor_output_is_blocked_or_has_blockers():
    from runtime.verifier import Stage4Verifier

    output = Stage4Verifier().run(
        {
            "status": "blocked",
            "step_results": [
                {"step_id": "a", "status": "done", "output": "ok", "error": None},
            ],
            "blockers": ["LLM quota exceeded, workflow paused"],
        }
    )

    assert output["status"] == "blocked"
    assert output["verdicts"][0]["verdict"] == "pass"
    assert output["blockers"] == ["LLM quota exceeded, workflow paused"]


def test_verifier_fails_done_step_with_empty_output():
    from runtime.verifier import Stage4Verifier

    output = Stage4Verifier().run(
        {
            "status": "ready",
            "step_results": [
                {"step_id": "a", "status": "done", "output": "", "error": None},
            ],
            "blockers": [],
        }
    )

    assert output["status"] == "partial"
    assert output["verdicts"] == [
        {"step_id": "a", "verdict": "fail", "reason": "done step has empty output"}
    ]
    assert output["blockers"] == ["done step has empty output: a"]
