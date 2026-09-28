"""Verified representative journeys exposed by both live and static consoles."""

from __future__ import annotations

from .console_contracts import FeaturedCase, FeaturedCasesResponse, FeaturedRunReference
from .evidence import EvidenceCheckLookup
from .results import CompositeResultStore, RunInProgressError


RETURN_POLICY_REMEDIATION = FeaturedCase(
    case_id="return-policy-remediation",
    title="반품 기간 충돌 해결",
    question="현재 반품 가능 기간은 며칠인가요?",
    summary=(
        "14일·30일 충돌을 확인하고 FAQ를 정리한 뒤, 같은 업무가 3회 모두 "
        "30일로 답한 검증 사례입니다."
    ),
    before=FeaturedRunReference(
        phase="BEFORE",
        label="정리 전",
        dataset="portfolio-hidden-conflict-before",
        run_id=(
            "phase6v4-portfolio-hidden-conflict-before-"
            "task_policy_return_window-r1"
        ),
        result="0 / 3 답변",
        detail="근거 충돌로 3회 모두 보류",
        action_label="보류 근거 보기",
        target="summary",
    ),
    after=FeaturedRunReference(
        phase="AFTER",
        label="정리 후",
        dataset="portfolio-ceiling-after",
        run_id="phase6v4-portfolio-ceiling-after-task_policy_return_window-r1",
        result="3 / 3 답변",
        detail="30일 · 근거 직접 일치",
        action_label="30일 근거 확인",
        target="evidence",
    ),
)


def verified_featured_cases(
    store: CompositeResultStore,
    evidence_lookup: EvidenceCheckLookup,
) -> FeaturedCasesResponse:
    """Return promoted cases only while their exact stored facts still hold."""
    case = RETURN_POLICY_REMEDIATION
    try:
        before = store.read(case.before.run_id)
        after = store.read(case.after.run_id)
        before_evidence = evidence_lookup.read(case.before.run_id)
        after_evidence = evidence_lookup.read(case.after.run_id)
    except (FileNotFoundError, RunInProgressError, ValueError):
        return FeaturedCasesResponse(featured_cases=[])

    if (
        before.dataset != case.before.dataset
        or after.dataset != case.after.dataset
        or before.task_id != "TASK_POLICY_RETURN_WINDOW"
        or after.task_id != "TASK_POLICY_RETURN_WINDOW"
        or before.payload is None
        or after.payload is None
        or before.payload.status != "ABSTAINED"
        or before.payload.abstention_reason != "CONFLICTING_EVIDENCE"
        or after.payload.status != "ANSWERED"
        or after.payload.answer != "30일"
        or before_evidence.run_id != case.before.run_id
        or after_evidence.run_id != case.after.run_id
        or after_evidence.verdict != "DIRECT_MATCH"
    ):
        return FeaturedCasesResponse(featured_cases=[])

    return FeaturedCasesResponse(featured_cases=[case])
