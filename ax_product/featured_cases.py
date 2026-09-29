"""Verified representative journeys exposed by both live and static consoles."""

from __future__ import annotations

from .console_contracts import (
    FeaturedCase, FeaturedCasesResponse, FeaturedRunReference,
    FrozenPocGate, FrozenPocWalkthrough,
)
from .evidence import EvidenceCheckLookup
from .results import CompositeResultStore, RunInProgressError
from .task_approvals import BusinessTaskApprovalRegistry


RETURN_TASK_ID = "TASK_POLICY_RETURN_WINDOW"
RETURN_BEFORE_RUN_IDS = tuple(
    f"phase6v4-portfolio-hidden-conflict-before-task_policy_return_window-r{index}"
    for index in range(1, 4)
)
RETURN_AFTER_RUN_IDS = tuple(
    f"phase6v4-portfolio-ceiling-after-task_policy_return_window-r{index}"
    for index in range(1, 4)
)


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
    task_approvals: BusinessTaskApprovalRegistry,
) -> FeaturedCasesResponse:
    """Return promoted cases only while their exact stored facts still hold."""
    case = RETURN_POLICY_REMEDIATION
    try:
        before_runs = [store.read(run_id) for run_id in RETURN_BEFORE_RUN_IDS]
        after_runs = [store.read(run_id) for run_id in RETURN_AFTER_RUN_IDS]
        before_evidence = [
            evidence_lookup.read(run_id) for run_id in RETURN_BEFORE_RUN_IDS
        ]
        after_evidence = [
            evidence_lookup.read(run_id) for run_id in RETURN_AFTER_RUN_IDS
        ]
    except (FileNotFoundError, RunInProgressError, ValueError):
        return FeaturedCasesResponse(featured_cases=[])

    before = before_runs[0]
    after = after_runs[0]
    approval = task_approvals.for_dataset(case.after.dataset).get(RETURN_TASK_ID)
    if (
        before.dataset != case.before.dataset
        or after.dataset != case.after.dataset
        or approval is None
        or approval.approval_scope != "CONTROLLED_DEMO"
        or any(run.task_id != RETURN_TASK_ID for run in before_runs + after_runs)
        or any(
            run.dataset != case.before.dataset
            or run.payload is None
            or run.payload.status != "ABSTAINED"
            or run.payload.abstention_reason != "CONFLICTING_EVIDENCE"
            for run in before_runs
        )
        or any(
            run.dataset != case.after.dataset
            or run.payload is None
            or run.payload.status != "ANSWERED"
            or run.payload.answer != "30일"
            for run in after_runs
        )
        or any(
            evidence.run_id != run_id
            for evidence, run_id in zip(
                before_evidence + after_evidence,
                RETURN_BEFORE_RUN_IDS + RETURN_AFTER_RUN_IDS,
                strict=True,
            )
        )
        or any(evidence.verdict != "DIRECT_MATCH" for evidence in after_evidence)
    ):
        return FeaturedCasesResponse(featured_cases=[])

    cited_source_ids = sorted({
        source_id
        for run in after_runs
        for source_id in (run.payload.source_ids if run.payload else [])
    })
    models = {run.model for run in after_runs}
    if len(models) != 1 or not cited_source_ids:
        return FeaturedCasesResponse(featured_cases=[])
    successful_runs = len(after_runs)
    direct_evidence_runs = sum(
        evidence.verdict == "DIRECT_MATCH" for evidence in after_evidence
    )
    walkthrough = FrozenPocWalkthrough(
        recommendation="CONDITIONAL_GO",
        recommendation_note=(
            "승인 업무의 성공 실행과 직접 근거는 확인했지만, 동결 산출물에는 심사자 조직의 "
            "모델 전달 승인·비용 한도·감사 보존 판단이 없으므로 조건부입니다."
        ),
        approved_task_id=RETURN_TASK_ID,
        approved_task_question=case.question,
        successful_runs=successful_runs,
        direct_evidence_runs=direct_evidence_runs,
        direct_evidence_ratio=direct_evidence_runs / successful_runs,
        cited_source_ids=cited_source_ids,
        model=next(iter(models)),
        failure_recovery=(
            "정리 전에는 14일·30일 근거 충돌로 3회 모두 보류했고, FAQ의 충돌 문장을 "
            "정리한 뒤 같은 승인 업무가 3회 모두 30일로 답했습니다."
        ),
        model_boundary=(
            "표시 모델은 과거 동결 실행의 식별자입니다. 현재 조직의 자격 증명이나 "
            "자료 전달 승인을 의미하지 않습니다."
        ),
        cost_control=(
            "동결 실행에는 조직별 실행 한도와 비용 승인 원장이 포함되지 않습니다. "
            "실제 도입 전 프로젝트 정책에서 별도로 설정해야 합니다."
        ),
        audit_retention=(
            "frozen v4 산출물과 manifest 무결성은 시작 시 검증됩니다. 조직별 감사 원장, "
            "보존 기간과 법적 보존 판단은 실제 프로젝트에서 별도로 기록해야 합니다."
        ),
        gates=[
            FrozenPocGate(
                code="EXECUTION_SAMPLE", label="승인 업무 성공 실행",
                status="PASS", detail="승인된 반품 업무의 성공 최종 실행 3/3회",
            ),
            FrozenPocGate(
                code="DIRECT_EVIDENCE", label="직접 근거 연결",
                status="PASS", detail="DIRECT_MATCH 3/3회 · 100%",
            ),
            FrozenPocGate(
                code="MODEL_BOUNDARY", label="모델·데이터 전달 승인",
                status="WARN", detail="과거 실행 모델만 확인 · 조직별 전달 승인 필요",
            ),
            FrozenPocGate(
                code="COST_CONTROL", label="비용·실행 통제",
                status="WARN", detail="동결 산출물에 조직별 비용 정책 없음",
            ),
            FrozenPocGate(
                code="AUDIT_RETENTION", label="감사·보존 상태",
                status="WARN", detail="산출물 무결성 검증 · 조직별 감사·보존 정책 필요",
            ),
        ],
        final_report_note=(
            "검증된 실행 사례는 조건부 진행 근거이며, 심사자 조직의 책임자 승인이나 "
            "법률·보안 인증을 대신하지 않습니다."
        ),
    )
    return FeaturedCasesResponse(
        featured_cases=[case.model_copy(update={"walkthrough": walkthrough})]
    )
