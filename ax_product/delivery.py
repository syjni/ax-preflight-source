"""Run-local first-valid-submission state machine for product delivery."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal

from pydantic import ValidationError

from .models import DeliveryEnvelope, SubmitAnswerInput


@dataclass(frozen=True)
class SubmissionAttempt:
    accepted: bool
    error_code: Literal["VALIDATION_ERROR", "ALREADY_SUBMITTED"] | None = None
    validation_errors: tuple[tuple[str, str], ...] = ()


class SubmitAnswerSession:
    """One instance per run. Only a validated payload consumes the slot."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._accepted: SubmitAnswerInput | None = None
        self._invalid_attempt_seen = False

    @property
    def state(self) -> Literal["UNSUBMITTED", "ACCEPTED"]:
        with self._lock:
            return "ACCEPTED" if self._accepted is not None else "UNSUBMITTED"

    @property
    def accepted_payload(self) -> SubmitAnswerInput | None:
        with self._lock:
            return self._accepted.model_copy(deep=True) if self._accepted is not None else None

    def submit(self, arguments: Any) -> SubmissionAttempt:
        with self._lock:
            if self._accepted is not None:
                return SubmissionAttempt(accepted=False, error_code="ALREADY_SUBMITTED")
            try:
                # Revalidate even a model instance; callers cannot mutate accepted state later.
                if isinstance(arguments, SubmitAnswerInput):
                    arguments = arguments.model_dump(mode="python")
                payload = SubmitAnswerInput.model_validate(arguments, strict=True)
            except ValidationError as exc:
                self._invalid_attempt_seen = True
                errors = tuple(
                    (".".join(map(str, error["loc"])), error["msg"])
                    for error in exc.errors(
                        include_input=False, include_context=False, include_url=False
                    )
                )
                return SubmissionAttempt(
                    accepted=False, error_code="VALIDATION_ERROR", validation_errors=errors
                )
            self._accepted = payload.model_copy(deep=True)
            return SubmissionAttempt(accepted=True)

    def envelope(self, *, run_id: str, task_id: str | None, model: str) -> DeliveryEnvelope:
        with self._lock:
            payload = self._accepted.model_copy(deep=True) if self._accepted is not None else None
            invalid_attempt_seen = self._invalid_attempt_seen
        if payload is not None:
            return DeliveryEnvelope(
                delivery_status="DELIVERED", run_id=run_id, task_id=task_id,
                payload=payload, model=model, source_link_status="NOT_CHECKED",
            )
        return DeliveryEnvelope(
            delivery_status="REJECTED", run_id=run_id, task_id=task_id,
            reject_reason="INVALID_SUBMISSION" if invalid_attempt_seen else "NO_SUBMISSION",
            model=model,
        )
