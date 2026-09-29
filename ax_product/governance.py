"""Project-scoped retention inventory and explicit deletion contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .models import StrictProductModel


class ProjectPurgeRequest(StrictProductModel):
    confirmation: str = Field(min_length=1, max_length=80)
    operation_id: str | None = Field(
        default=None, pattern=r"^del_[a-f0-9]{32}$"
    )

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
    checkpoint_sequence: int = Field(default=0, ge=0)
    protection_mode: Literal[
        "CHAIN_AND_CHECKPOINT_NO_EXTERNAL_AUTHORITY",
        "HMAC_CHAIN_AND_CHECKPOINT",
    ] = "CHAIN_AND_CHECKPOINT_NO_EXTERNAL_AUTHORITY"
    immutable_storage: Literal[False] = False
    repair_required: bool = False
    operator_guidance: str = (
        "python -m ax_product.audit_ledger inspect --root <access-root>"
    )
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
    operation_id: str = Field(pattern=r"^del_[a-f0-9]{32}$")
    deletion_status: Literal["PARTIAL_FAILURE", "COMPLETED"]
    completed_stages: list[str]
    remaining_stages: list[str]
    remaining_records: list[str]
    attempt_count: int = Field(ge=1)
    failure_code: str | None = None
    failure_detail: str | None = None
    completed_at: datetime | None = None
    verification_status: Literal["PARTIAL", "VERIFIED"]
    project_deleted: bool
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
    raw_project_identifier_retained: Literal[True] = True
    audit_tombstone_retained: Literal[True] = True
    source_files_deleted: Literal[False] = False


class DeletionOperationView(StrictProductModel):
    schema_version: Literal["ax-deletion-operation-v1"] = (
        "ax-deletion-operation-v1"
    )
    operation_id: str = Field(pattern=r"^del_[a-f0-9]{32}$")
    scope: Literal["PROJECT", "DATASET"]
    project_id: str | None = None
    dataset_profile: str | None = None
    deletion_status: Literal["PARTIAL_FAILURE", "COMPLETED"]
    completed_stages: list[str]
    remaining_stages: list[str]
    remaining_records: list[str]
    attempt_count: int = Field(ge=1)
    failure_code: str | None = None
    failure_detail: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    source_files_deleted: Literal[False] = False
