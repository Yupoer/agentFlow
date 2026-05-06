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
            {"id": "c", "title": "C", "action": "run c", "owner": "hermes", "depends_on": ["b"]},
            {"id": "a", "title": "A", "action": "run a", "owner": "hermes", "depends_on": []},
            {"id": "b", "title": "B", "action": "run b", "owner": "hermes", "depends_on": ["a"]},
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
            {"id": "a", "title": "A", "action": "fail a", "owner": "hermes", "depends_on": []},
            {"id": "b", "title": "B", "action": "depends a", "owner": "hermes", "depends_on": ["a"]},
            {"id": "x", "title": "X", "action": "independent", "owner": "hermes", "depends_on": []},
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
            {"id": "a", "title": "A", "action": "retry a", "owner": "hermes", "depends_on": []},
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
            {"id": "a", "title": "A", "action": "quota", "owner": "hermes", "depends_on": []},
            {"id": "b", "title": "B", "action": "never", "owner": "hermes", "depends_on": []},
        ]
    }

    with pytest.raises(LLMQuotaExceededError):
        Stage3Executor(delegate_task=delegate, parent_agent=object()).run(plan)

    assert len(attempts) == 1


def test_executor_has_no_llm_fallback_when_delegate_unavailable():
    from runtime.executor import Stage3Executor

    plan = {
        "steps": [
            {"id": "a", "title": "A", "action": "run a", "owner": "hermes", "depends_on": []},
        ]
    }

    output = Stage3Executor(delegate_task=None, parent_agent=None).run(plan)

    assert output["status"] == "partial"
    assert output["step_results"] == [
        {
            "step_id": "a",
            "status": "failed",
            "output": "",
            "error": "delegate_task unavailable; Stage 3 requires Hermes delegate_task",
        }
    ]
