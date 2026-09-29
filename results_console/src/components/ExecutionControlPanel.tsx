import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, api } from '../api';
import type {
  DatasetOption,
  ProjectExecutionControl,
  ProjectView,
} from '../generated/api';
import { Status, type Tone } from './Status';

type Props = {
  project: ProjectView;
  dataset: DatasetOption | null;
  control: ProjectExecutionControl | null;
  loading: boolean;
  loadError: string;
  onRefresh: () => Promise<void>;
};

type ExecutionBlocker = NonNullable<ProjectExecutionControl['blockers']>[number];

const blockerCopy: Record<ExecutionBlocker, string> = {
  RUNNER_UNAVAILABLE: 'AI 실행 runner가 활성화되지 않았습니다.',
  RUNNER_EXECUTABLE_UNAVAILABLE: 'Kiro CLI 실행 파일을 현재 환경에서 찾을 수 없습니다.',
  EXECUTION_POLICY_REQUIRED: 'OWNER가 모델과 실행 한도를 먼저 확정해야 합니다.',
  DATASET_REQUIRED: '이 프로젝트에서 점검한 내 자료를 선택해야 합니다.',
  DATA_TRANSFER_APPROVAL_REQUIRED: '선택한 자료의 모델 전달 경계 승인이 필요합니다.',
  DATA_TRANSFER_APPROVAL_EXPIRED: '자료 전달 승인이 만료되었습니다. 다시 검토해 승인하세요.',
  MODEL_NOT_APPROVED: '현재 실행 모델이 자료 전달 승인에 기록된 모델과 다릅니다.',
  BATCH_RUN_LIMIT_EXCEEDED: '예정 실행 수가 프로젝트의 배치 한도를 넘습니다.',
  DAILY_RUN_LIMIT_REACHED: '최근 24시간 실행 한도를 모두 사용했습니다.',
  DAILY_BUDGET_REACHED: '최근 24시간 예상 비용 한도를 모두 사용했습니다.',
  CONCURRENCY_LIMIT_REACHED: '동시에 실행할 수 있는 작업 수를 모두 사용했습니다.',
};

function apiMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail.replace(' · ', ' — ');
  return '실행 통제 설정을 처리하지 못했습니다.';
}

