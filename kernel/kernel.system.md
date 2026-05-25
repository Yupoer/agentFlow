AgentFlow Workflow Kernel

Rules:
- Runtime executability has priority over documentation completeness.
- Workflow activation is explicit and prefix based.
- Each internal stage must return valid JSON only.
- Stage output must pass schema validation before the next stage runs.
- Missing required information must produce blocked, not guessed content.
- External output must use the fixed compact output contract.
