from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

DEFAULT_PREFIXES = (
    "啟用 workflow：",
    "啟用 workflow:",
    "workflow：",
    "workflow:",
)


@dataclass(frozen=True)
class ActivationResult:
    mode: str
    user_input: str
    raw_input: str
    activated: bool


def parse_activation(message: str, prefixes: tuple[str, ...] = DEFAULT_PREFIXES) -> ActivationResult:
    raw_input = message or ""
    text = raw_input.strip()
    for prefix in prefixes:
        if text.lower().startswith(prefix.lower()):
            return ActivationResult(
                mode="workflow",
                user_input=text[len(prefix):].strip(),
                raw_input=raw_input,
                activated=True,
            )
    return ActivationResult(
        mode="direct_answer",
        user_input=text,
        raw_input=raw_input,
        activated=False,
    )


def activate(message: str, llm: Callable[[str], str], state_path: Optional[str] = None) -> dict[str, Any]:
    from runtime.orchestrator import WorkflowOrchestrator

    return WorkflowOrchestrator(llm=llm, state_path=state_path).run(message)
