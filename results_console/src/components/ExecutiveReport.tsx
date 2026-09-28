import type { FindingsResponse, ReadinessResponse } from '../generated/api';

const currentReturnFaqExcerpt = '반품 가능 여부는 구매일, 상품 상태, 영수증 보유 여부를 함께 확인한다.';

function metric(response: FindingsResponse | null) {
  const value = response?.diagnostics;
  return value
    ? `${value.processable_task_count} / ${value.task_count}`
    : '—';
}

export function ExecutiveReport({
  dataset,
  readiness,
  findings,
  comparison,
}: {
  dataset: string;
  readiness: ReadinessResponse | null;
  findings: FindingsResponse | null;
  comparison: FindingsResponse | null;
}) {
  const active = (findings?.findings ?? [])
    .filter((item) => item.comparison_status !== 'NOT_REPRODUCED_AFTER')
    .sort((left, right) => {
      const order = { DATA_SIGNAL: 0, RETRIEVAL_LIMITATION: 1, CAUSE_UNCONFIRMED: 2 } as const;
      const attributionOrder = order[left.attribution_status ?? 'DATA_SIGNAL']
        - order[right.attribution_status ?? 'DATA_SIGNAL'];
      return attributionOrder || right.affected_task_count - left.affected_task_count;
    });
  const visible = active.slice(0, 5);
  const returnFinding = [...(findings?.findings ?? []), ...(comparison?.findings ?? [])]
    .find((item) => item.finding_type === 'CONFLICTING_SOURCES' && item.comparison);
  const returnComparison = returnFinding?.comparison;
  const beforeFaqEvidence = returnFinding?.evidence.find((item) => item.source_title?.includes('FAQ_2026'));
  const policyEvidence = returnFinding?.evidence.find((item) => !item.source_title?.includes('FAQ_2026'));
  const score = readiness?.readiness.readiness_score;

  return <section className="executive-report" id="executive-report" aria-labelledby="executive-report-title">
    <div className="executive-report__actions no-print">
      <span>관리자 공유용 1페이지</span>
      <button type="button" onClick={() => window.print()}>PDF로 저장 / 인쇄</button>
    </div>
    <header className="executive-report__header">
      <div><small>AX Preflight · AI 업무 도입 전 점검</small><h2 id="executive-report-title">어디를 먼저 검토하면 업무가 풀리는가</h2></div>
      <div><span>데이터셋</span><strong>{(readiness?.dataset_name ?? dataset) || '조회 전'}</strong></div>
    </header>
    <div className="executive-report__metrics">
      <article><span>반복 안정 처리</span><strong>{metric(findings)}</strong><small>3회 모두 같은 의미값</small></article>
      <article><span>일관된 보류</span><strong>{findings?.diagnostics.blocked_task_count ?? '—'}</strong><small>3회 모두 보류</small></article>
      <article><span>불안정·검토 필요</span><strong>{findings?.diagnostics.inconclusive_task_count ?? '—'}</strong><small>답변·보류 혼재</small></article>
    </div>
    {returnComparison && <div className="executive-report__case" aria-label="반품 기간 개선 사례">
      <div className="executive-report__case-head"><div><span>검증된 수정 사례</span><strong>반품 가능 기간</strong></div><div><b>{returnComparison.before_observed_run_count - returnComparison.before_abstained_run_count} / {returnComparison.before_observed_run_count}</b><i>→</i><b>{returnComparison.after_answered_run_count} / {returnComparison.after_observed_run_count}</b></div></div>
      <div className="executive-report__quotes">
        {beforeFaqEvidence && <blockquote><span>정리 전 FAQ · Before 실행에서 인용</span><strong>{beforeFaqEvidence.source_title}</strong><p>{beforeFaqEvidence.excerpt ?? '원문 발췌 없음'}</p></blockquote>}
        <blockquote className="executive-report__quote--current"><span>정리 후 FAQ · 현재 원문</span><strong>FAQ_2026.txt</strong><p>{currentReturnFaqExcerpt}</p></blockquote>
        {policyEvidence && <blockquote><span>현행 정책 · 변경 없음</span><strong>{policyEvidence.source_title ?? '기준 자료'}</strong><p>{policyEvidence.excerpt ?? '원문 발췌 없음'}</p></blockquote>}
      </div>
      <small>정적 Readiness {score === undefined ? '—' : `${Math.round(score)} / 100`}만으로는 발견하지 못한 충돌입니다. 전체 Before/After 품질 향상 주장이 아니라, 변경 파일과 직접 연결되는 이 업무만 수정 효과로 설명합니다.</small>
    </div>}
    <div className="executive-report__fixes">
      <h3>우선 검토할 불안정·데이터 신호</h3>
      {visible.length === 0 && <p className="executive-report__empty">현재 관측 실행에서 열린 진단 신호가 없습니다.</p>}
      {visible.map((finding, index) => <article key={finding.finding_id}>
        <span className="mono">{String(index + 1).padStart(2, '0')}</span>
        <div><strong>{finding.affected_tasks.map((item) => item.label).join(', ')}</strong>
          {finding.attribution_status === 'CAUSE_UNCONFIRMED' && <small>데이터 원인 미확인</small>}
          {finding.attribution_status === 'RETRIEVAL_LIMITATION' && <small>검색·탐색 경로 한계 확인</small>}
          <p>{finding.recommended_action}</p></div>
        <div><strong>{finding.affected_task_count}</strong><small>재검증할 업무</small></div>
      </article>)}
      {active.length > visible.length && <p className="executive-report__more">추가 진단 신호 {active.length - visible.length}건은 상세 화면에서 확인하세요.</p>}
    </div>
    <footer><span>관측 실행 {findings?.diagnostics.observed_run_count ?? 0}회 · 의미 비교 규칙 {findings?.comparison_version ?? 'v1'}</span><span>불안정 신호는 원인 확인 후 조치하고, 동일 업무 재실행으로 효과를 확인합니다.</span></footer>
  </section>;
}
