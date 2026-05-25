from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class WorkflowState:
    workflow_id: str
    mode: str
    raw_input: str
    user_input: str
    status: str = "direct_answer"
    objective: str = ""
    summary: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    normalized_request: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    executor_results: list[dict[str, Any]] = field(default_factory=list)
    executor_output: dict[str, Any] | None = None
    verifier_output: dict[str, Any] | None = None
    final_output: dict[str, Any] | None = None
    execution_mode: str = "standalone"
    stage3_available: bool = False
    partial_reason: str = ""
    activation_trigger: str = "none"
    execution_requested: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def create(cls, *, mode: str, raw_input: str, user_input: str) -> "WorkflowState":
        return cls(
            workflow_id=str(uuid.uuid4()),
            mode=mode,
            raw_input=raw_input,
            user_input=user_input,
            status="direct_answer" if mode == "direct_answer" else "initialized",
        )

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        self.touch()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowState":
        field_names = {item.name for item in fields(cls)}
        values = {key: value for key, value in data.items() if key in field_names}
        return cls(**values)


def compact_output(state: WorkflowState) -> dict[str, Any]:
    if state.final_output is not None:
        return {
            "workflow_id": state.workflow_id,
            **state.final_output,
            "final_output": state.final_output,
        }

    return {
        "workflow_id": state.workflow_id,
        "status": state.status,
        "objective": state.objective,
        "summary": state.summary,
        "steps": state.steps,
        "risks": state.risks,
        "blockers": state.blockers,
        "errors": state.errors,
        "executor_output": state.executor_output,
        "verifier_status": state.verifier_output.get("status") if state.verifier_output else None,
        "verifier_summary": state.verifier_output.get("summary") if state.verifier_output else None,
        "verifier_output": state.verifier_output,
        "activation_trigger": state.activation_trigger,
        "execution": state.execution_requested,
        "execution_requested": state.execution_requested,
    }


class JsonlStateStore:
    def __init__(self, path: str | Path = ".agentflow-workflow-state.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, state: WorkflowState) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def latest(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        latest_line = None
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    latest_line = line
        return json.loads(latest_line) if latest_line else None

    def get(self, workflow_id: str | None = None) -> dict[str, Any] | None:
        if workflow_id is None:
            return self.latest()
        if not self.path.exists():
            return None
        latest_match = None
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("workflow_id") == workflow_id:
                    latest_match = row
        return latest_match


def list_states(store: JsonlStateStore) -> list[dict[str, Any]]:
    if not store.path.exists():
        return []
    latest_by_id: dict[str, dict[str, Any]] = {}
    with store.path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            workflow_id = row.get("workflow_id")
            if workflow_id:
                latest_by_id[workflow_id] = row
    return sorted(latest_by_id.values(), key=lambda row: row.get("updated_at", 0), reverse=True)
