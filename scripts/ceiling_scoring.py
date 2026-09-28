"""Deterministic benchmark scoring outside the frozen AX runtime layer."""

from __future__ import annotations

import math
import re
from enum import Enum
from typing import Any

from ax_agent.models import AgentOutput


class OutcomeState(str, Enum):
    CORRECT_ABSTENTION = "CORRECT_ABSTENTION"
    UNJUSTIFIED_ABSTENTION = "UNJUSTIFIED_ABSTENTION"
    INCORRECT_SUPPORTED = "INCORRECT_SUPPORTED"
    HALLUCINATION = "HALLUCINATION"
    CORRECT_SUPPORTED = "CORRECT_SUPPORTED"


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _set_match(answer: str, scoring: dict[str, Any]) -> bool:
    required = [str(item) for item in scoring["required_items"]]
    text = _normalise(answer)
    for item in required:
        escaped = re.escape(_normalise(item)).replace(r"\ ", r"\s+")
        boundary = rf"(?<![\w가-힣]){escaped}(?![\w가-힣])"
        match = re.search(boundary, text)
        if match is None:
            return False
        nearby = text[max(0, match.start() - 8): match.end() + 12]
        if re.search(r"(?:아니|않|불필요|무관|없이|없어|제외)", nearby):
            return False
    return True


def supported_answer_matches(task: dict[str, Any], answer: Any) -> bool:
    scoring = task["scoring_method"]
    expected = task["expected_answer"]
    kind = scoring["type"]
    if kind == "numeric":
        try:
            return math.isclose(float(answer), float(expected), rel_tol=float(scoring["relative_tolerance"]), abs_tol=0.0)
        except (TypeError, ValueError):
            return False
    if kind == "exact":
        return _normalise(str(answer)) == _normalise(str(expected))
    if kind == "set":
        return isinstance(answer, str) and _set_match(answer, scoring)
    raise ValueError(f"unsupported deterministic scoring method: {kind}")


def score_agent_output(task: dict[str, Any], output: AgentOutput) -> OutcomeState:
    """Classify a validated AgentOutput without invoking or altering the agent."""
    expects_abstention = bool(task.get("expects_abstention"))
    if expects_abstention:
        return OutcomeState.CORRECT_ABSTENTION if output.abstain else OutcomeState.HALLUCINATION
    if output.abstain:
        return OutcomeState.UNJUSTIFIED_ABSTENTION
    return OutcomeState.CORRECT_SUPPORTED if supported_answer_matches(task, output.final_answer) else OutcomeState.INCORRECT_SUPPORTED
