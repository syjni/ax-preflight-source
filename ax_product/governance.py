"""Project-scoped retention inventory and explicit deletion contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .models import StrictProductModel


class ProjectPurgeRequest(StrictProductModel):
    confirmation: str = Field(min_length=1, max_length=80)

    @field_validator("confirmation")
    @classmethod
    def trim_confirmation(cls, value: str) -> str:
        return value.strip()


class ProjectRetentionPolicyUpdate(StrictProductModel):
    managed_data_days: int = Field(default=90, ge=1, le=3650)
    audit_event_days: int = Field(default=365, ge=30, le=3650)
    legal_hold: bool = False


class ProjectRetentionPolicyView(ProjectRetentionPolicyUpdate):
    schema_version: Literal["ax-project-retention-policy-v1"] = (
        "ax-project-retention-policy-v1"
    )
    project_id: str
    mode: Literal["OWNER_REVIEW"] = "OWNER_REVIEW"
    automatic_deletion_enabled: Literal[False] = False
    next_review_at: datetime
    updated_by: str | None = None
    updated_at: datetime | None = None


class ProjectAuditEvent(StrictProductModel):
    event_id: str
    sequence: int = Field(ge=1)
    at: datetime
    event: str
    actor_user_id: str | None = None
    target: str | None = None
    integrity_verified: bool


class ProjectAuditLog(StrictProductModel):
    schema_version: Literal["ax-project-audit-log-v1"] = "ax-project-audit-log-v1"
    project_id: str
    ledger_status: Literal[
        "VERIFIED", "LEGACY_SEALED", "LEGACY_UNSEALED", "INVALID"
    ]
    event_count: int = Field(ge=0)
    returned_event_count: int = Field(ge=0)
    retention_policy: ProjectRetentionPolicyView
    events: list[ProjectAuditEvent]


class ProjectDataInventory(StrictProductModel):
    schema_version: Literal["ax-project-data-inventory-v1"] = (
        "ax-project-data-inventory-v1"
    )
    project_id: str
    retention_mode: Literal["MANUAL_DELETE"] = "MANUAL_DELETE"
    automatic_expiry_enabled: Literal[False] = False
    local_dataset_count: int = Field(ge=0)
    managed_copy_count: int = Field(ge=0)
    business_task_count: int = Field(ge=0)
    writable_run_count: int = Field(ge=0)
    running_run_count: int = Field(ge=0)
    batch_count: int = Field(ge=0)
    active_batch_count: int = Field(ge=0)
    project_membership_count: int = Field(ge=1)
    execution_policy_count: int = Field(ge=0)
    transfer_approval_count: int = Field(ge=0)
    execution_usage_count: int = Field(ge=0)
    poc_decision_count: int = Field(ge=0)
    audit_event_count: int = Field(ge=0)
    retention_policy: ProjectRetentionPolicyView
    source_files_will_be_deleted: Literal[False] = False


class ProjectPurgeResult(StrictProductModel):
    schema_version: Literal["ax-project-purge-result-v1"] = (
        "ax-project-purge-result-v1"
    )
    project_id: str
    project_name: str
    purge_receipt_id: str
    completed_at: datetime
    verification_status: Literal["VERIFIED"] = "VERIFIED"
    project_deleted: Literal[True] = True
    local_datasets_deleted: int = Field(ge=0)
    managed_copies_deleted: int = Field(ge=0)
    business_tasks_deleted: int = Field(ge=0)
    writable_runs_deleted: int = Field(ge=0)
    batches_deleted: int = Field(ge=0)
    project_memberships_deleted: int = Field(ge=1)
    execution_policies_deleted: int = Field(ge=0)
    transfer_approvals_deleted: int = Field(ge=0)
    execution_usage_records_deleted: int = Field(ge=0)
    poc_decisions_deleted: int = Field(ge=0)
    audit_events_deleted: int = Field(ge=0)
    raw_project_identifier_retained: Literal[False] = False
    source_files_deleted: Literal[False] = False
