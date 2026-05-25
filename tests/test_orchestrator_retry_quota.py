import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.orchestrator import WorkflowOrchestrator
from runtime.validator import is_llm_quota_exceeded, is_retryable_llm_error


def _stage1() -> str:
    return json.dumps(
        {
            "status": "ready",
            "objective": "retry objective",
            "constraints": [],
            "context": {},
            "success_criteria": [],
            "blockers": [],
        }
    )


def _stage2() -> str:
    return json.dumps(
        {
            "status": "ready",
            "summary": "retry plan",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Retry",
                    "action": "Retry transient LLM failures",
                    "owner": "agentflow",
                    "depends_on": [],
                }
            ],
            "risks": [],
            "artifacts": [],
            "blockers": [],
        }
    )


class HttpError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class TimeoutErrorLike(Exception):
    pass


def test_retryable_error_detection_covers_timeout_and_5xx_only():
    assert is_retryable_llm_error(TimeoutError("timed out"))
    assert is_retryable_llm_error(TimeoutErrorLike("network timeout while reading"))
    assert is_retryable_llm_error(HttpError(503, "service unavailable"))
    assert not is_retryable_llm_error(HttpError(400, "bad request"))
    assert not is_retryable_llm_error(HttpError(429, "rate limit"))


def test_quota_detection_covers_429_quota_and_rate_limit_messages():
    assert is_llm_quota_exceeded(HttpError(429, "too many requests"))
    assert is_llm_quota_exceeded(Exception("quota exceeded"))
    assert is_llm_quota_exceeded(Exception("rate limit reached"))
    assert not is_llm_quota_exceeded(HttpError(503, "service unavailable"))


def test_llm_call_retries_retryable_errors_then_continues(monkeypatch, tmp_path):
    monkeypatch.setattr("runtime.orchestrator.time.sleep", lambda _seconds: None)
    attempts = []

    def llm(prompt: str) -> str:
        attempts.append(prompt)
        if len(attempts) < 3:
            raise HttpError(503, "service unavailable")
        if "Stage 2" in prompt:
            return _stage2()
        return _stage1()

    result = WorkflowOrchestrator(
        llm=llm,
        use_delegate=False,
        state_path=tmp_path / "state.jsonl",
    ).run("啟用 workflow：測試 retry")

    assert result["status"] == "blocked"
    assert result["objective"] == "retry objective"
    assert result["steps"][0]["status"] == "failed"
    assert result["final_output"]["status"] == "blocked"
    assert len(attempts) == 4


def test_quota_error_does_not_retry_and_writes_blocked_state(monkeypatch, tmp_path):
    monkeypatch.setattr("runtime.orchestrator.time.sleep", lambda _seconds: None)
    attempts = []
    state_path = tmp_path / "state.jsonl"

    def llm(prompt: str) -> str:
        attempts.append(prompt)
        raise HttpError(429, "quota exceeded")

    result = WorkflowOrchestrator(
        llm=llm,
        use_delegate=False,
        state_path=state_path,
    ).run("啟用 workflow：測試 quota")

    assert len(attempts) == 1
    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "LLM quota exceeded, workflow paused"
    assert result["blockers"] == ["LLM quota exceeded, workflow paused"]

    rows = [json.loads(line) for line in state_path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["status"] == "blocked"
    assert rows[-1]["blocked_reason"] == "LLM quota exceeded, workflow paused"
