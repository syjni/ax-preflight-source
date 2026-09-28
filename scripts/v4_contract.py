"""Development implementation of the proposed ax-exp-v4 output contract.

This module does not read or rewrite ax-exp-v3 artifacts. Native model format
compliance and the deterministic delivery gate are separate observations.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class DuplicateField(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateField(key)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant: {value}")


_DECODER = json.JSONDecoder(object_pairs_hook=_unique_object, parse_constant=_reject_constant)


class AgentOutputV4(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    final_answer: str | int | float | list[str] | None = Field(...)
    unit: str | None = Field(...)
    explanation: str = Field(max_length=2000)
    source_ids: list[str]
    abstain: bool

    @model_validator(mode="after")
    def validate_answer(self) -> "AgentOutputV4":
        if self.abstain and self.final_answer is not None:
            raise ValueError("abstention requires final_answer=null")
        if not self.abstain and self.final_answer is None:
            raise ValueError("non-abstention requires a final_answer")
        if isinstance(self.final_answer, list) and not self.final_answer:
            raise ValueError("a set answer cannot be empty")
        if isinstance(self.final_answer, float) and not math.isfinite(self.final_answer):
            raise ValueError("non-finite numeric answer")
        return self


def _decode_output(raw: str) -> tuple[AgentOutputV4, int] | None:
    try:
        value, end = _DECODER.raw_decode(raw)
        if not isinstance(value, dict):
            return None
        return AgentOutputV4.model_validate(value, strict=True), end
    except (json.JSONDecodeError, DuplicateField, ValidationError, ValueError):
        return None


def strict_output(raw: str) -> AgentOutputV4 | None:
    candidate = raw.strip()
    if not candidate.startswith("{") or not candidate.endswith("}"):
        return None
    decoded = _decode_output(candidate)
    return decoded[0] if decoded is not None and decoded[1] == len(candidate) else None


def extract_unique_output(raw: str) -> AgentOutputV4 | None:
    """Find one schema-valid object; reject any other braces outside that object."""
    candidates: list[tuple[int, int, AgentOutputV4]] = []
    for start, character in enumerate(raw):
        if character != "{":
            continue
        decoded = _decode_output(raw[start:])
        if decoded is not None:
            output, length = decoded
            candidates.append((start, start + length, output))
    if len(candidates) != 1:
        return None
    start, end, output = candidates[0]
    if any(character in "{}" for character in raw[:start] + raw[end:]):
        return None
    return output


@dataclass(frozen=True)
class DeliveryResult:
    native_strict: bool
    semantic_available: bool
    delivered_valid: bool
    decision: str
    delivered_json: str | None
    raw_sha256: str
    delivered_sha256: str | None


def gate_response(raw: str) -> DeliveryResult:
    native = strict_output(raw)
    semantic = native or extract_unique_output(raw)
    delivered = (
        json.dumps(semantic.model_dump(mode="json"), ensure_ascii=False,
                   sort_keys=True, separators=(",", ":"), allow_nan=False)
        if semantic is not None else None
    )
    if delivered is not None and strict_output(delivered) is None:
        raise AssertionError("gate produced invalid JSON")
    return DeliveryResult(
        native_strict=native is not None,
        semantic_available=semantic is not None,
        delivered_valid=delivered is not None,
        decision=("NATIVE_STRICT" if native is not None else
                  "NORMALIZED_WRAPPER" if semantic is not None else "REJECTED"),
        delivered_json=delivered,
        raw_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        delivered_sha256=(hashlib.sha256(delivered.encode("utf-8")).hexdigest()
                          if delivered is not None else None),
    )
