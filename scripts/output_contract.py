"""Deterministic validation for the frozen AX agent-output contract.

Strict validity and analysis-only semantic extraction are deliberately separate.
The raw response is never changed, repaired, or normalized beyond inspecting
leading and trailing whitespace for the strict whole-response check.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ax_agent.models import AgentOutput


class DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a field name."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


_DECODER = json.JSONDecoder(object_pairs_hook=_unique_object)


def _validated_agent_output(value: Any) -> AgentOutput | None:
    if not isinstance(value, dict):
        return None
    try:
        return AgentOutput.model_validate(value, strict=True)
    except ValidationError:
        return None


def strict_agent_output(raw_response: str) -> AgentOutput | None:
    """Return the output only when the entire response is one schema-valid object."""
    candidate = raw_response.strip()
    if not candidate or candidate[0] != "{" or candidate[-1] != "}":
        return None
    try:
        value, end = _DECODER.raw_decode(candidate)
    except (json.JSONDecodeError, DuplicateKeyError):
        return None
    if end != len(candidate):
        return None
    return _validated_agent_output(value)


def extract_semantic_agent_output(raw_response: str) -> AgentOutput | None:
    """Extract one unambiguous schema-valid object without repairing the response."""
    candidates: list[tuple[int, int, AgentOutput]] = []
    for start, character in enumerate(raw_response):
        if character != "{":
            continue
        try:
            value, length = _DECODER.raw_decode(raw_response[start:])
        except (json.JSONDecodeError, DuplicateKeyError):
            continue
        output = _validated_agent_output(value)
        if output is not None:
            candidates.append((start, start + length, output))
    if len(candidates) != 1:
        return None
    return candidates[0][2]


@dataclass(frozen=True)
class OutputContractResult:
    raw_response: str
    output_contract_valid: bool
    semantic_json_available: bool
    parsed_result: dict[str, Any] | None


def parse_agent_response(raw_response: str) -> OutputContractResult:
    """Report strict validity and semantic availability as independent metrics."""
    strict = strict_agent_output(raw_response)
    semantic = strict or extract_semantic_agent_output(raw_response)
    return OutputContractResult(
        raw_response=raw_response,
        output_contract_valid=strict is not None,
        semantic_json_available=semantic is not None,
        parsed_result=semantic.model_dump(mode="json") if semantic is not None else None,
    )
