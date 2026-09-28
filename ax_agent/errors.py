from __future__ import annotations


class AgentToolError(RuntimeError):
    """Stable, model-visible error with a machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AgentBudgetExceeded(AgentToolError):
    def __init__(self, category: str, budget: int):
        super().__init__(
            "AGENT_BUDGET_EXCEEDED",
            f"{category} tool budget of {budget} calls has been exhausted",
        )
