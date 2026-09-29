"""Typed views of the existing product HTTP responses for console code generation.

These models describe the API's current JSON shape. They do not calculate or
change readiness, onboard tasks, or alter the delivery contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .models import StrictProductModel, UnscoredObservation


class ReadinessDimensions(StrictProductModel):
    accessibility: float
    completeness: float
    redundancy: float
    timeliness: float
    safety: float


class AccessibilityCounts(StrictProductModel):
    total_files: int
    parsed_files: int
    ocr_required_files: int
    accessible_files: int


class CompletenessCounts(StrictProductModel):
    eligible_tables: int
    total_cells: int
    estimated_missing_cells: float


class RedundancyCounts(StrictProductModel):
    total_files: int
    exact_duplicate_groups: int
    redundant_files: int


class TimelinessCounts(StrictProductModel):
    files_with_valid_modified_at: int
    non_stale_files: int
    stale_files: int
    future_timestamp_files: int
    missing_timestamp_files: int
    invalid_timestamp_files: int


class SafetyCounts(StrictProductModel):
    total_files: int
    pii_affected_files: int
    files_without_detected_pii: int


class ReadinessCounts(StrictProductModel):
    accessibility: AccessibilityCounts
    completeness: CompletenessCounts
    redundancy: RedundancyCounts
    timeliness: TimelinessCounts
    safety: SafetyCounts


class ReadinessFlags(StrictProductModel):
    empty_file_set: bool
    completeness_not_applicable: bool
    no_valid_modified_at: bool
    missing_modified_at_count: int
    invalid_modified_at_count: int
    future_modified_at_count: int
    unknown_ocr_file_id_count: int
    unknown_pii_file_id_count: int
    scan_metadata_file_count_mismatch: bool


class ReadinessScore(StrictProductModel):
    schema_version: Literal["ax-readiness-score-v1"]
    readiness_score: float
    dimensions: ReadinessDimensions
    dimension_weights: ReadinessDimensions
    counts: ReadinessCounts
    as_of_date: str
    stale_threshold_days: int
    flags: ReadinessFlags


class ReadinessResponse(StrictProductModel):
    dataset: str
    dataset_name: str
    readiness: ReadinessScore
    unscored_observations: list[UnscoredObservation]


class DatasetOption(StrictProductModel):
    profile: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    dataset_name: str = Field(min_length=1)
    display_label: str = Field(min_length=1)
    origin: Literal["BUNDLED", "LOCAL"] = "BUNDLED"
    scanned_at: str | None = None
    source_root_name: str | None = None
    project_id: str | None = None


class DatasetsResponse(StrictProductModel):
    schema_version: Literal["ax-datasets-response-v1"] = "ax-datasets-response-v1"
    datasets: list[DatasetOption]


class FeaturedRunReference(StrictProductModel):
    phase: Literal["BEFORE", "AFTER"]
    label: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    result: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    action_label: str = Field(min_length=1)
    target: Literal["summary", "evidence"]


class FrozenPocGate(StrictProductModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    label: str = Field(min_length=1)
    status: Literal["PASS", "WARN", "BLOCK"]
    detail: str = Field(min_length=1)


class FrozenPocWalkthrough(StrictProductModel):
    schema_version: Literal["ax-frozen-poc-walkthrough-v1"] = (
        "ax-frozen-poc-walkthrough-v1"
    )
    label: Literal["검증된 동결 예시"] = "검증된 동결 예시"
    read_only: Literal[True] = True
    snapshot_id: Literal["phase6-v4"] = "phase6-v4"
    recommendation: Literal["GO", "CONDITIONAL_GO", "NO_GO"]
    recommendation_note: str = Field(min_length=1)
    approved_task_id: str = Field(min_length=1)
    approved_task_question: str = Field(min_length=1)
    approval_scope: Literal["CONTROLLED_DEMO"] = "CONTROLLED_DEMO"
    successful_runs: int = Field(ge=0)
    direct_evidence_runs: int = Field(ge=0)
    direct_evidence_ratio: float = Field(ge=0, le=1)
    cited_source_ids: list[str]
    model: str = Field(min_length=1)
    failure_recovery: str = Field(min_length=1)
    model_boundary: str = Field(min_length=1)
    cost_control: str = Field(min_length=1)
    audit_retention: str = Field(min_length=1)
    gates: list[FrozenPocGate]
    final_report_note: str = Field(min_length=1)


class FeaturedCase(StrictProductModel):
    case_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    question: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    before: FeaturedRunReference
    after: FeaturedRunReference
    walkthrough: FrozenPocWalkthrough | None = None

    @model_validator(mode="after")
    def validate_before_after(self) -> "FeaturedCase":
        if self.before.phase != "BEFORE" or self.after.phase != "AFTER":
            raise ValueError("featured case requires BEFORE and AFTER references")
        if self.before.run_id == self.after.run_id:
            raise ValueError("featured case references must use distinct runs")
        return self


class FeaturedCasesResponse(StrictProductModel):
    schema_version: Literal["ax-featured-cases-response-v1"] = (
        "ax-featured-cases-response-v1"
    )
    featured_cases: list[FeaturedCase]


class BusinessTaskCandidate(StrictProductModel):
    task_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    question: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: Literal["CANDIDATE"] = "CANDIDATE"


class BusinessTaskCatalog(StrictProductModel):
    schema_version: Literal["ax-business-task-catalog-v1"]
    tasks: list[BusinessTaskCandidate]


class BusinessTaskApprovalSummary(StrictProductModel):
    approval_id: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    success_criteria: list[str] = Field(min_length=1)
    approval_scope: Literal["CUSTOMER", "CONTROLLED_DEMO"]
    approved_by_role: str = Field(min_length=1)
    approved_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class BusinessTaskView(StrictProductModel):
    task_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    question: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: Literal["CANDIDATE", "VERIFIED"]
    approval: BusinessTaskApprovalSummary | None = None

    @model_validator(mode="after")
    def validate_approval_status(self) -> "BusinessTaskView":
        if (self.status == "VERIFIED") != (self.approval is not None):
            raise ValueError("VERIFIED requires approval and CANDIDATE forbids it")
        return self


class TasksResponse(StrictProductModel):
    dataset: str
    catalog_status: Literal["CANDIDATES_AVAILABLE", "VERIFIED_TASKS_AVAILABLE"]
    tasks: list[BusinessTaskView] = Field(default_factory=list)
