import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, api } from '../api';
import type { DatasetOption, PocEvaluationGate, PocEvaluationReport, ProjectView } from '../generated/api';
import { Status, type Tone } from './Status';

type Props = {
  project: ProjectView | null;
  dataset: DatasetOption | null;
  revision: string;
};

const gateLabels: Record<PocEvaluationGate['status'], string> = {
  PASS: '통과', WARN: '검토', BLOCK: '차단',
};

const decisionLabels = {
  APPROVED: '승인', CONDITIONAL: '조건부 승인', REJECTED: '반려',
} as const;

function apiMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail === 'POC_GO_GATES_REQUIRED') return '모든 차단·검토 항목을 통과해야 최종 승인할 수 있습니다.';
    if (error.detail === 'POC_BLOCKERS_REMAIN') return '차단 항목이 남아 있어 조건부 승인할 수 없습니다.';
    return error.detail.replace(' · ', ' — ');
  }
  return 'PoC 평가를 불러오지 못했습니다.';
}

function recommendation(report: PocEvaluationReport): { label: string; tone: Tone } {
  if (report.recommendation === 'GO') return { label: 'GO · 승인 가능', tone: 'positive' };
  if (report.recommendation === 'CONDITIONAL_GO') return { label: 'CONDITIONAL · 보완 후 승인', tone: 'warning' };
  return { label: 'NO-GO · 차단 해소 필요', tone: 'danger' };
}

function gateTone(status: PocEvaluationGate['status']): Tone {
  return status === 'PASS' ? 'positive' : status === 'WARN' ? 'warning' : 'danger';
}

