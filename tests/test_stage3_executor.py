import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.validator import LLMQuotaExceededError


def _ok_delegate(**kwargs):
    goal = kwargs["goal"]
    step_id = goal.split("step_id=")[1].split()[0]
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
                        }
                    ),
                }
            ]
        }
    )


def test_executor_runs_steps_in_dependency_order(monkeypatch):
    from runtime.executor import Stage3Executor

    monkeypatch.setattr("runtime.executor.time.sleep", lambda _seconds: None)
    calls = []

    def delegate(**kwargs):
        calls.append(kwargs["goal"].split("step_id=")[1].split()[0])
        return _ok_delegate(**kwargs)

    plan = {
        "steps": [
            {"id": "c", "title": "C", "action": "run c", "owner": "agentflow", "depends_on": ["b"]},
            {"id": "a", "title": "A", "action": "run a", "owner": "agentflow", "depends_on": []},
            {"id": "b", "title": "B", "action": "run b", "owner": "agentflow", "depends_on": ["a"]},
        ]
    }

    output = Stage3Executor(delegate_task=delegate, parent_agent=object()).run(plan)

    assert output["status"] == "ready"
    assert calls == ["a", "b", "c"]
    assert [r["step_id"] for r in output["step_results"]] == ["a", "b", "c"]


def test_executor_marks_failed_step_and_skips_dependents_but_runs_independent(monkeypatch):
    from runtime.executor import Stage3Executor

    monkeypatch.setattr("runtime.executor.time.sleep", lambda _seconds: None)
    calls = []

    def delegate(**kwargs):
        step_id = kwargs["goal"].split("step_id=")[1].split()[0]
        calls.append(step_id)
        if step_id == "a":
            return json.dumps({"results": [{"task_index": 0, "status": "error", "error": "boom", "summary": None}]})
        return _ok_delegate(**kwargs)

    plan = {
        "steps": [
            {"id": "a", "title": "A", "action": "fail a", "owner": "agentflow", "depends_on": []},
            {"id": "b", "title": "B", "action": "depends a", "owner": "agentflow", "depends_on": ["a"]},
            {"id": "x", "title": "X", "action": "independent", "owner": "agentflow", "depends_on": []},
        ]
    }

    output = Stage3Executor(delegate_task=delegate, parent_agent=object()).run(plan)

    assert output["status"] == "partial"
    assert calls == ["a", "x"]
    by_id = {r["step_id"]: r for r in output["step_results"]}
    assert by_id["a"]["status"] == "failed"
    assert by_id["b"]["status"] == "skipped"
    assert by_id["x"]["status"] == "done"


def test_executor_retries_timeout_then_succeeds(monkeypatch):
    from runtime.executor import Stage3Executor

    sleeps = []
    monkeypatch.setattr("runtime.executor.time.sleep", lambda seconds: sleeps.append(seconds))
    attempts = []

    def delegate(**kwargs):
        attempts.append(kwargs)
        if len(attempts) < 3:
            raise TimeoutError("network timeout")
        return _ok_delegate(**kwargs)

    plan = {
        "steps": [
            {"id": "a", "title": "A", "action": "retry a", "owner": "agentflow", "depends_on": []},
        ]
    }

    output = Stage3Executor(delegate_task=delegate, parent_agent=object()).run(plan)

    assert output["status"] == "ready"
    assert len(attempts) == 3
    assert sleeps == [1, 2]


def test_executor_quota_raises_pause_immediately(monkeypatch):
    from runtime.executor import Stage3Executor

    monkeypatch.setattr("runtime.executor.time.sleep", lambda _seconds: None)
    attempts = []

    def delegate(**kwargs):
        attempts.append(kwargs)
        exc = RuntimeError("quota exceeded")
        exc.status_code = 429
        raise exc

    plan = {
        "steps": [
            {"id": "a", "title": "A", "action": "quota", "owner": "agentflow", "depends_on": []},
            {"id": "b", "title": "B", "action": "never", "owner": "agentflow", "depends_on": []},
        ]
    }

    with pytest.raises(LLMQuotaExceededError):
        Stage3Executor(delegate_task=delegate, parent_agent=object()).run(plan)

    assert len(attempts) == 1


