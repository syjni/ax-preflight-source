"""Shared request contract for every AX product runner implementation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .models import StrictProductModel


RUNNABLE_REQUEST_TYPES = frozenset({
    "AD_HOC_QUESTION", "TASK_CANDIDATE", "VERIFIED_BUSINESS_TASK",
})


class ResolvedRunRequest(StrictProductModel):
    """Internal request whose reviewed task ID has been resolved to a question."""

    dataset: str = Field(min_length=1)
    request_type: Literal[
        "VERIFIED_BUSINESS_TASK", "TASK_CANDIDATE", "AD_HOC_QUESTION"
    ]
    task_id: str | None = None
    question: str = Field(min_length=1)
    model: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identity(self) -> "ResolvedRunRequest":
        for name in ("dataset", "question", "model"):
            value = getattr(self, name)
            if value != value.strip():
                raise ValueError(f"{name} must be unpadded")
        if self.request_type == "AD_HOC_QUESTION":
            if self.task_id is not None:
                raise ValueError("AD_HOC_QUESTION forbids task_id")
        elif self.task_id is None or not self.task_id.strip():
            raise ValueError(f"{self.request_type} requires a nonblank task_id")
        return self


def validate_runner_request(request: Any) -> str:
    """Validate a request accepted by both fake and external product runners.

    The API owns catalog onboarding and candidate identity checks.  This shared
    boundary prevents an individual runner from silently supporting a narrower
    set of otherwise valid API requests.
    """
    request_type = getattr(request, "request_type", None)
    question = getattr(request, "question", None)
    task_id = getattr(request, "task_id", None)
    if request_type not in RUNNABLE_REQUEST_TYPES:
        raise ValueError("unsupported product runner request_type")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("runnable product requests require a nonblank question")
    if request_type in {"TASK_CANDIDATE", "VERIFIED_BUSINESS_TASK"}:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(f"{request_type} requests require a nonblank task_id")
    elif task_id is not None:
        raise ValueError("AD_HOC_QUESTION requests forbid task_id")
    return question
