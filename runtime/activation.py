from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

DEFAULT_PREFIXES = (
    "啟用 workflow：",
    "啟用 workflow:",
    "workflow：",
    "workflow:",
)

WORKFLOW_INTENT_TERMS = ("workflow", "流程", "多階段", "stage")
ACTION_TERMS = ("建", "建立", "設計", "規劃", "plan", "拆步驟", "先給我計劃")
PLAN_ONLY_TERMS = ("先給我看", "我修正後再建立", "先 review", "先review")


@dataclass(frozen=True)
class ActivationResult:
    mode: str
    user_input: str
    raw_input: str
    activated: bool
    trigger: str = "none"
    execution_requested: bool = True


def parse_activation(message: str, prefixes: tuple[str, ...] = DEFAULT_PREFIXES) -> ActivationResult:
    raw_input = message or ""
    text = raw_input.strip()
    lowered = text.casefold()
    execution_requested = _execution_requested(text)

    for prefix in prefixes:
        if lowered.startswith(prefix.casefold()):
            return ActivationResult(
                mode="workflow",
                user_input=text[len(prefix):].strip(),
                raw_input=raw_input,
                activated=True,
                trigger="explicit_prefix",
                execution_requested=execution_requested,
            )

    if _has_semantic_workflow_intent(text):
        return ActivationResult(
            mode="workflow",
            user_input=text,
            raw_input=raw_input,
            activated=True,
            trigger="semantic_detector",
            execution_requested=execution_requested,
        )

    return ActivationResult(
        mode="direct_answer",
        user_input=text,
        raw_input=raw_input,
        activated=False,
        trigger="none",
        execution_requested=True,
    )


def _has_semantic_workflow_intent(text: str) -> bool:
    lowered = text.casefold()
    has_workflow_intent = any(term.casefold() in lowered for term in WORKFLOW_INTENT_TERMS)
    has_action = any(term.casefold() in lowered for term in ACTION_TERMS)
    return has_workflow_intent and has_action


def _execution_requested(text: str) -> bool:
    lowered = text.casefold()
    return not any(term.casefold() in lowered for term in PLAN_ONLY_TERMS)


def activate(message: str, llm: Callable[[str], str], state_path: Optional[str] = None) -> dict[str, Any]:
    from runtime.orchestrator import WorkflowOrchestrator

    return WorkflowOrchestrator(llm=llm, state_path=state_path).run(message)