def test_executor_has_no_llm_fallback_when_delegate_unavailable():
    from runtime.executor import Stage3Executor

    plan = {
        "steps": [
            {"id": "a", "title": "A", "action": "run a", "owner": "agentflow", "depends_on": []},
        ]
    }

    output = Stage3Executor(delegate_task=None, parent_agent=None).run(plan)

    assert output["status"] == "partial"
    assert output["step_results"] == [
        {
            "step_id": "a",
            "status": "failed",
            "output": "",
            "error": "delegate_task unavailable; Stage 3 requires delegate_task",
            "artifacts": [],
        }
    ]


def test_executor_forwards_step_toolsets_to_delegate(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_TOOLSETS", "web,file")
    from runtime.executor import Stage3Executor

    calls = []

    def delegate(**kwargs):
        calls.append(kwargs)
        return _ok_delegate(**kwargs)

    plan = {
        "steps": [
            {
                "id": "search",
                "title": "Search",
                "action": "search web",
                "owner": "agentflow",
                "depends_on": [],
                "toolsets": ["web", "file"],
            }
        ]
    }

    output = Stage3Executor(delegate_task=delegate, parent_agent=object()).run(plan)

    assert output["status"] == "ready"
    assert calls[0]["toolsets"] == ["web", "file"]


def test_executor_skips_unapproved_side_effect_without_delegate_call():
    from runtime.executor import Stage3Executor

    calls = []

    def delegate(**kwargs):
        calls.append(kwargs)
        return _ok_delegate(**kwargs)

    plan = {
        "steps": [
            {
                "id": "send-email",
                "title": "Send email",
                "action": "send email",
                "owner": "agentflow",
                "depends_on": [],
                "requires_approval": True,
                "approval_status": "pending",
            }
        ]
    }

    output = Stage3Executor(delegate_task=delegate, parent_agent=object()).run(plan)

    assert calls == []
    assert output["status"] == "partial"
    assert output["step_results"][0]["status"] == "skipped"
    assert output["step_results"][0]["error"] == "side-effect step requires explicit approval"


def test_executor_skips_unknown_toolset_before_delegate_call():
    from runtime.executor import Stage3Executor

    calls = []

    def delegate(**kwargs):
        calls.append(kwargs)
        return _ok_delegate(**kwargs)

    plan = {
        "steps": [
            {
                "id": "unknown-tool",
                "title": "Use unknown tool",
                "action": "use tool",
                "owner": "agentflow",
                "depends_on": [],
                "toolsets": ["not_installed_tool"],
            }
        ]
    }

    output = Stage3Executor(delegate_task=delegate, parent_agent=object()).run(plan)

    assert calls == []
    assert output["status"] == "partial"
    assert output["step_results"][0]["status"] == "skipped"
    assert "missing or unsupported toolsets" in output["step_results"][0]["error"]


def test_executor_uses_injected_tool_registry_availability():
    from runtime.executor import Stage3Executor

    class Registry:
        def missing(self, toolsets):
            return [toolset for toolset in toolsets if toolset == "video"]

    calls = []

    def delegate(**kwargs):
        calls.append(kwargs)
        return _ok_delegate(**kwargs)

    plan = {
        "steps": [
            {
                "id": "video-step",
                "title": "Use disabled tool",
                "action": "use video",
                "owner": "agentflow",
                "depends_on": [],
                "toolsets": ["video"],
            }
        ]
    }

    output = Stage3Executor(delegate_task=delegate, parent_agent=object(), tool_registry=Registry()).run(plan)

    assert calls == []
    assert output["status"] == "partial"
    assert output["step_results"][0]["status"] == "skipped"
    assert "video" in output["step_results"][0]["error"]


def test_executor_preserves_previous_done_results_and_reruns_only_unfinished():
    from runtime.executor import Stage3Executor

    calls = []

    def delegate(**kwargs):
        calls.append(kwargs["goal"].split("step_id=")[1].split()[0])
        return _ok_delegate(**kwargs)

    plan = {
        "steps": [
            {"id": "a", "title": "A", "action": "a", "owner": "agentflow", "depends_on": []},
            {"id": "b", "title": "B", "action": "b", "owner": "agentflow", "depends_on": ["a"]},
        ]
    }
    previous = [{"step_id": "a", "status": "done", "output": "done a", "error": None, "artifacts": []}]

    output = Stage3Executor(delegate_task=delegate, parent_agent=object()).run(plan, previous_results=previous)

    assert calls == ["b"]
    assert output["status"] == "ready"
    assert [r["step_id"] for r in output["step_results"]] == ["a", "b"]
