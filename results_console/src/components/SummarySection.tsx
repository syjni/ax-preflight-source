import type { FindingsResponse, ReadinessResponse } from '../generated/api';
import type { RunResult } from '../api';
import { runState } from '../api';
import { Status } from './Status';

function formatAnswer(answer: string | number | boolean | string[] | null | undefined, unit: string | null | undefined): string {
  const value = Array.isArray(answer) ? answer.join(', ') : String(answer ?? '—');
  if (!unit) return value;
  const compactValue = value.replace(/\s/g, '').toLocaleLowerCase();
  const compactUnit = unit.replace(/\s/g, '').toLocaleLowerCase();
  if (compactUnit === 'date') return value;
  return compactValue.endsWith(compactUnit) ? value : `${value} ${unit}`;
}

function abstentionReason(reason: string | null | undefined): string {
  if (reason === 'NOT_FOUND') return '필요한 자료를 찾지 못해 보류';
  if (reason === 'INSUFFICIENT_EVIDENCE') return '근거가 부족해 보류';
  if (reason === 'CONFLICTING_EVIDENCE') return '근거가 충돌해 보류';
  return '사유 미기록';
}

export function SummarySection({ readiness, findings, run, loading, staticDemo = false }: { readiness: ReadinessResponse | null; findings: FindingsResponse | null; run: RunResult | null; loading: boolean; staticDemo?: boolean }) {
  const score = readiness?.readiness.readiness_score;
  const diagnostics = findings?.diagnostics;
  const activeFindingCount = findings?.findings.filter((item) => item.comparison_status !== 'NOT_REPRODUCED_AFTER').length;
  const returnComparison = findings?.findings.find((item) => item.finding_type === 'CONFLICTING_SOURCES' && item.comparison)?.comparison;
  const state = run ? runState(run) : null;
  const delivery = run && 'delivery_status' in run ? run : null;
  const payload = delivery?.payload;
  const answer = payload?.status === 'ANSWERED'
    ? formatAnswer(payload.answer, payload.unit)
    : null;
  return <section className="summary-section" id="summary" aria-labelledby="summary-title">
    <header className="section-heading summary-heading">
      <div><div className="section-index">01 / 업무 진단</div><h1 id="summary-title">AI 업무 진단</h1></div>
      {state && <Status tone={state === 'DELIVERED' ? 'positive' : state === 'REJECTED' ? 'danger' : 'warning'}>{state}</Status>}
    </header>
    <div className="impact-story" aria-label="핵심 진단 사례">
      <div className="impact-story__readiness"><span>정적 Data Readiness</span><strong>{score === undefined ? '—' : Math.round(score)}<small>/ 100</small></strong><p>파일 구조 점검은 통과했지만 실제 업무 성공을 보증하지 않습니다.</p></div>
      <div className="impact-story__case"><span>반품 기간 업무</span>{returnComparison ? <div><strong>{returnComparison.before_observed_run_count - returnComparison.before_abstained_run_count} / {returnComparison.before_observed_run_count}</strong><i>→</i><strong>{returnComparison.after_answered_run_count} / {returnComparison.after_observed_run_count}</strong></div> : staticDemo ? <div><strong>0 / 3</strong><i>→</i><strong>3 / 3</strong></div> : <strong>비교 결과 조회 전</strong>}<p>14일·30일 충돌을 지목하고 정리한 뒤, 세 번 모두 30일로 답했습니다.</p></div>
    </div>
    <div className="diagnostic-grid" aria-label="업무 진단 요약">
      <div className="diagnostic-metric"><span>반복 안정 처리</span><strong>{loading ? '…' : `${diagnostics?.processable_task_count ?? 0} / ${diagnostics?.task_count || '—'}`}</strong><small>3회 모두 같은 의미값으로 답변</small></div>
      <div className="diagnostic-metric"><span>일관된 보류</span><strong>{loading ? '…' : `${diagnostics?.blocked_task_count ?? 0} / ${diagnostics?.task_count || '—'}`}</strong><small>3회 모두 보류된 업무</small></div>
      <div className="diagnostic-metric diagnostic-metric--accent"><span>불안정·검토 필요</span><strong>{loading ? '…' : `${diagnostics?.inconclusive_task_count ?? 0} / ${diagnostics?.task_count || '—'}`}</strong><small>답변·보류 혼재 또는 의미값 차이</small></div>
    </div>
    <div className="summary-verdict" aria-live="polite">
        <span className="summary-verdict__label">현재 실행 결과</span>
        {delivery?.delivery_status === 'DELIVERED' && payload && <>
          <div className="summary-verdict__line"><strong>{payload.status === 'ANSWERED' ? '답변' : '보류'}</strong><span>{payload.status === 'ANSWERED' ? answer : abstentionReason(payload.abstention_reason)}</span></div>
          <span className="agent-explanation-label">에이전트 설명 · 검증 대상 아님</span>
          <p>{payload.explanation}</p>
        </>}
        {delivery?.delivery_status === 'REJECTED' && <>
          <div className="summary-verdict__line is-rejected"><strong>실행 거절</strong><span>{delivery.reject_reason ?? '사유 미기록'}</span></div>
          <p>전달된 answer payload가 없습니다.</p>
        </>}
        {run && state === 'RUNNING' && <>
          <div className="summary-verdict__line is-running"><strong>실행 중</strong><span>최종 결과 대기 중</span></div>
          <p>완료 전에는 Delivery verdict를 표시하지 않습니다.</p>
        </>}
        {!run && <>
          <div className="summary-verdict__line is-empty"><strong>실행 선택 없음</strong><span>데이터셋 전체 진단을 표시 중입니다.</span></div>
          <p>실행 ID를 조회하면 개별 실행 결과와 근거 검사를 함께 볼 수 있습니다.</p>
        </>}
    </div>
    <div className="summary-status">
      <div><span>데이터셋</span><strong>{readiness?.dataset_name ?? '조회 전'}</strong></div>
      <div><span>관측 실행</span><strong className="mono">{diagnostics?.observed_run_count ?? '—'}회</strong></div>
      <div><span>열린 진단 신호</span><strong className="mono">{activeFindingCount ?? 0}건</strong></div>
      <div><span>실행 ID</span><strong className="mono">{run?.run_id ?? '전체 진단'}</strong></div>
    </div>
    {findings?.comparison_version === 'v2' && findings.legacy_diagnostics && <details className="comparison-audit"><summary>의미 비교 규칙 v2 적용 · 기존 문자열 비교 v1 결과 보기</summary><p>같은 frozen run을 재실행하지 않고 다시 분류했습니다. v1은 처리 {findings.legacy_diagnostics.processable_task_count}, 보류 {findings.legacy_diagnostics.blocked_task_count}, 불안정 {findings.legacy_diagnostics.inconclusive_task_count}; v2는 처리 {diagnostics?.processable_task_count}, 보류 {diagnostics?.blocked_task_count}, 불안정 {diagnostics?.inconclusive_task_count}입니다.</p></details>}
  </section>;
}
