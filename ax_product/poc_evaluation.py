"""Project-scoped PoC evaluation and accountable approval contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .models import StrictProductModel


PocRecommendation = Literal["GO", "CONDITIONAL_GO", "NO_GO"]
POC_EVALUATION_CRITERIA_VERSION = "AX_POC_GATES_V2"
POC_MIN_RUNS_PER_APPROVED_TASK = 3
POC_DIRECT_EVIDENCE_MIN_SAMPLE = 3
POC_DIRECT_EVIDENCE_MIN_RATIO = 0.8


class PocDecisionUpdate(StrictProductModel):
    decision: Literal["APPROVED", "CONDITIONAL", "REJECTED"]
    note: str = Field(min_length=5, max_length=2000)
    scope_acknowledged: Literal[True]
    risk_acknowledged: Literal[True]
    valid_days: int = Field(default=30, ge=1, le=365)

    @field_validator("note")
    @classmethod
    def trim_note(cls, value: str) -> str:
        return value.strip()


class PocDecisionView(StrictProductModel):
    schema_version: Literal["ax-poc-decision-v1"] = "ax-poc-decision-v1"
    decision_id: str
    project_id: str
    dataset_profile: str
    decision: Literal["APPROVED", "CONDITIONAL", "REJECTED"]
    note: str
    assessment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    decided_by: str
    decided_at: datetime
    expires_at: datetime


class PocEvaluationMetrics(StrictProductModel):
    readiness_score: float = Field(ge=0, le=100)
    onboarding_status: Literal["READY", "REVIEW_REQUIRED", "BLOCKED"]
    registered_tasks: int = Field(ge=0)
    approved_tasks: int = Field(ge=0)
    observed_runs: int = Field(ge=0)
    answered_runs: int = Field(ge=0)
    abstained_runs: int = Field(ge=0)
    rejected_runs: int = Field(ge=0)
    direct_evidence_runs: int = Field(ge=0)
    direct_evidence_ratio: float = Field(ge=0, le=1)
    repeated_tasks: int = Field(ge=0)
    stable_tasks: int = Field(ge=0)
    open_findings: int = Field(ge=0)


class PocEvaluationGate(StrictProductModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    label: str
    status: Literal["PASS", "WARN", "BLOCK"]
    detail: str
    decision_relevant: bool = True
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    excluded: int | None = Field(default=None, ge=0)
    minimum_sample: int | None = Field(default=None, ge=1)
    minimum_ratio: float | None = Field(default=None, ge=0, le=1)


class PocEvaluationRunPopulation(StrictProductModel):
    total_final_runs: int = Field(ge=0)
    included_runs: int = Field(ge=0)
    included_answered_runs: int = Field(ge=0)
    included_abstained_runs: int = Field(ge=0)
    excluded_rejected_runs: int = Field(ge=0)
    excluded_runtime_failure_runs: int = Field(ge=0)
    excluded_non_verified_request_runs: int = Field(ge=0)
    excluded_unapproved_task_runs: int = Field(ge=0)
    excluded_missing_context_runs: int = Field(ge=0)


class PocEvaluationTaskSample(StrictProductModel):
    task_id: str = Field(min_length=1)
    task_label: str = Field(min_length=1)
    included_runs: int = Field(ge=0)
    minimum_runs: int = Field(ge=1)
    sample_complete: bool


class PocEvaluationReport(StrictProductModel):
    schema_version: Literal["ax-poc-evaluation-v1"] = "ax-poc-evaluation-v1"
    project_id: str
    project_name: str
    dataset_profile: str
    dataset_name: str
    generated_at: datetime
    assessment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    criteria_version: Literal["AX_POC_GATES_V2"] = POC_EVALUATION_CRITERIA_VERSION
    diagnostics_version: Literal["v2"] = "v2"
    metrics: PocEvaluationMetrics
    run_population: PocEvaluationRunPopulation
    task_samples: list[PocEvaluationTaskSample]
    gates: list[PocEvaluationGate]
    recommendation: PocRecommendation
    decision: PocDecisionView | None = None
    decision_current: bool = False
    decision_expired: bool = False
    scope_note: str = (
        "이 평가는 현재 저장된 정적 점검·승인 업무·관측 실행·근거 검사와 운영 통제를 "
        "요약하며 법률·보안 인증이나 업무 정답률을 대신하지 않습니다."
    )
