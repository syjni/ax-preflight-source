"""Fail-closed approval records for dataset-scoped business tasks."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .console_contracts import BusinessTaskCatalog
from .models import StrictProductModel


ApprovalScope = Literal["CUSTOMER", "CONTROLLED_DEMO"]


def question_sha256(question: str) -> str:
    """Bind an approval to the exact reviewed catalog question."""
    return hashlib.sha256(question.encode("utf-8")).hexdigest()


class BusinessTaskApproval(StrictProductModel):
    approval_id: str = Field(min_length=1, pattern=r"^[A-Z0-9][A-Z0-9_-]*$")
    dataset_profile: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    success_criteria: list[str] = Field(min_length=1)
    approval_scope: ApprovalScope
    approved_by_role: str = Field(min_length=1)
    approved_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    question_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_text_and_criteria(self) -> "BusinessTaskApproval":
        text_fields = (
            "dataset_profile", "task_id", "owner_role", "approved_by_role"
        )
        for field_name in text_fields:
            value = getattr(self, field_name)
            if value != value.strip():
                raise ValueError(f"{field_name} must be unpadded")
        if any(not item.strip() or item != item.strip() for item in self.success_criteria):
            raise ValueError("success_criteria must contain only nonblank, unpadded text")
        if len(self.success_criteria) != len(set(self.success_criteria)):
            raise ValueError("success_criteria must not contain duplicates")
        try:
            parsed_date = date.fromisoformat(self.approved_at)
        except ValueError as exc:
            raise ValueError("approved_at must be a real ISO calendar date") from exc
        if parsed_date.isoformat() != self.approved_at:
            raise ValueError("approved_at must use YYYY-MM-DD")
        return self


class BusinessTaskApprovalRegistry(StrictProductModel):
    schema_version: Literal["ax-business-task-approvals-v1"]
    approvals: list[BusinessTaskApproval] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_uniqueness(self) -> "BusinessTaskApprovalRegistry":
        approval_ids = [item.approval_id for item in self.approvals]
        scopes = [
            (item.dataset_profile, item.task_id) for item in self.approvals
        ]
        if len(approval_ids) != len(set(approval_ids)):
            raise ValueError("approval_id must be unique")
        if len(scopes) != len(set(scopes)):
            raise ValueError("only one approval is allowed per dataset and task")
        return self

    def for_dataset(self, dataset_profile: str) -> dict[str, BusinessTaskApproval]:
        return {
            item.task_id: item
            for item in self.approvals
            if item.dataset_profile == dataset_profile
        }


def validate_approval_registry(
    registry: BusinessTaskApprovalRegistry,
    catalog: BusinessTaskCatalog,
) -> None:
    """Reject unknown or stale approvals before the API starts serving them."""
    catalog_by_id = {item.task_id: item for item in catalog.tasks}
    for approval in registry.approvals:
        task = catalog_by_id.get(approval.task_id)
        if task is None:
            raise ValueError(
                f"approval {approval.approval_id} references an unknown task"
            )
        if approval.question_sha256 != question_sha256(task.question):
            raise ValueError(
                f"approval {approval.approval_id} is stale for its catalog question"
            )
