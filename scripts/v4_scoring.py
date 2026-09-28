"""Development scorer for the proposed ax-exp-v4 answer representations."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from scripts.v4_contract import AgentOutputV4


class Outcome(str, Enum):
    CORRECT_SUPPORTED = "CORRECT_SUPPORTED"
    INCORRECT_SUPPORTED = "INCORRECT_SUPPORTED"
    CORRECT_ABSTENTION = "CORRECT_ABSTENTION"
    UNJUSTIFIED_ABSTENTION = "UNJUSTIFIED_ABSTENTION"
    HALLUCINATION = "HALLUCINATION"


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("not a numeric value")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("not a numeric value") from exc
    if not result.is_finite():
        raise ValueError("non-finite numeric value")
    return result


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def validate_task_spec(task: dict[str, Any]) -> None:
    """Fail before an experiment if a task has an incomplete scoring contract."""
    method = task["scoring_method"]
    kind = method["type"]
    expected = task["expected_answer"]
    abstention = bool(task.get("expects_abstention", False))
    if abstention != (expected is None):
        raise ValueError("expected_answer null must match expects_abstention")
    if kind == "numeric_quantity":
        units = method["accepted_units"]
        if not isinstance(units, dict) or not units:
            raise ValueError("numeric task requires accepted units")
        if not abstention:
            _decimal(expected)
        for name, spec in units.items():
            if not isinstance(name, str) or not name:
                raise ValueError("empty unit name")
            if _decimal(spec["scale_to_canonical"]) <= 0:
                raise ValueError("unit scale must be positive")
            if _decimal(spec["absolute_tolerance_canonical"]) < 0:
                raise ValueError("negative numeric tolerance")
        return
    if kind == "set_items":
        if abstention:
            if method["accepted_forms"]:
                raise ValueError("abstention set task cannot reveal answer forms")
            return
        if not isinstance(expected, list) or not expected or not all(isinstance(x, str) for x in expected):
            raise ValueError("set task requires expected item strings")
        expected_normal = {_norm(item) for item in expected}
        if len(expected_normal) != len(expected):
            raise ValueError("duplicate expected set concept")
        aliases = method["accepted_forms"]
        if {_norm(concept) for concept in aliases} != expected_normal:
            raise ValueError("set concepts do not match expected_answer")
        reverse: dict[str, str] = {}
        for canonical, forms in aliases.items():
            for form in [canonical, *forms]:
                key = _norm(form)
                if key in reverse and reverse[key] != _norm(canonical):
                    raise ValueError("set form maps to multiple concepts")
                reverse[key] = _norm(canonical)
        return
    if kind == "exact_text":
        forms = method["accepted_forms"]
        if abstention:
            if forms:
                raise ValueError("abstention exact task cannot reveal answer forms")
        elif not isinstance(expected, str) or _norm(expected) not in {_norm(form) for form in forms}:
            raise ValueError("exact expected answer missing from accepted forms")
        return
    raise ValueError(f"unknown v4 scoring method: {kind}")


def supported_answer_matches(task: dict[str, Any], output: AgentOutputV4) -> bool:
    method = task["scoring_method"]
    answer = output.final_answer
    kind = method["type"]
    if kind == "numeric_quantity":
        if isinstance(answer, bool) or not isinstance(answer, (int, float)):
            return False
        unit_spec = method["accepted_units"].get(output.unit)
        if unit_spec is None:
            return False
        expected = _decimal(task["expected_answer"])
        actual = _decimal(answer) * _decimal(unit_spec["scale_to_canonical"])
        tolerance = _decimal(unit_spec["absolute_tolerance_canonical"])
        if tolerance < 0:
            raise ValueError("negative numeric tolerance")
        return abs(actual - expected) <= tolerance
    if kind == "set_items":
        if not isinstance(answer, list) or output.unit is not None:
            return False
        expected = {_norm(item) for item in task["expected_answer"]}
        aliases = method["accepted_forms"]
        reverse: dict[str, str] = {}
        if {_norm(concept) for concept in aliases} != expected:
            raise ValueError("set concepts do not match expected_answer")
        for canonical, forms in aliases.items():
            normal = _norm(canonical)
            if normal not in expected:
                raise ValueError("unregistered set concept")
            for form in [canonical, *forms]:
                key = _norm(form)
                if key in reverse and reverse[key] != normal:
                    raise ValueError("set form maps to multiple concepts")
                reverse[key] = normal
        mapped = [reverse.get(_norm(item)) for item in answer]
        return None not in mapped and len(mapped) == len(expected) and set(mapped) == expected
    if kind == "exact_text":
        return (isinstance(answer, str) and output.unit is None
                and _norm(answer) in {_norm(value) for value in method["accepted_forms"]})
    raise ValueError(f"unknown v4 scoring method: {kind}")


def score_output(task: dict[str, Any], output: AgentOutputV4) -> Outcome:
    if task.get("expects_abstention", False):
        return Outcome.CORRECT_ABSTENTION if output.abstain else Outcome.HALLUCINATION
    if output.abstain:
        return Outcome.UNJUSTIFIED_ABSTENTION
    return (Outcome.CORRECT_SUPPORTED if supported_answer_matches(task, output)
            else Outcome.INCORRECT_SUPPORTED)
