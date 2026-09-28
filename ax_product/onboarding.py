"""Deterministic preflight checks for a configured runtime dataset."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ax_mcp.runtime_dataset import (
    RuntimeDataset,
    RuntimeDatasetError,
    runtime_identity,
    validate_runtime_resource_leakage,
)

from .console_contracts import BusinessTaskCatalog
from .models import StrictProductModel
from .task_approvals import BusinessTaskApprovalRegistry


class OnboardingCheck(StrictProductModel):
    code: Literal[
        "DATASET_INTEGRITY",
        "PARSE_COVERAGE",
        "RETRIEVAL_SURFACE",
        "RUNTIME_RESOURCE_LEAKAGE",
        "BUSINESS_TASK_REVIEW",
    ]
    status: Literal["PASS", "WARN", "BLOCK"]
    observed: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)


class OnboardingAssessment(StrictProductModel):
    schema_version: Literal["ax-onboarding-assessment-v1"] = (
        "ax-onboarding-assessment-v1"
    )
    dataset: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    status: Literal["READY", "REVIEW_REQUIRED", "BLOCKED"]
    can_run: bool
    blocker_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    checks: list[OnboardingCheck]


def _status(checks: list[OnboardingCheck]) -> tuple[str, bool, int, int]:
    blocker_count = sum(check.status == "BLOCK" for check in checks)
    warning_count = sum(check.status == "WARN" for check in checks)
    if blocker_count:
        return "BLOCKED", False, blocker_count, warning_count
    if warning_count:
        return "REVIEW_REQUIRED", True, 0, warning_count
    return "READY", True, 0, 0


def assess_onboarding(
    dataset: RuntimeDataset,
    task_catalog: BusinessTaskCatalog,
    task_approvals: BusinessTaskApprovalRegistry | None = None,
) -> OnboardingAssessment:
    """Assess only observable runtime inputs; never infer customer approval."""
    checks: list[OnboardingCheck] = []
    identity: dict | None = None
    try:
        identity = runtime_identity(dataset)
        checks.append(OnboardingCheck(
            code="DATASET_INTEGRITY",
            status="PASS",
            observed=identity["file_count"],
            total=identity["file_count"],
        ))
    except (RuntimeDatasetError, OSError, ValueError):
        checks.append(OnboardingCheck(
            code="DATASET_INTEGRITY",
            status="BLOCK",
        ))

    if identity is not None:
        file_count = identity["file_count"]
        parsed_count = identity["parsed_file_count"]
        parse_status = (
            "BLOCK" if parsed_count == 0
            else "WARN" if parsed_count < file_count
            else "PASS"
        )
        checks.append(OnboardingCheck(
            code="PARSE_COVERAGE",
            status=parse_status,
            observed=parsed_count,
            total=file_count,
        ))
        retrieval_count = (
            identity["search_index_document_count"] + identity["table_count"]
        )
        checks.append(OnboardingCheck(
            code="RETRIEVAL_SURFACE",
            status="PASS" if retrieval_count else "BLOCK",
            observed=retrieval_count,
        ))

    try:
        leakage = validate_runtime_resource_leakage(dataset)
        checks.append(OnboardingCheck(
            code="RUNTIME_RESOURCE_LEAKAGE",
            status="PASS" if leakage["passed"] else "BLOCK",
            observed=len(leakage["violations"]),
            total=leakage["runtime_resource_count"],
        ))
    except (OSError, ValueError):
        checks.append(OnboardingCheck(
            code="RUNTIME_RESOURCE_LEAKAGE",
            status="BLOCK",
        ))

    candidate_count = len(task_catalog.tasks)
    verified_count = (
        0 if task_approvals is None
        else len(task_approvals.for_dataset(dataset.profile))
    )
    checks.append(OnboardingCheck(
        code="BUSINESS_TASK_REVIEW",
        status=(
            "PASS"
            if candidate_count > 0 and verified_count == candidate_count
            else "WARN"
        ),
        observed=verified_count,
        total=candidate_count,
    ))

    status, can_run, blocker_count, warning_count = _status(checks)
    return OnboardingAssessment(
        dataset=dataset.profile,
        dataset_name=dataset.dataset_name,
        status=status,
        can_run=can_run,
        blocker_count=blocker_count,
        warning_count=warning_count,
        checks=checks,
    )
