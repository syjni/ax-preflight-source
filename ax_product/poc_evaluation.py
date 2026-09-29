"""Project-scoped PoC evaluation and accountable approval contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .models import StrictProductModel


PocRecommendation = Literal["GO", "CONDITIONAL_GO", "NO_GO"]


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
    stable_tasks: int = Field(ge=0)
    open_findings: int = Field(ge=0)


class PocEvaluationGate(StrictProductModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    label: str
    status: Literal["PASS", "WARN", "BLOCK"]
    detail: str


class PocEvaluationReport(StrictProductModel):
    schema_version: Literal["ax-poc-evaluation-v1"] = "ax-poc-evaluation-v1"
    project_id: str
    project_name: str
    dataset_profile: str
    dataset_name: str
    generated_at: datetime
    assessment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: PocEvaluationMetrics
    gates: list[PocEvaluationGate]
    recommendation: PocRecommendation
    decision: PocDecisionView | None = None
    decision_current: bool = False
    decision_expired: bool = False
    scope_note: str = (
        "이 평가는 현재 저장된 정적 점검·승인 업무·관측 실행·근거 검사와 운영 통제를 "
        "요약하며 법률·보안 인증이나 업무 정답률을 대신하지 않습니다."
    )
