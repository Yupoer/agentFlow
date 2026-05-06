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


def test_verifier_fails_missing_file_artifact(tmp_path):
    from runtime.verifier import Stage4Verifier

    missing = tmp_path / "missing.md"
    output = Stage4Verifier().run(
        {
            "status": "ready",
            "step_results": [
                {
                    "step_id": "write-doc",
                    "status": "done",
                    "output": "wrote doc",
                    "error": None,
                    "artifacts": [{"type": "markdown", "uri": str(missing), "status": "created"}],
                },
            ],
            "blockers": [],
        }
    )

    assert output["status"] == "partial"
    assert output["verdicts"][0] == {
        "step_id": "write-doc",
        "verdict": "fail",
        "reason": f"artifact file does not exist: {missing}",
    }


def test_verifier_passes_existing_file_artifact(tmp_path):
    from runtime.verifier import Stage4Verifier

    artifact = tmp_path / "digest.md"
    artifact.write_text("ok", encoding="utf-8")
    output = Stage4Verifier().run(
        {
            "status": "ready",
            "step_results": [
                {
                    "step_id": "write-doc",
                    "status": "done",
                    "output": "wrote doc",
                    "error": None,
                    "artifacts": [{"type": "markdown", "uri": str(artifact), "status": "created"}],
                },
            ],
            "blockers": [],
        }
    )

    assert output["status"] == "ready"
    assert output["verdicts"][0]["verdict"] == "pass"


def test_verifier_fails_unverified_email_artifact():
    from runtime.verifier import Stage4Verifier

    output = Stage4Verifier().run(
        {
            "status": "ready",
            "step_results": [
                {
                    "step_id": "send-email",
                    "status": "done",
                    "output": "sent",
                    "error": None,
                    "artifacts": [{"type": "email", "uri": "message-id-123", "status": "created"}],
                },
            ],
            "blockers": [],
        }
    )

    assert output["status"] == "partial"
    assert output["verdicts"][0]["reason"] == "artifact email is not verified in Himalaya sent mail: message-id-123"


def test_verifier_passes_verified_message_artifact():
    from runtime.verifier import Stage4Verifier

    output = Stage4Verifier().run(
        {
            "status": "ready",
            "step_results": [
                {
                    "step_id": "send-message",
                    "status": "done",
                    "output": "sent",
                    "error": None,
                    "artifacts": [{"type": "message", "uri": "discord:123", "status": "verified"}],
                },
            ],
            "blockers": [],
        }
    )

    assert output["status"] == "ready"
    assert output["verdicts"][0]["verdict"] == "pass"


def test_verifier_passes_message_send_result_artifact():
    import json
    from runtime.verifier import Stage4Verifier

    output = Stage4Verifier().run(
        {
            "status": "ready",
            "blockers": [],
            "step_results": [
                {
                    "step_id": "notify",
                    "status": "done",
                    "output": "sent",
                    "error": None,
                    "artifacts": [
                        {
                            "type": "message",
                            "uri": json.dumps({"success": True, "message_id": "abc", "target": "discord"}),
                            "status": "created",
                        }
                    ],
                }
            ],
        }
    )

    assert output["status"] == "ready"
    assert output["verdicts"][0]["verdict"] == "pass"


def test_verifier_passes_email_when_himalaya_sent_log_matches(monkeypatch):
    from runtime import artifact_verifiers
    from runtime.verifier import Stage4Verifier

    class Proc:
        returncode = 0
        stdout = '[{"message-id":"message-id-123","to":"dev@example.com"}]'

    monkeypatch.setattr(artifact_verifiers.shutil, "which", lambda name: "/usr/bin/himalaya")
    monkeypatch.setattr(artifact_verifiers.subprocess, "run", lambda *args, **kwargs: Proc())

    output = Stage4Verifier().run(
        {
            "status": "ready",
            "blockers": [],
            "step_results": [
                {
                    "step_id": "email",
                    "status": "done",
                    "output": "sent",
                    "error": None,
                    "artifacts": [{"type": "email", "uri": "message-id-123", "status": "created"}],
                }
            ],
        }
    )

    assert output["status"] == "ready"
    assert output["verdicts"][0]["verdict"] == "pass"
