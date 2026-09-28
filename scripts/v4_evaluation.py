"""Combine v4 response delivery and scoring without changing raw model output."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from scripts.v4_contract import gate_response, strict_output
from scripts.v4_scoring import Outcome, score_output


CORRECT = {Outcome.CORRECT_SUPPORTED, Outcome.CORRECT_ABSTENTION}


@dataclass(frozen=True)
class Evaluation:
    task_id: str
    native_strict: bool
    delivered_valid: bool
    gate_decision: str
    outcome: str
    correct: bool
    primary_success: bool
    raw_sha256: str
    delivered_sha256: str | None
    delivered_json: str | None

    def receipt(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_response(task: dict[str, Any], raw_response: str) -> Evaluation:
    gate = gate_response(raw_response)
    if gate.delivered_json is None:
        outcome = "NO_VALID_OUTPUT"
        correct = False
    else:
        output = strict_output(gate.delivered_json)
        if output is None:
            raise AssertionError("delivery gate returned invalid JSON")
        scored = score_output(task, output)
        outcome = scored.value
        correct = scored in CORRECT
    return Evaluation(
        task_id=task["task_id"],
        native_strict=gate.native_strict,
        delivered_valid=gate.delivered_valid,
        gate_decision=gate.decision,
        outcome=outcome,
        correct=correct,
        primary_success=correct and gate.delivered_valid,
        raw_sha256=gate.raw_sha256,
        delivered_sha256=gate.delivered_sha256,
        delivered_json=gate.delivered_json,
    )