export function PocEvaluationPanel({ project, dataset, revision }: Props) {
  const localDataset = project && dataset?.origin === 'LOCAL' && dataset.project_id === project.project_id ? dataset : null;
  const [report, setReport] = useState<PocEvaluationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [decision, setDecision] = useState<'APPROVED' | 'CONDITIONAL' | 'REJECTED'>('REJECTED');
  const [note, setNote] = useState('');
  const [scopeAcknowledged, setScopeAcknowledged] = useState(false);
  const [riskAcknowledged, setRiskAcknowledged] = useState(false);
  const [validDays, setValidDays] = useState(30);
  const owner = project?.member_role === 'OWNER';

  async function load() {
    if (!project || !localDataset) {
      setReport(null);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const next = await api.pocEvaluation(project.project_id, localDataset.profile);
      setReport(next);
      setDecision(next.recommendation === 'GO' ? 'APPROVED' : next.recommendation === 'CONDITIONAL_GO' ? 'CONDITIONAL' : 'REJECTED');
    } catch (nextError) {
      setReport(null);
      setError(apiMessage(nextError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setNote('');
    setScopeAcknowledged(false);
    setRiskAcknowledged(false);
    void load();
  }, [project?.project_id, localDataset?.profile, revision]);

  async function saveDecision(event: FormEvent) {
    event.preventDefault();
    if (!project || !localDataset || !owner || !scopeAcknowledged || !riskAcknowledged || note.trim().length < 5) return;
    setSaving(true);
    setError('');
    try {
      const next = await api.recordPocDecision(project.project_id, localDataset.profile, {
        decision,
        note: note.trim(),
        scope_acknowledged: true,
        risk_acknowledged: true,
        valid_days: validDays,
      });
      setReport(next);
      setScopeAcknowledged(false);
      setRiskAcknowledged(false);
    } catch (nextError) {
      setError(apiMessage(nextError));
    } finally {
      setSaving(false);
    }
  }

  function printApprovalReport() {
    document.body.classList.add('print-poc-evaluation');
    const cleanup = () => document.body.classList.remove('print-poc-evaluation');
    window.addEventListener('afterprint', cleanup, { once: true });
    window.print();
  }

  const status = report ? recommendation(report) : null;
  const currentDecision = report?.decision && report.decision_current && !report.decision_expired
    ? report.decision : null;
  const saveDisabled = saving || note.trim().length < 5 || !scopeAcknowledged || !riskAcknowledged
    || (decision === 'APPROVED' && report?.recommendation !== 'GO')
    || (decision === 'CONDITIONAL' && report?.recommendation === 'NO_GO');

  return <section className="poc-evaluation-report" id="poc-evaluation" aria-labelledby="poc-evaluation-title">
    <div className="poc-evaluation__actions no-print"><span>PoC 평가 대시보드 · 승인 보고서</span><div><button type="button" onClick={() => void load()} disabled={loading}>{loading ? '평가 중…' : '새로고침'}</button><button type="button" onClick={printApprovalReport} disabled={!report}>PDF로 저장 / 인쇄</button></div></div>
    <header className="poc-evaluation__header">
      <div><small>AX Preflight · POC DECISION CONTROL</small><h2 id="poc-evaluation-title">사내 PoC를 다음 단계로 진행해도 되는가</h2><p>{report?.scope_note ?? '현재 프로젝트의 자료를 선택하면 평가 기준과 승인 상태를 계산합니다.'}</p></div>
      <div><span>평가 대상</span><strong>{report?.dataset_name ?? localDataset?.display_label ?? '내 자료 선택 필요'}</strong>{status && <Status tone={status.tone}>{status.label}</Status>}</div>
    </header>

    {!localDataset && <div className="state-message">프로젝트에 연결된 내 자료를 선택하면 정적 준비도, 승인 업무, 관측 실행, 직접 근거와 운영 통제를 함께 평가합니다.</div>}
    {localDataset && loading && !report && <div className="state-message">PoC 평가 지표와 통제를 확인하는 중…</div>}
    {error && <div className="notice notice--danger no-print" role="alert">{error}</div>}
    {report && <>
      <div className="poc-evaluation__metrics">
        <article><span>데이터 준비도</span><strong>{Math.round(report.metrics.readiness_score)}</strong><small>/ 100</small></article>
        <article><span>승인 업무</span><strong>{report.metrics.approved_tasks}</strong><small>/ {report.metrics.registered_tasks}</small></article>
        <article><span>관측 실행</span><strong>{report.metrics.observed_runs}</strong><small>답변 {report.metrics.answered_runs} · 보류 {report.metrics.abstained_runs}</small></article>
        <article><span>직접 근거</span><strong>{report.metrics.direct_evidence_runs}</strong><small>DIRECT_MATCH</small></article>
        <article><span>안정 처리 업무</span><strong>{report.metrics.stable_tasks}</strong><small>반복 의미값 기준</small></article>
        <article><span>열린 신호</span><strong>{report.metrics.open_findings}</strong><small>원인 검토 대상</small></article>
      </div>

      <div className="poc-evaluation__gates">
        <div className="poc-evaluation__section-head"><div><span className="mono">DECISION GATES</span><h3>승인 게이트</h3></div><span>{report.gates.filter((item) => item.status === 'PASS').length} / {report.gates.length} 통과</span></div>
        {report.gates.map((item) => <article key={item.code} className={`is-${item.status.toLowerCase()}`}><Status tone={gateTone(item.status)}>{gateLabels[item.status]}</Status><div><strong>{item.label}</strong><p>{item.detail}</p></div><code>{item.code}</code></article>)}
      </div>

      <div className="poc-evaluation__decision">
        <div className="poc-evaluation__section-head"><div><span className="mono">ACCOUNTABLE DECISION</span><h3>책임자 판단</h3></div>{currentDecision ? <Status tone={currentDecision.decision === 'APPROVED' ? 'positive' : currentDecision.decision === 'CONDITIONAL' ? 'warning' : 'danger'}>{decisionLabels[currentDecision.decision]}</Status> : <Status tone="neutral">유효한 판단 없음</Status>}</div>
        {report.decision && <div className={`poc-evaluation__decision-record${currentDecision ? '' : ' is-stale'}`}>
          <div><strong>{decisionLabels[report.decision.decision]}</strong><span>{new Date(report.decision.decided_at).toLocaleString('ko-KR')} · {new Date(report.decision.expires_at).toLocaleDateString('ko-KR')}까지</span></div>
          <p>{report.decision.note}</p>
          {!currentDecision && <small>{report.decision_expired ? '판단 유효 기간이 만료되었습니다.' : '평가 지표 또는 통제가 바뀌어 다시 판단해야 합니다.'}</small>}
        </div>}

        {owner ? <form className="poc-evaluation__decision-form no-print" onSubmit={saveDecision}>
          <div className="poc-evaluation__decision-fields">
            <label><span>판단</span><select value={decision} onChange={(event) => setDecision(event.currentTarget.value as typeof decision)}><option value="APPROVED" disabled={report.recommendation !== 'GO'}>승인 · GO만 가능</option><option value="CONDITIONAL" disabled={report.recommendation === 'NO_GO'}>조건부 승인</option><option value="REJECTED">반려</option></select></label>
            <label><span>유효 기간</span><select value={validDays} onChange={(event) => setValidDays(Number(event.currentTarget.value))}><option value={7}>7일</option><option value={30}>30일</option><option value={90}>90일</option><option value={365}>365일</option></select></label>
          </div>
          <label><span>판단 근거와 후속 조건</span><textarea value={note} onInput={(event) => setNote(event.currentTarget.value)} rows={3} maxLength={2000} placeholder="예: 반품 업무 3회 직접 근거 확인 후 고객지원팀에 한정해 승인" /></label>
          <div className="poc-evaluation__checks"><label><input type="checkbox" checked={scopeAcknowledged} onChange={(event) => setScopeAcknowledged(event.currentTarget.checked)} /><span>현재 데이터셋·업무·관측 실행 범위의 판단임을 확인했습니다.</span></label><label><input type="checkbox" checked={riskAcknowledged} onChange={(event) => setRiskAcknowledged(event.currentTarget.checked)} /><span>열린 신호와 모델·데이터 전달 경계를 검토했습니다.</span></label></div>
          <button className="primary-action" disabled={saveDisabled}>{saving ? '기록 중…' : '판단 기록 및 보고서 확정 →'}</button>
        </form> : <p className="workspace-panel__empty no-print">평가 결과는 볼 수 있지만 책임자 판단은 프로젝트 OWNER만 기록할 수 있습니다.</p>}
      </div>

      <footer><span>평가 ID {report.assessment_fingerprint.slice(0, 12)} · {new Date(report.generated_at).toLocaleString('ko-KR')}</span><span>판단은 지표·게이트가 바뀌거나 유효 기간이 끝나면 자동으로 ‘재검토 필요’가 됩니다.</span></footer>
    </>}
  </section>;
}
