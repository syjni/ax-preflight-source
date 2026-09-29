import type { FeaturedCase, FeaturedRunReference } from '../api';

type FeaturedCaseJourneyProps = {
  cases: FeaturedCase[];
  currentDataset: string;
  currentRunId: string | null;
  loadingRunId: string | null;
  error: string;
  onOpen: (reference: FeaturedRunReference) => void;
};

function StageButton({
  reference,
  currentDataset,
  currentRunId,
  loadingRunId,
  onOpen,
}: {
  reference: FeaturedRunReference;
  currentDataset: string;
  currentRunId: string | null;
  loadingRunId: string | null;
  onOpen: (reference: FeaturedRunReference) => void;
}) {
  const selected = currentDataset === reference.dataset && currentRunId === reference.run_id;
  const loading = loadingRunId === reference.run_id;
  return <button
    type="button"
    className={`featured-case__stage featured-case__stage--${reference.phase.toLowerCase()}${selected ? ' is-selected' : ''}`}
    aria-pressed={selected}
    disabled={Boolean(loadingRunId)}
    onClick={() => onOpen(reference)}
  >
    <span className="featured-case__phase">{reference.label}</span>
    <strong>{reference.result}</strong>
    <span className="featured-case__detail">{reference.detail}</span>
    <span className="featured-case__action">{loading ? '불러오는 중…' : selected ? '현재 보고 있는 실행' : `${reference.action_label} →`}</span>
  </button>;
}

export function FeaturedCaseJourney(props: FeaturedCaseJourneyProps) {
  const featured = props.cases[0];
  if (!featured) return null;
  const walkthrough = featured.walkthrough;

  function printFrozenPocReport() {
    document.body.classList.add('print-frozen-poc');
    const cleanup = () => document.body.classList.remove('print-frozen-poc');
    window.addEventListener('afterprint', cleanup, { once: true });
    window.print();
  }

  return <section className="featured-case" id="featured-case" aria-labelledby="featured-case-title">
    <div className="featured-case__copy">
      <div className="section-index">검증된 대표 흐름</div>
      <h2 id="featured-case-title">{featured.title}</h2>
      <p>{featured.summary}</p>
      <small>{featured.question}</small>
    </div>
    <div className="featured-case__stages">
      <StageButton reference={featured.before} currentDataset={props.currentDataset} currentRunId={props.currentRunId} loadingRunId={props.loadingRunId} onOpen={props.onOpen} />
      <span className="featured-case__arrow" aria-hidden="true">→</span>
      <StageButton reference={featured.after} currentDataset={props.currentDataset} currentRunId={props.currentRunId} loadingRunId={props.loadingRunId} onOpen={props.onOpen} />
    </div>
    {walkthrough && <div className="frozen-poc" id="verified-poc" aria-labelledby="verified-poc-title">
      <header className="frozen-poc__header">
        <div><span className="mono">{walkthrough.label} · {walkthrough.snapshot_id}</span><h3 id="verified-poc-title">승인 업무부터 최종 보고서까지</h3><p>{walkthrough.recommendation_note}</p></div>
        <div><strong>{walkthrough.recommendation === 'CONDITIONAL_GO' ? 'CONDITIONAL' : walkthrough.recommendation}</strong><span>읽기 전용 · 실시간 실행 아님</span></div>
      </header>
      <div className="frozen-poc__journey">
        <article><span>01 · Before → After</span><strong>{featured.before.result} → {featured.after.result}</strong><p>{walkthrough.failure_recovery}</p></article>
        <article><span>02 · 승인 업무</span><strong>{walkthrough.approved_task_question}</strong><p><code>{walkthrough.approved_task_id}</code> · {walkthrough.approval_scope}</p></article>
        <article><span>03 · 실행 결과</span><strong>성공 최종 실행 {walkthrough.successful_runs}회</strong><p>승인 업무 반복 표본만 집계했습니다.</p></article>
        <article><span>04 · 근거 경로와 인용</span><strong>DIRECT_MATCH {walkthrough.direct_evidence_runs}/{walkthrough.successful_runs}</strong><p>{walkthrough.cited_source_ids.map((sourceId) => <code key={sourceId}>{sourceId}</code>)}</p></article>
        <article><span>05 · 실패 복구</span><strong>충돌 보류 → 근거 직접 일치</strong><p>{walkthrough.failure_recovery}</p></article>
        <article><span>06 · 모델·데이터 전달 경계</span><strong>{walkthrough.model}</strong><p>{walkthrough.model_boundary}</p></article>
        <article><span>07 · 비용·실행 통제</span><strong>조직별 설정 필요</strong><p>{walkthrough.cost_control}</p></article>
        <article><span>08 · 감사·보존 상태</span><strong>동결 무결성 검증</strong><p>{walkthrough.audit_retention}</p></article>
      </div>
      <div className="frozen-poc__gates">
        <div><span className="mono">POC DECISION GATES</span><h4>PoC 평가 게이트</h4></div>
        {walkthrough.gates.map((gate) => <article key={gate.code} className={`is-${gate.status.toLowerCase()}`}><span>{gate.status === 'PASS' ? '통과' : gate.status === 'WARN' ? '검토' : '차단'}</span><div><strong>{gate.label}</strong><p>{gate.detail}</p></div><code>{gate.code}</code></article>)}
      </div>
      <footer className="frozen-poc__report">
        <div><span className="mono">FINAL APPROVAL REPORT</span><h4>최종 승인 보고서</h4><p>{walkthrough.final_report_note}</p></div>
        <button className="no-print" type="button" onClick={printFrozenPocReport}>읽기 전용 보고서 인쇄</button>
      </footer>
    </div>}
    {props.error && <div className="notice notice--danger" role="alert">{props.error}</div>}
  </section>;
}