function money(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function connectionLabel(control: ProjectExecutionControl | null): { label: string; tone: Tone } {
  if (!control) return { label: '확인 전', tone: 'neutral' };
  if (!control.connection.runner_enabled) return { label: 'runner 꺼짐', tone: 'warning' };
  if (control.connection.executable_status === 'UNAVAILABLE') return { label: 'CLI 확인 필요', tone: 'warning' };
  if (control.connection.executable_status === 'AVAILABLE') return { label: '연결 준비됨', tone: 'positive' };
  return { label: '설정 runner', tone: 'blue' };
}

export function ExecutionControlPanel({ project, dataset, control, loading, loadError, onRefresh }: Props) {
  const owner = project.member_role === 'OWNER';
  const localDataset = dataset?.origin === 'LOCAL' && dataset.project_id === project.project_id
    ? dataset : null;
  const [model, setModel] = useState('claude-sonnet-5');
  const [dailyRuns, setDailyRuns] = useState(20);
  const [batchRuns, setBatchRuns] = useState(10);
  const [concurrentRuns, setConcurrentRuns] = useState(1);
  const [costPerRun, setCostPerRun] = useState('0.10');
  const [dailyBudget, setDailyBudget] = useState('2.00');
  const [classification, setClassification] = useState<'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL'>('INTERNAL');
  const [validDays, setValidDays] = useState(30);
  const [toolOutputAcknowledged, setToolOutputAcknowledged] = useState(false);
  const [providerPolicyReviewed, setProviderPolicyReviewed] = useState(false);
  const [sensitiveDataReviewed, setSensitiveDataReviewed] = useState(false);
  const [busy, setBusy] = useState<'policy' | 'approval' | 'revoke' | null>(null);
  const [error, setError] = useState('');
  const [feedback, setFeedback] = useState('');

  useEffect(() => {
    const policy = control?.policy;
    const defaultModel = policy?.model ?? control?.connection.default_model ?? 'claude-sonnet-5';
    setModel(defaultModel);
    setDailyRuns(policy?.daily_run_limit ?? 20);
    setBatchRuns(policy?.max_batch_runs ?? 10);
    setConcurrentRuns(policy?.max_concurrent_runs ?? 1);
    setCostPerRun(((policy?.estimated_cost_per_run_cents ?? 10) / 100).toFixed(2));
    setDailyBudget(((policy?.daily_budget_cents ?? 200) / 100).toFixed(2));
  }, [control?.policy?.updated_at, control?.connection.default_model]);

  useEffect(() => {
    setError('');
    setFeedback('');
    setToolOutputAcknowledged(false);
    setProviderPolicyReviewed(false);
    setSensitiveDataReviewed(false);
  }, [project.project_id, localDataset?.profile]);

  useEffect(() => {
    setClassification(control?.transfer_approval?.data_classification ?? 'INTERNAL');
  }, [control?.transfer_approval?.approval_id]);

  async function savePolicy(event: FormEvent) {
    event.preventDefault();
    if (!owner) return;
    if (policyValidation) {
      setError(policyValidation);
      return;
    }
    setBusy('policy');
    setError('');
    setFeedback('');
    try {
      await api.updateExecutionPolicy(project.project_id, {
        model: model.trim(),
        daily_run_limit: dailyRuns,
        max_batch_runs: batchRuns,
        max_concurrent_runs: concurrentRuns,
        estimated_cost_per_run_cents: costPerRunCents,
        daily_budget_cents: dailyBudgetCents,
      });
      await onRefresh();
      setFeedback('모델과 실행 한도를 저장했습니다. 모델을 바꾸면 자료 전달 승인을 다시 받아야 합니다.');
    } catch (nextError) {
      setError(apiMessage(nextError));
    } finally {
      setBusy(null);
    }
  }

  async function approveTransfer(event: FormEvent) {
    event.preventDefault();
    if (!owner || !localDataset || !control?.policy || !approvalReady) return;
    setBusy('approval');
    setError('');
    setFeedback('');
    try {
      await api.approveDataTransfer(project.project_id, {
        dataset_profile: localDataset.profile,
        model: control.policy.model ?? model,
        data_classification: classification,
        tool_output_to_model_acknowledged: true,
        provider_policy_reviewed: true,
        sensitive_data_reviewed: true,
        valid_days: validDays,
      });
      await onRefresh();
      setToolOutputAcknowledged(false);
      setProviderPolicyReviewed(false);
      setSensitiveDataReviewed(false);
      setFeedback('이 자료와 모델 조합의 전달 경계를 승인했습니다.');
    } catch (nextError) {
      setError(apiMessage(nextError));
    } finally {
      setBusy(null);
    }
  }

  async function revokeTransfer() {
    if (!owner || !localDataset || !control?.transfer_approval) return;
    if (!window.confirm(`'${localDataset.display_label}'의 모델 전달 승인을 해제할까요? 해제 즉시 새 실행이 차단됩니다.`)) return;
    setBusy('revoke');
    setError('');
    setFeedback('');
    try {
      await api.revokeDataTransfer(project.project_id, localDataset.profile);
      await onRefresh();
      setFeedback('자료 전달 승인을 해제했습니다.');
    } catch (nextError) {
      setError(apiMessage(nextError));
    } finally {
      setBusy(null);
    }
  }

  const connection = connectionLabel(control);
  const policy = control?.policy;
  const usage = control?.usage;
  const approval = control?.transfer_approval;
  const approvalReady = toolOutputAcknowledged && providerPolicyReviewed && sensitiveDataReviewed;
  const costPerRunCents = Math.round(Number(costPerRun) * 100);
  const dailyBudgetCents = Math.round(Number(dailyBudget) * 100);
  const policyValidation = !model.trim()
    ? '승인 모델을 입력하세요.'
    : batchRuns > dailyRuns
      ? '배치당 실행 한도는 24시간 실행 한도보다 클 수 없습니다.'
      : !Number.isFinite(costPerRunCents) || costPerRunCents < 1
        ? '실행당 예상 비용은 $0.01 이상이어야 합니다.'
        : !Number.isFinite(dailyBudgetCents) || dailyBudgetCents < costPerRunCents
          ? '24시간 예상 비용 한도는 실행 한 번의 예상 비용 이상이어야 합니다.'
          : '';
  const blockers = control?.blockers ?? [];
  const statusText = !localDataset
    ? '내 자료 선택 필요'
    : loading
      ? '확인 중…'
      : control?.can_execute
        ? '실행 가능'
        : `${blockers.length}개 조치 필요`;

  return <details className="workspace-panel__execution" id="execution-control" open>
    <summary>
      <div><span className="mono">MODEL &amp; COST CONTROL</span><strong>모델 연결·데이터 경계·비용</strong></div>
      <span>{statusText}</span>
    </summary>
    <div className="execution-control">
      {!localDataset && <p className="workspace-panel__empty">이 프로젝트에서 점검한 내 자료를 선택하면 모델 전달 범위와 실행 한도를 설정할 수 있습니다.</p>}
      {localDataset && loading && <div className="state-message">실행 통제 상태를 확인하는 중…</div>}
      {localDataset && loadError && <div className="notice notice--danger" role="alert">{loadError}</div>}
      {localDataset && control && <>
        <div className="execution-control__overview">
          <article>
            <div><span className="mono">MODEL CONNECTION</span><Status tone={connection.tone}>{connection.label}</Status></div>
            <strong>{control.connection.provider === 'KIRO_CLI' ? 'Kiro CLI' : '구성된 runner'}</strong>
            <p>자격 증명은 실행 환경에서만 관리하며 화면·프로젝트 파일에 저장하거나 표시하지 않습니다.</p>
            <small>실행 파일 {control.connection.executable_status} · 자격 증명 미탐색 · 제한 {control.connection.timeout_seconds ? `${control.connection.timeout_seconds}초` : 'runner 기본값'}</small>
          </article>
          <article>
            <div><span className="mono">DATA BOUNDARY</span><Status tone={approval ? 'positive' : 'warning'}>{approval ? '승인됨' : '승인 필요'}</Status></div>
            <strong>{approval ? `${approval.data_classification} · ${approval.model}` : localDataset.display_label}</strong>
            <p>검색 도구가 읽은 자료 일부와 질문이 승인된 모델에 전달될 수 있습니다. 원본 폴더 자체는 업로드하지 않습니다.</p>
            <small>{approval ? `${new Date(approval.expires_at).toLocaleDateString('ko-KR')}까지 · PII 가능 파일 ${approval.pii_affected_file_count}개` : '자료·모델 조합별 OWNER 승인'}</small>
          </article>
        </div>

        {blockers.length > 0 && <div className="execution-control__blockers" role="status">
          <strong>실행 전 확인할 항목</strong>
          <ul>{blockers.map((blocker) => <li key={blocker}><code>{blocker}</code><span>{blockerCopy[blocker]}</span></li>)}</ul>
        </div>}

        {policy && usage && <div className="execution-control__usage" aria-label="최근 24시간 실행 사용량">
          <div><span>예약 실행</span><strong>{usage.reserved_runs} / {policy.daily_run_limit}</strong><small>남음 {usage.remaining_run_capacity}회</small></div>
          <div><span>예상 비용</span><strong>{money(usage.estimated_spend_cents)} / {money(policy.daily_budget_cents ?? 0)}</strong><small>남음 {money(usage.remaining_budget_cents)}</small></div>
          <div><span>동시 실행</span><strong>{usage.running_runs} / {policy.max_concurrent_runs}</strong><small>서버 확인값</small></div>
          <div><span>배치 한도</span><strong>{policy.max_batch_runs}회</strong><small>요청 한 건 기준</small></div>
        </div>}

        {owner ? <form className="execution-control__form" onSubmit={savePolicy}>
          <div className="execution-control__form-heading"><div><strong>1. 모델과 한도</strong><p>금액은 실제 청구액이 아닌 보수적인 실행 전 예상치입니다.</p></div><Status tone={policy ? 'positive' : 'warning'}>{policy ? '저장됨' : '미설정'}</Status></div>
          <div className="execution-control__policy-grid">
            <label><span>승인 모델</span><input value={model} onInput={(event) => setModel(event.currentTarget.value)} maxLength={120} required /></label>
            <label><span>24시간 실행 한도</span><input type="number" value={dailyRuns} onInput={(event) => setDailyRuns(Number(event.currentTarget.value))} min={1} max={500} required /></label>
            <label><span>배치당 실행 한도</span><input type="number" value={batchRuns} onInput={(event) => setBatchRuns(Number(event.currentTarget.value))} min={1} max={50} required /></label>
            <label><span>동시 실행 한도</span><input type="number" value={concurrentRuns} onInput={(event) => setConcurrentRuns(Number(event.currentTarget.value))} min={1} max={5} required /></label>
            <label><span>실행당 예상 비용 · USD</span><input type="number" value={costPerRun} onInput={(event) => setCostPerRun(event.currentTarget.value)} min="0.01" max="1000" step="0.01" required /></label>
            <label><span>24시간 예상 비용 한도 · USD</span><input type="number" value={dailyBudget} onInput={(event) => setDailyBudget(event.currentTarget.value)} min="0.01" max="100000" step="0.01" required /></label>
          </div>
          {policyValidation && <p className="execution-control__validation" role="status">{policyValidation}</p>}
          <button className="primary-action" disabled={busy !== null || Boolean(policyValidation)}>{busy === 'policy' ? '저장 중…' : '실행 정책 저장 →'}</button>
        </form> : <p className="workspace-panel__empty">실행 정책과 자료 전달 승인은 OWNER만 변경할 수 있습니다. 현재 설정과 사용량은 모든 프로젝트 구성원이 확인할 수 있습니다.</p>}

        {owner && <form className="execution-control__form" onSubmit={approveTransfer}>
          <div className="execution-control__form-heading"><div><strong>2. 선택 자료 전달 승인</strong><p>{localDataset.display_label} · {policy?.model ?? '실행 정책을 먼저 저장하세요'}</p></div>{approval && <button type="button" className="execution-control__revoke" onClick={() => void revokeTransfer()} disabled={busy !== null}>{busy === 'revoke' ? '해제 중…' : '승인 해제'}</button>}</div>
          <div className="execution-control__approval-grid">
            <label><span>데이터 분류</span><select value={classification} onChange={(event) => setClassification(event.currentTarget.value as typeof classification)} disabled={!policy}><option value="PUBLIC">PUBLIC · 공개</option><option value="INTERNAL">INTERNAL · 사내</option><option value="CONFIDENTIAL">CONFIDENTIAL · 기밀</option></select></label>
            <label><span>승인 유효 기간</span><select value={validDays} onChange={(event) => setValidDays(Number(event.currentTarget.value))} disabled={!policy}><option value={7}>7일</option><option value={30}>30일</option><option value={90}>90일</option><option value={365}>365일</option></select></label>
          </div>
          <div className="execution-control__checks">
            <label><input type="checkbox" checked={toolOutputAcknowledged} onChange={(event) => setToolOutputAcknowledged(event.currentTarget.checked)} disabled={!policy} /><span>질문과 검색 도구 출력이 모델에 전달될 수 있음을 확인했습니다.</span></label>
            <label><input type="checkbox" checked={providerPolicyReviewed} onChange={(event) => setProviderPolicyReviewed(event.currentTarget.checked)} disabled={!policy} /><span>사용할 모델 제공자의 데이터 처리·보존 정책을 검토했습니다.</span></label>
            <label><input type="checkbox" checked={sensitiveDataReviewed} onChange={(event) => setSensitiveDataReviewed(event.currentTarget.checked)} disabled={!policy} /><span>민감정보 가능 패턴과 자료 분류를 검토했습니다.</span></label>
          </div>
          <button className="primary-action" disabled={busy !== null || !policy || !approvalReady}>{busy === 'approval' ? '승인 중…' : approval ? '전달 경계 다시 승인 →' : '전달 경계 승인 →'}</button>
        </form>}
        {error && <div className="notice notice--danger" role="alert">{error}</div>}
        {feedback && <div className="workspace-panel__feedback" role="status">{feedback}</div>}
      </>}
    </div>
  </details>;
}
