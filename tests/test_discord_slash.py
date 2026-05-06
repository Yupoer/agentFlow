import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_discord_slash_natural_language_routes_to_run_argv():
    from runtime.discord_slash import parse_workflow_slash

    command = parse_workflow_slash('/workflow 幫我整理 LogPulse 專案面試講稿，先給我看')

    assert command.mode == "natural_language"
    assert command.argv == ["run", "幫我整理 LogPulse 專案面試講稿，先給我看"]
    assert command.shell_command() == "python runtime/cli.py run '幫我整理 LogPulse 專案面試講稿，先給我看'"


def test_discord_slash_template_routes_to_run_template_inputs():
    from runtime.discord_slash import parse_workflow_slash

    command = parse_workflow_slash('/workflow template research_email_digest topic=Kafka recipient=dev@example.com')

    assert command.mode == "template"
    assert command.argv == [
        "run-template",
        "research_email_digest",
        "--input",
        "topic=Kafka",
        "--input",
        "recipient=dev@example.com",
    ]


def test_discord_slash_accepts_quoted_template_values():
    from runtime.discord_slash import parse_workflow_slash

    command = parse_workflow_slash('/workflow template research_email_digest topic="AI infra" recipient=dev@example.com')

    assert command.argv == [
        "run-template",
        "research_email_digest",
        "--input",
        "topic=AI infra",
        "--input",
        "recipient=dev@example.com",
    ]


def test_discord_slash_approve_routes_to_cli_approve():
    from runtime.discord_slash import parse_workflow_slash

    command = parse_workflow_slash('/workflow approve abc123 send_discord_digest')

    assert command.mode == "approve"
    assert command.argv == ["approve", "abc123", "send_discord_digest"]


def test_cli_slash_dispatches_to_routed_command(monkeypatch, capsys):
    from runtime import cli

    calls = []

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            pass

        def run_template(self, template, inputs):
            calls.append((template, inputs))
            return {"status": "ok", "template": template, "inputs": inputs}

    monkeypatch.setattr(cli, "WorkflowOrchestrator", FakeOrchestrator)

    assert cli.main(["slash", "/workflow template research_email_digest topic=Kafka recipient=dev@example.com"]) == 0

    assert calls == [("research_email_digest", {"topic": "Kafka", "recipient": "dev@example.com"})]
    output = capsys.readouterr().out
    assert '"status": "ok"' in output
