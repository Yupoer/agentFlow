import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_taiwan_job_templates_are_loadable_and_bindable():
    from runtime.templates import bind_template, load_template

    search = bind_template(load_template("taiwan_job_search"), {"keywords": "Python backend", "sources": "104,1111"})
    assert search["status"] == "ready"
    assert search["steps"][0]["id"] == "collect_jobs"
    assert "raw_jobs.json" in search["steps"][0]["expected_artifacts"][0]
    assert any(step["id"] == "score_jobs" for step in search["steps"])

    interview = bind_template(load_template("taiwan_job_interview_prep"), {"job_detail": "Linker Vision Backend Engineer"})
    assert any("AI-assisted" in item for item in interview["risks"])
    assert interview["steps"][-1]["id"] == "write_interview_pack"

    application = bind_template(load_template("taiwan_job_application_batch"), {"selected_jobs": "job-a, job-b"})
    assert application["steps"][-1]["id"] == "verify_honesty_risk"
    assert all(step["requires_approval"] is False for step in application["steps"])


def test_taiwan_job_search_template_keeps_side_effects_approval_free_until_application():
    from runtime.templates import bind_template, load_template

    plan = bind_template(load_template("taiwan_job_search"), {})
    assert all(step["approval_status"] == "not_required" for step in plan["steps"])
    assert all(step["requires_approval"] is False for step in plan["steps"])
    assert "104/1111" in " ".join(plan["risks"])
