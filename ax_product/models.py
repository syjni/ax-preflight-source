"""Pydantic source of truth for the AX product delivery contract."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


AnswerStatus = Literal["ANSWERED", "ABSTAINED"]
AnswerKind = Literal["EXACT_TEXT", "EMPTY_SET", "ID_LIST", "NUMERIC_QUANTITY"]
AbstentionReason = Literal[
    "NOT_FOUND", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"
]
RejectReason = Literal[
    "NO_SUBMISSION", "INVALID_SUBMISSION", "INVALID_RUN", "MODEL_FALLBACK",
    "FORBIDDEN_TOOL", "RUNTIME_ERROR",
]
SourceLinkStatus = Literal["NOT_CHECKED", "LINKED", "PARTIAL", "UNLINKED"]


class StrictProductModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _nonblank(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be blank")


def _unique_nonblank_ids(ids: list[str], name: str) -> None:
    if any(not value.strip() or value != value.strip() for value in ids):
        raise ValueError(f"{name} must contain only nonblank, unpadded IDs")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{name} must not contain duplicate IDs")


class SubmitAnswerInput(StrictProductModel):
    """One authoritative final answer submitted by the product agent."""

    status: AnswerStatus
    answer: str | int | float | bool | list[str] | None = None
    answer_kind: AnswerKind | None = None
    unit: str | None = None
    explanation: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] = Field(default_factory=list)
    abstention_reason: AbstentionReason | None = None

    @model_validator(mode="after")
    def validate_relationships(self) -> "SubmitAnswerInput":
        _nonblank(self.explanation, "explanation")
        _unique_nonblank_ids(self.source_ids, "source_ids")
        if self.unit is not None:
            _nonblank(self.unit, "unit")
        if self.status == "ANSWERED":
            if self.answer is None:
                raise ValueError("ANSWERED requires answer")
            if self.abstention_reason is not None:
                raise ValueError("ANSWERED must not have abstention_reason")
            if not self.source_ids:
                raise ValueError("ANSWERED requires at least one source_id")
            if isinstance(self.answer, str):
                _nonblank(self.answer, "answer")
            elif isinstance(self.answer, list):
                if not self.answer and self.answer_kind != "EMPTY_SET":
                    raise ValueError("answer list must not be empty")
                _unique_nonblank_ids(self.answer, "answer list")
            elif isinstance(self.answer, float) and not math.isfinite(self.answer):
                raise ValueError("answer must be finite")
            if self.answer_kind == "EMPTY_SET":
                if self.answer != [] or self.unit is not None:
                    raise ValueError("EMPTY_SET requires answer=[] and unit=null")
            elif self.answer_kind == "ID_LIST":
                if not isinstance(self.answer, list) or not self.answer or self.unit is not None:
                    raise ValueError("ID_LIST requires a non-empty answer list and unit=null")
            elif self.answer_kind == "NUMERIC_QUANTITY":
                if isinstance(self.answer, bool) or not isinstance(self.answer, (int, float)):
                    raise ValueError("NUMERIC_QUANTITY requires a JSON number")
                if self.unit is None:
                    raise ValueError("NUMERIC_QUANTITY requires unit")
            elif self.answer_kind == "EXACT_TEXT":
                if not isinstance(self.answer, str) or self.unit is not None:
                    raise ValueError("EXACT_TEXT requires a string answer and unit=null")
        else:
            if self.answer is not None or self.unit is not None:
                raise ValueError("ABSTAINED requires answer=null and unit=null")
            if self.answer_kind is not None:
                raise ValueError("ABSTAINED requires answer_kind=null")
            if self.abstention_reason is None:
                raise ValueError("ABSTAINED requires abstention_reason")
            if self.abstention_reason in (
                "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"
            ) and not self.source_ids:
                raise ValueError(f"{self.abstention_reason} requires a source_id")
        return self


class DeliveryEnvelope(StrictProductModel):
    """Gate result consumed by product clients; no raw model prose is included."""

    delivery_status: Literal["DELIVERED", "REJECTED"]
    run_id: str = Field(min_length=1)
    dataset: str = Field(default="UNKNOWN", min_length=1)
    task_id: str | None = None
    payload: SubmitAnswerInput | None = None
    reject_reason: RejectReason | None = None
    model: str = Field(min_length=1)
    source_link_status: SourceLinkStatus | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "DeliveryEnvelope":
        _nonblank(self.run_id, "run_id")
        _nonblank(self.dataset, "dataset")
        _nonblank(self.model, "model")
        if self.task_id is not None:
            _nonblank(self.task_id, "task_id")
        if self.delivery_status == "DELIVERED":
            if self.payload is None or self.reject_reason is not None:
                raise ValueError("DELIVERED requires payload and no reject_reason")
            if self.source_link_status is None:
                raise ValueError("DELIVERED requires source_link_status")
        elif self.payload is not None or self.reject_reason is None or self.source_link_status is not None:
            raise ValueError("REJECTED requires reject_reason, no payload, and no source_link_status")
        return self


class UnscoredObservation(StrictProductModel):
    """Static observation outside the frozen readiness score dimensions."""

    code: str = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]*$", examples=["PROBABLE_VERSION_GROUP"])
    severity: Literal["info", "warning", "error"]
    message: str = Field(min_length=1)
    file_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_observation(self) -> "UnscoredObservation":
        _nonblank(self.message, "message")
        _unique_nonblank_ids(self.file_ids, "file_ids")
        return self
