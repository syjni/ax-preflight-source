import { useState } from 'react';
import type { DataFinding, FindingType } from '../generated/api';
import { Status, type Tone } from './Status';

const typeCopy: Record<FindingType, { label: string; tone: Tone }> = {
  CONFLICTING_SOURCES: { label: '문서 충돌', tone: 'warning' },
  INCONSISTENT_ANSWERS: { label: '불안정 업무 · 원인 미확인 (의미값 불일치)', tone: 'warning' },
  MIXED_OUTCOMES: { label: '실행 결과 혼재', tone: 'warning' },
  INSUFFICIENT_EVIDENCE: { label: '근거 부족', tone: 'warning' },
  MISSING_INFORMATION: { label: '자료 공백', tone: 'warning' },
};
const legacyComparisonAuditLabel = 'After에서 재현되지 않음';
const currentReturnFaqExcerpt = '반품 가능 여부는 구매일, 상품 상태, 영수증 보유 여부를 함께 확인한다.';

function headline(finding: DataFinding): string {
  return finding.affected_tasks.map((task) => task.label).join(', ') || '업무 수준 진단 신호';
}

function evidenceHeading(finding: DataFinding): string {
  if (finding.finding_type === 'CONFLICTING_SOURCES') return '정리 전 실행에서 인용한 서로 충돌한 원문';
  if (finding.finding_type === 'MIXED_OUTCOMES') return '보류 실행에서 조회한 자료';
  if (finding.finding_type === 'MISSING_INFORMATION' || finding.finding_type === 'INSUFFICIENT_EVIDENCE') {
    return '검색했지만 답을 확정하지 못한 자료';
  }
  return '실행에서 반환된 근거';
}

function formatAnswer(answer: string | number | boolean | string[], unit: string | null | undefined): string {
  const value = Array.isArray(answer) ? answer.join(', ') : String(answer);
  if (!unit) return value;
  const compactValue = value.replace(/\s/g, '').toLocaleLowerCase();
  const compactUnit = unit.replace(/\s/g, '').toLocaleLowerCase();
  if (compactUnit === 'date') return value;
  if (compactUnit === 'krw' && (compactValue.endsWith('원') || compactValue.startsWith('₩'))) return value;
  return compactValue.endsWith(compactUnit) ? value : `${value} ${unit}`;
}

function abstentionReason(reason: string): string {
  const copy: Record<string, string> = {
    NOT_FOUND: '필요한 자료를 찾지 못해 보류',
    INSUFFICIENT_EVIDENCE: '근거가 부족해 보류',
    CONFLICTING_EVIDENCE: '근거가 충돌해 보류',
  };
  return copy[reason] ?? '판단을 보류';
}

function attributionCopy(status: DataFinding['attribution_status']): string {
  if (status === 'RETRIEVAL_LIMITATION') return '검색 경로 한계 확인';
  return status === 'CAUSE_UNCONFIRMED' ? '원인 미확인' : '데이터 신호';
}

function highlightedExcerpt(excerpt: string) {
  return excerpt.split(/(14일|30일)/g).map((part, index) =>
    part === '14일' || part === '30일' ? <mark key={`${part}-${index}`}>{part}</mark> : part
  );
}

function evidenceContext(finding: DataFinding, sourceTitle: string | null | undefined): string | null {
  if (finding.finding_type !== 'CONFLICTING_SOURCES') return null;
  if (sourceTitle?.includes('FAQ_2026')) return '정리 전 원문 · Before 실행에서 인용';
  return '변경되지 않은 현행 정책 · Before 실행에서 인용';
}

function parseStructuredRows(excerpt: string | null | undefined, toolName: string) {
  if (toolName !== 'query_table' || !excerpt) return null;
  try {
    const value: unknown = JSON.parse(excerpt);
    if (!Array.isArray(value) || value.length === 0 || !value.every((row) => row && typeof row === 'object' && !Array.isArray(row))) return null;
    return value as Array<Record<string, unknown>>;
  } catch {
    return null;
  }
}

function StructuredRows({ rows }: { rows: Array<Record<string, unknown>> }) {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  return <div className="structured-table-wrap"><table className="structured-table">
    <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
    <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{columns.map((column) => <td key={column}>{row[column] == null ? '—' : String(row[column])}</td>)}</tr>)}</tbody>
  </table></div>;
}

