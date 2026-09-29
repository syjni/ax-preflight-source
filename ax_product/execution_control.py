"""Project-scoped model boundary approval and bounded execution budgets."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .models import StrictProductModel


DATA_BOUNDARY_REVISION = "AX_DATA_BOUNDARY_V1"
ExecutionBlocker = Literal[
    "RUNNER_UNAVAILABLE",
    "RUNNER_EXECUTABLE_UNAVAILABLE",
    "EXECUTION_POLICY_REQUIRED",
    "DATASET_REQUIRED",
    "DATA_TRANSFER_APPROVAL_REQUIRED",
    "DATA_TRANSFER_APPROVAL_EXPIRED",
    "MODEL_NOT_APPROVED",
    "BATCH_RUN_LIMIT_EXCEEDED",
    "DAILY_RUN_LIMIT_REACHED",
    "DAILY_BUDGET_REACHED",
    "CONCURRENCY_LIMIT_REACHED",
]


class ExecutionPolicyUpdate(StrictProductModel):
    model: str = Field(default="claude-sonnet-5", min_length=1, max_length=120)
    daily_run_limit: int = Field(default=20, ge=1, le=500)
    max_batch_runs: int = Field(default=10, ge=1, le=50)
    max_concurrent_runs: int = Field(default=1, ge=1, le=5)
    estimated_cost_per_run_cents: int = Field(default=10, ge=1, le=100_000)
    daily_budget_cents: int = Field(default=200, ge=1, le=10_000_000)

    @model_validator(mode="after")
    def validate_budget(self) -> "ExecutionPolicyUpdate":
        self.model = self.model.strip()
        if not self.model:
            raise ValueError("model must not be blank")
        if self.daily_budget_cents < self.estimated_cost_per_run_cents:
            raise ValueError("daily budget must cover at least one estimated run")
        if self.max_batch_runs > self.daily_run_limit:
            raise ValueError("max batch runs must not exceed the daily run limit")
        return self


class ProjectExecutionPolicyView(ExecutionPolicyUpdate):
    schema_version: Literal["ax-project-execution-policy-v1"] = (
        "ax-project-execution-policy-v1"
    )
    project_id: str
    provider: Literal["KIRO_CLI"] = "KIRO_CLI"
    updated_by: str
    updated_at: datetime


class DataTransferApprovalRequest(StrictProductModel):
    dataset_profile: str = Field(min_length=1, max_length=160)
    model: str = Field(min_length=1, max_length=120)
    data_classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL"]
    tool_output_to_model_acknowledged: Literal[True]
    provider_policy_reviewed: Literal[True]
    sensitive_data_reviewed: Literal[True]
    valid_days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def trim_values(self) -> "DataTransferApprovalRequest":
        self.dataset_profile = self.dataset_profile.strip()
        self.model = self.model.strip()
        if not self.dataset_profile or not self.model:
            raise ValueError("dataset_profile and model must not be blank")
        return self


class DataTransferApprovalView(StrictProductModel):
    schema_version: Literal["ax-data-transfer-approval-v1"] = (
        "ax-data-transfer-approval-v1"
    )
    approval_id: str
    project_id: str
    dataset_profile: str
    provider: Literal["KIRO_CLI"] = "KIRO_CLI"
    model: str
    data_classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL"]
    boundary_revision: Literal["AX_DATA_BOUNDARY_V1"] = DATA_BOUNDARY_REVISION
    pii_affected_file_count: int = Field(ge=0)
    tool_output_to_model_acknowledged: Literal[True] = True
    provider_policy_reviewed: Literal[True] = True
    sensitive_data_reviewed: Literal[True] = True
    approved_by: str
    approved_at: datetime
    expires_at: datetime


class ModelConnectionStatus(StrictProductModel):
    schema_version: Literal["ax-model-connection-status-v1"] = (
        "ax-model-connection-status-v1"
    )
    runner_enabled: bool
    provider: Literal["KIRO_CLI", "CONFIGURED_RUNNER"]
    executable_status: Literal["AVAILABLE", "UNAVAILABLE", "NOT_CHECKED"]
    credential_status: Literal["ENVIRONMENT_MANAGED_NOT_PROBED"] = (
        "ENVIRONMENT_MANAGED_NOT_PROBED"
    )
    timeout_seconds: int | None = Field(default=None, ge=1)
    default_model: str = "claude-sonnet-5"


class ProjectExecutionUsage(StrictProductModel):
    schema_version: Literal["ax-project-execution-usage-v1"] = (
        "ax-project-execution-usage-v1"
    )
    window: Literal["ROLLING_24_HOURS"] = "ROLLING_24_HOURS"
    window_started_at: datetime
    reserved_runs: int = Field(ge=0)
    running_runs: int = Field(ge=0)
    estimated_spend_cents: int = Field(ge=0)
    remaining_run_capacity: int = Field(ge=0)
    remaining_budget_cents: int = Field(ge=0)


class ProjectExecutionControl(StrictProductModel):
    schema_version: Literal["ax-project-execution-control-v1"] = (
        "ax-project-execution-control-v1"
    )
    project_id: str
    dataset_profile: str | None = None
    connection: ModelConnectionStatus
    policy: ProjectExecutionPolicyView | None = None
    transfer_approval: DataTransferApprovalView | None = None
    usage: ProjectExecutionUsage | None = None
    can_execute: bool
    blockers: list[ExecutionBlocker] = Field(default_factory=list)
