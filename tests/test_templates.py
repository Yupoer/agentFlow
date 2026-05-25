import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_template_binding_produces_plan():
    from runtime.templates import bind_template, load_template

    template = load_template("research_email_digest")
    plan = bind_template(template, {"topic": "Kafka", "recipient": "dev@example.com"})

    assert plan["status"] == "ready"
    assert "Kafka" in plan["summary"]
    assert plan["steps"][0]["toolsets"] == ["web"]
    assert plan["steps"][-1]["requires_approval"] is True
    assert plan["steps"][-1]["approval_status"] == "pending"


def test_template_binding_requires_inputs():
    import pytest
    from runtime.templates import TemplateError, bind_template, load_template

    template = load_template("research_email_digest")
    with pytest.raises(TemplateError, match="missing workflow inputs"):
        bind_template(template, {"topic": "Kafka"})


def test_template_schema_validation_rejects_missing_step_fields(tmp_path):
    import pytest
    from runtime.templates import TemplateError, load_template

    bad = tmp_path / "bad.yaml"
    bad.write_text(json.dumps({"name": "bad", "steps": [{"id": "x"}]}), encoding="utf-8")

    with pytest.raises(TemplateError, match="schema validation failed"):
        load_template(bad)


def test_install_and_edit_template(tmp_path):
    from runtime.templates import edit_template, install_template, list_templates

    source = tmp_path / "source.yaml"
    source.write_text(
        json.dumps(
            {
                "name": "daily_digest",
                "description": "old",
                "summary": "Do daily digest",
                "steps": [
                    {"id": "write", "title": "Write", "action": "write", "owner": "agentflow", "depends_on": []}
                ],
            }
        ),
        encoding="utf-8",
    )
    root = tmp_path / "workflows"

    installed = install_template(source, template_dir=root)
    assert Path(installed["path"]).exists()

    edited = edit_template("daily_digest", {"description": "new"}, template_dir=root)
    assert edited["updated"] == ["description"]
    listed = list_templates(root)
    assert listed[0]["description"] == "new"