export function FindingCard({ finding, index }: { finding: DataFinding; index: number }) {
  const [open, setOpen] = useState(finding.finding_type === 'CONFLICTING_SOURCES');
  const copy = typeCopy[finding.finding_type];
  const comparisonStatus = finding.comparison_status ?? 'OPEN';
  const statusCopy = comparisonStatus === 'NOT_REPRODUCED_AFTER'
    ? '수정 후 미재현'
    : comparisonStatus === 'UNKNOWN' ? '비교 확인 필요' : attributionCopy(finding.attribution_status);
  return <article className={`finding-card finding-card--${comparisonStatus.toLowerCase()} finding-card--${finding.finding_type.toLowerCase()}`} id={`finding-${finding.finding_id}`} data-legacy-comparison-label={comparisonStatus === 'NOT_REPRODUCED_AFTER' ? legacyComparisonAuditLabel : undefined}>
    <button className="finding-trigger" aria-expanded={open} aria-controls={`finding-body-${finding.finding_id}`} onClick={() => setOpen((value) => !value)}>
      <span className="finding-number mono">{String(index + 1).padStart(2, '0')}</span>
      <span><small>{copy.label}</small><strong>{headline(finding)}</strong></span>
      <Status tone={comparisonStatus === 'NOT_REPRODUCED_AFTER' ? 'positive' : comparisonStatus === 'UNKNOWN' ? 'neutral' : copy.tone}>{statusCopy}</Status>
      <span className="row-toggle">{open ? '접기 −' : '펼치기 +'}</span>
    </button>
    {open && <div className="finding-body" id={`finding-body-${finding.finding_id}`}>
      <div className="finding-copy"><p>{finding.summary}</p><div><span>권고 조치</span><strong>{finding.recommended_action}</strong></div></div>
      <div className="finding-counts" aria-label="영향 범위">
        <div><span>영향받은 업무</span><strong>{finding.affected_task_count}</strong><small>고유 업무</small></div>
        {finding.finding_type === 'MIXED_OUTCOMES'
          ? <div><span>반복 실행 결과</span><strong className="finding-counts__mixed">{finding.answered_run_count} 답변 · {finding.abstained_run_count} 보류</strong><small>총 {finding.observed_run_count}회</small></div>
          : comparisonStatus === 'NOT_REPRODUCED_AFTER' && finding.comparison
            ? <div><span>정리 전·후 반복 결과</span><strong className="finding-counts__transition">{finding.comparison.before_abstained_run_count}회 보류 → {finding.comparison.after_answered_run_count}회 답변</strong><small>Before → After</small></div>
          : <div><span>{finding.finding_type === 'INCONSISTENT_ANSWERS' ? '비교한 답변 실행' : '관측된 실패 실행'}</span><strong>{finding.observed_run_count}</strong><small>반복 실행 포함</small></div>}
      </div>
      {finding.comparison && <div className="finding-comparison">
        <span>수정 전</span><strong>{finding.comparison.before_abstained_run_count} / {finding.comparison.before_observed_run_count} 충돌로 보류</strong>
        <span>수정 후</span><strong>{finding.comparison.after_answered_run_count} / {finding.comparison.after_observed_run_count} 답변</strong>
      </div>}
      {finding.finding_type === 'CONFLICTING_SOURCES' && finding.comparison && <div className="finding-current-source">
        <span>정리 후 원문 · 현재 FAQ</span><strong>FAQ_2026.txt</strong>
        <blockquote>{currentReturnFaqExcerpt}</blockquote>
        <small>정리 전의 ‘14일’ 문장을 제거했으며, 현재 반품 기간은 정책 문서의 30일을 따릅니다.</small>
      </div>}
      {(finding.answer_variants?.length ?? 0) > 0 && <div className="finding-evidence"><h3>{finding.finding_type === 'MIXED_OUTCOMES' ? '답변된 실행의 값' : '반복 실행에서 관측된 의미값'}</h3>{finding.answer_variants?.map((variant) => <article key={`${variant.normalized_value}-${variant.normalized_unit ?? ''}-${variant.source_ids.join('|')}`}>
        <div><strong>{formatAnswer(variant.answer, variant.unit)}</strong><span className="mono">{variant.run_count}회</span></div>
        <details className="technical-detail"><summary>비교 상세</summary><p className="mono">정규화: {variant.normalized_value}{variant.normalized_unit ? ` · ${variant.normalized_unit}` : ''}</p><small className="mono">{variant.source_ids.join(', ') || '출처 없음'}</small></details>
      </article>)}</div>}
      {(finding.abstention_variants?.length ?? 0) > 0 && <div className="finding-evidence finding-evidence--abstention"><h3>보류된 실행의 사유</h3>{finding.abstention_variants?.map((variant) => <article key={`${variant.reason}-${variant.explanation}`}>
        <div><strong>{abstentionReason(variant.reason)}</strong><span className="mono">{variant.run_count}회</span></div>
        <p>{variant.explanation}</p>
        <details className="technical-detail"><summary>실행 상세</summary><small className="mono">{variant.run_ids.join(', ')}</small></details>
      </article>)}</div>}
      {finding.evidence.length > 0 && <div className={`finding-evidence ${finding.finding_type === 'CONFLICTING_SOURCES' ? 'finding-evidence--conflict' : ''}`}><h3>{evidenceHeading(finding)}</h3>{finding.evidence.map((item) => {
        const rows = parseStructuredRows(item.excerpt, item.tool_name);
        const context = evidenceContext(finding, item.source_title);
        return <article key={item.source_id}>
        <div><strong>{item.source_title ?? (item.tool_name === 'query_table' ? '구조화 조회 결과' : '자료 발췌')}</strong></div>
        {context && <small className="evidence-context">{context}</small>}
        {rows ? <StructuredRows rows={rows} /> : item.excerpt ? <blockquote>{finding.finding_type === 'CONFLICTING_SOURCES' ? highlightedExcerpt(item.excerpt) : item.excerpt}</blockquote> : <p>이 자료의 발췌문을 같은 실행의 도구 응답에서 찾지 못했습니다.</p>}
        <details className="technical-detail"><summary>감사 정보</summary><small className="mono">{item.tool_name} · {item.source_id}</small></details>
      </article>;})}</div>}
      <details className="finding-audit"><summary>기술 감사 정보</summary><dl className="finding-meta">
        <div><dt>원인 귀속</dt><dd>{finding.attribution_status === 'RETRIEVAL_LIMITATION' ? '검색·탐색 경로 한계 확인' : finding.attribution_status === 'CAUSE_UNCONFIRMED' ? '데이터 원인 미확인' : '데이터 신호 관측'}</dd></div>
        <div><dt>Finding 유형</dt><dd className="mono">{finding.finding_type}</dd></div>
        <div><dt>Finding ID</dt><dd className="mono">{finding.finding_id}</dd></div>
        <div><dt>Run IDs</dt><dd className="source-values">{finding.affected_run_ids.map((id) => <span className="mono" key={id}>{id}</span>)}</dd></div>
      </dl></details>
    </div>}
  </article>;
}
