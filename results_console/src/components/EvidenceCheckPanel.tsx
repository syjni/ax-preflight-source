import type { EvidenceCheckResult, RetrievalTrace } from '../generated/api';
import { evidenceVerdictCopy } from '../viewModel';
import { Status, type Tone } from './Status';
import { RetrievalTracePanel } from './RetrievalTracePanel';

const verdictTone: Record<EvidenceCheckResult['verdict'], Tone> = {
  DIRECT_MATCH: 'positive', DERIVABLE: 'blue', PARTIAL_SUPPORT: 'warning', UNCONFIRMED: 'neutral',
};

const limitationCopy: Record<string, string> = {
  'Checks only the approved Delivery JSON and cited structured tool responses from this run.': '승인된 결과 JSON과 같은 실행에서 인용한 구조화 도구 응답만 검사합니다.',
  'DERIVABLE is limited to exact sum, difference, and row count; division, rates, unit conversion, and semantic inference are out of scope.': '계산 확인은 정확한 합계·차이·행 수로 제한하며, 나눗셈·비율·단위 변환·의미 추론은 범위 밖입니다.',
  'A lexical direct match does not independently establish broader contextual entailment.': '문자열의 직접 일치만으로 더 넓은 문맥의 정합성까지 보증하지 않습니다.',
};

function SourceSet({ label, ids, tone = 'neutral' }: { label: string; ids: string[]; tone?: Tone }) {
  return <div className="source-set"><span>{label}</span><div>{ids.length ? ids.map((id) => <Status key={id} tone={tone}>{id}</Status>) : <em>없음</em>}</div></div>;
}

export function EvidenceCheckPanel({ data, loading, missing, error, trace, traceLoading, traceMissing, traceError }: { data: EvidenceCheckResult | null; loading: boolean; missing: boolean; error: string; trace: RetrievalTrace | null; traceLoading: boolean; traceMissing: boolean; traceError: string }) {
  const copy = data ? evidenceVerdictCopy[data.verdict] : null;
  return <section className="report-section evidence-check" id="evidence" aria-labelledby="evidence-title">
    <header className="section-heading"><div><div className="section-index">06 / 근거 검사</div><h2 id="evidence-title">근거 검사</h2></div>{data && <Status tone={verdictTone[data.verdict]}>{copy!.label}</Status>}</header>
    <p className="section-lede">최종 DeliveryEnvelope와 동일 run의 구조화 응답만 검사한 별도 결과입니다. DeliveryEnvelope를 수정하지 않습니다.</p>
    {loading && <div className="state-message">근거 검사 결과를 불러오는 중…</div>}
    {missing && <div className="notice"><strong>근거 검사 결과 없음</strong><span>404는 실행 실패나 오답 판정으로 바꾸지 않습니다.</span></div>}
    {error && <div className="notice notice--danger" role="alert">{error}</div>}
    {data && <div className={`evidence-result evidence-result--${data.verdict.toLowerCase()}`}>
      <div className="evidence-summary"><div><strong>{copy!.label}</strong></div><p>{copy!.summary}</p></div>
      {data.unconfirmed_is_not_incorrect && <div className="not-incorrect">확인 불가가 오답을 뜻하지 않음</div>}
      <details className="evidence-audit"><summary>근거 연결 감사 정보</summary><div className="source-groups">
        <SourceSet label="인용" ids={data.cited_source_ids} />
        <SourceSet label="일치" ids={data.matched_source_ids} tone="positive" />
        <SourceSet label="미확인" ids={data.unmatched_source_ids} tone="warning" />
      </div>
      {data.derivation && <div className="derivation"><h3>계산 상세</h3><dl>
        <div><dt>연산</dt><dd className="mono">{data.derivation.operation}</dd></div>
        <div><dt>필드</dt><dd className="mono">{data.derivation.field ?? '—'}</dd></div>
        <div><dt>피연산자</dt><dd className="mono">{data.derivation.operands.join(', ') || '—'}</dd></div>
        <div><dt>결과</dt><dd className="mono">{data.derivation.result}</dd></div>
      </dl></div>}
      <div className="evidence-references"><h3>검사 응답</h3>{data.evidence.length ? data.evidence.map((item) => <div key={`${item.sequence}-${item.tool_name}`}><span className="mono">#{item.sequence}</span><strong>{item.tool_name}</strong><span>{item.match}</span><small className="mono">{item.source_ids.join(', ')}</small></div>) : <p>기록된 검사 응답 없음</p>}</div>
      <div className="evidence-hash"><span>Delivery SHA-256</span><code>{data.delivery_sha256}</code></div></details>
      <div className="limitations"><h3>검사 범위와 한계</h3><ul>{data.limitations.map((item, index) => <li key={index}>{limitationCopy[item] ?? item}</li>)}</ul></div>
    </div>}
    <RetrievalTracePanel data={trace} loading={traceLoading} missing={traceMissing} error={traceError} />
  </section>;
}
