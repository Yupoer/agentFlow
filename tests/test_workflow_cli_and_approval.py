import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_approve_marks_step_approved_and_reruns(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFLOW_TOOLSETS", "web,file,terminal")
    from runtime.orchestrator import WorkflowOrchestrator

    state_path = tmp_path / "state.jsonl"
    calls = []

    def delegate(**kwargs):
        step_id = kwargs["goal"].split("step_id=")[1].split()[0]
        calls.append(step_id)
        return json.dumps(
            {
                "results": [
                    {
                        "task_index": 0,
                        "status": "completed",
                        "summary": json.dumps(
                            {
                                "step_id": step_id,
                                "status": "done",
                                "output": f"done {step_id}",
                                "error": None,
                                "artifacts": [{"type": "email", "uri": "message-id", "status": "verified"}],
                            }
                        ),
                    }
                ]
            }
        )

    orchestrator = WorkflowOrchestrator(delegate_task=delegate, parent_agent=object(), state_path=state_path)
    first = orchestrator.run_template(
        "research_email_digest",
        {"topic": "Kafka", "recipient": "dev@example.com", "output_path": str(tmp_path / "digest.md")},
    )

    assert first["status"] in {"blocked", "partial"}
    assert calls == ["search", "write_digest"]

    approved = orchestrator.approve(first["workflow_id"], "send_email")

    assert calls == ["search", "write_digest", "send_email"]
    assert approved["workflow_id"] == first["workflow_id"]


def test_cli_lists_templates(capsys):
    from runtime.cli import main

    assert main(["templates"]) == 0
    output = capsys.readouterr().out
    assert "research_email_digest" in output
