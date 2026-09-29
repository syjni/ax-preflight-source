import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { ApiError, api, isStaticDemo } from '../api';
import type { BatchStatus, BusinessTaskView, ProjectExecutionControl, TasksResponse } from '../generated/api';
import { Status } from './Status';

type BatchPanelProps = {
  dataset: string;
  tasks: TasksResponse | null;
  canRun: boolean;
  fixture: boolean;
  fixtureBatch?: BatchStatus | null;
  model?: string;
  executionControl?: ProjectExecutionControl | null;
  onUsageChanged?: () => void;
  onOpenRun: (runId: string) => void;
};

type BatchAction = 'pause' | 'resume' | 'cancel' | 'retry';

const activeStates = new Set<BatchStatus['state']>([
  'QUEUED', 'RUNNING', 'PAUSE_REQUESTED', 'PAUSED', 'CANCEL_REQUESTED',
]);

const stateLabels: Record<BatchStatus['state'], string> = {
  QUEUED: '대기',
  RUNNING: '실행 중',
  PAUSE_REQUESTED: '일시정지 대기',
  PAUSED: '일시정지',
  CANCEL_REQUESTED: '중단 대기',
  CANCELLED: '중단됨',
  COMPLETED: '완료',
  COMPLETED_WITH_ERRORS: '일부 실패',
};

const itemStateLabels: Record<BatchStatus['items'][number]['status'], string> = {
  QUEUED: '대기',
  RUNNING: '실행 중',
  SUCCEEDED: '성공',
  FAILED: '실패',
  CANCELLED: '중단',
};

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    const labels: Record<string, string> = {
      RUNNER_UNAVAILABLE: '실행 runner가 꺼져 있습니다.',
      RUNNER_EXECUTABLE_UNAVAILABLE: 'Kiro CLI 실행 파일을 찾을 수 없습니다.',
      EXECUTION_POLICY_REQUIRED: 'OWNER가 모델과 실행 한도를 먼저 저장해야 합니다.',
      DATA_TRANSFER_APPROVAL_REQUIRED: '이 자료의 모델 전달 경계 승인이 필요합니다.',
      DATA_TRANSFER_APPROVAL_EXPIRED: '자료 전달 승인이 만료되었습니다.',
      MODEL_NOT_APPROVED: '실행 모델과 자료 전달 승인 모델이 다릅니다.',
      BATCH_RUN_LIMIT_EXCEEDED: '예정 실행 수가 프로젝트의 배치 한도를 넘습니다.',
      DAILY_RUN_LIMIT_REACHED: '최근 24시간 실행 한도를 모두 사용했습니다.',
      DAILY_BUDGET_REACHED: '최근 24시간 예상 비용 한도를 모두 사용했습니다.',
      CONCURRENCY_LIMIT_REACHED: '동시 실행 한도를 모두 사용했습니다.',
      BATCH_NOT_PAUSABLE: '현재 상태에서는 일시정지할 수 없습니다.',
      BATCH_NOT_RESUMABLE: '현재 상태에서는 재개할 수 없습니다.',
      BATCH_ALREADY_TERMINAL: '이미 종료된 배치입니다.',
      BATCH_NOT_RETRYABLE: '종료되거나 일시정지된 배치만 재시도할 수 있습니다.',
      NO_RETRYABLE_ITEMS: '재시도 가능한 실패 항목이 없습니다.',
      API_CONNECTION_FAILED: 'API 연결에 실패했습니다.',
    };
    return labels[error.detail] ?? `${error.status || 'API'} · ${error.detail}`;
  }
  return '반복 실행 요청을 처리하지 못했습니다.';
}

function taskRequest(task: BusinessTaskView) {
  return task.status === 'VERIFIED'
    ? { task_id: task.task_id, request_type: 'VERIFIED_BUSINESS_TASK' as const }
    : { task_id: task.task_id, request_type: 'TASK_CANDIDATE' as const, question: task.question };
}

export function BatchPanel({ dataset, tasks, canRun, fixture, fixtureBatch, model, executionControl, onUsageChanged, onOpenRun }: BatchPanelProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [repetitions, setRepetitions] = useState(3);
  const [maxAttempts, setMaxAttempts] = useState(2);
  const [batch, setBatch] = useState<BatchStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const readOnly = fixture || isStaticDemo;

  useEffect(() => {
    const available = tasks?.tasks ?? [];
    const preferred = available.find((task) => task.status === 'VERIFIED') ?? available[0];
    setSelectedIds(preferred ? [preferred.task_id] : []);
    setBatch(fixtureBatch ?? null);
    setError('');
  }, [dataset, tasks, fixtureBatch]);

  useEffect(() => {
    if (!batch || !activeStates.has(batch.state) || readOnly) return;
    let active = true;
    const refresh = () => {
      api.batch(batch.batch_id)
        .then((next) => {
          if (active) {
            if (next.completed_items !== batch.completed_items || next.state !== batch.state) onUsageChanged?.();
            setBatch(next);
            setError('');
          }
        })
        .catch((nextError: unknown) => { if (active) setError(messageFor(nextError)); });
    };
    const timer = window.setInterval(refresh, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [batch?.batch_id, batch?.state, readOnly]);

  const selectedTasks = useMemo(
    () => (tasks?.tasks ?? []).filter((task) => selectedIds.includes(task.task_id)),
    [tasks, selectedIds],
  );
  const plannedRuns = selectedTasks.length * repetitions;
  const policy = executionControl?.policy;
  const usage = executionControl?.usage;
  const plannedCost = plannedRuns * (policy?.estimated_cost_per_run_cents ?? 0);
  const policyBlocked = Boolean(policy && (
    plannedRuns > (policy.max_batch_runs ?? 0)
    || plannedRuns > (usage?.remaining_run_capacity ?? 0)
    || plannedCost > (usage?.remaining_budget_cents ?? 0)
  ));
  const retryable = Boolean(batch?.items.some(
    (item) => item.status === 'FAILED' && item.attempt < (batch?.max_attempts ?? 0),
  ));

  function toggleTask(taskId: string) {
    setSelectedIds((current) => current.includes(taskId)
      ? current.filter((id) => id !== taskId)
      : [...current, taskId]);
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!dataset || !canRun || readOnly || selectedTasks.length === 0) return;
    setBusy(true);
    setError('');
    try {
      const created = await api.createBatch({
        dataset,
        tasks: selectedTasks.map(taskRequest),
        repetitions,
        max_attempts: maxAttempts,
        ...(model ? { model } : {}),
      });
      setBatch(created);
      onUsageChanged?.();
    } catch (nextError) {
      setError(messageFor(nextError));
    } finally {
      setBusy(false);
    }
  }

  async function act(action: BatchAction) {
    if (!batch || readOnly) return;
    setBusy(true);
    setError('');
    try {
      const operation = {
        pause: api.pauseBatch,
        resume: api.resumeBatch,
        cancel: api.cancelBatch,
        retry: api.retryBatch,
      }[action];
      setBatch(await operation(batch.batch_id));
      if (action === 'resume' || action === 'retry') onUsageChanged?.();
    } catch (nextError) {
      setError(messageFor(nextError));
    } finally {
      setBusy(false);
    }
  }

  const pausable = batch?.state === 'QUEUED' || batch?.state === 'RUNNING';
  const resumable = batch?.state === 'PAUSED' || batch?.state === 'PAUSE_REQUESTED';
  const cancellable = Boolean(batch && !['COMPLETED', 'COMPLETED_WITH_ERRORS', 'CANCELLED'].includes(batch.state));

  return <section className="report-section batch-section" id="batch" aria-labelledby="batch-title">
    <header className="section-heading"><div><div className="section-index">08 / 반복 실행</div><h2 id="batch-title">반복 실행 오케스트레이션</h2></div>{batch && <Status tone={batch.failed_items ? 'warning' : batch.state === 'COMPLETED' ? 'positive' : 'blue'}>{stateLabels[batch.state]}</Status>}</header>
    <p className="section-lede">선택한 업무를 최대 50회까지 순차 실행하고 진행률·부분 실패를 실행 단위로 기록합니다. 일시정지와 중단은 현재 실행을 안전하게 마친 뒤 적용됩니다.</p>

    <form className="batch-config" onSubmit={create}>
      <fieldset disabled={busy || readOnly || !canRun}>
        <legend>실행할 업무</legend>
        <div className="batch-task-list">
          {(tasks?.tasks ?? []).map((task) => <label key={task.task_id}>
            <input type="checkbox" checked={selectedIds.includes(task.task_id)} onChange={() => toggleTask(task.task_id)} />
            <span><strong>{task.question}</strong><small>{task.task_id} · {task.status === 'VERIFIED' ? '승인됨' : '후보'}</small></span>
          </label>)}
        </div>
      </fieldset>
      <div className="batch-options">
        <label>업무별 반복 횟수<select value={repetitions} onChange={(event) => setRepetitions(Number(event.target.value))} disabled={busy || readOnly}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}회</option>)}</select></label>
        <label>최대 시도 횟수<select value={maxAttempts} onChange={(event) => setMaxAttempts(Number(event.target.value))} disabled={busy || readOnly}>{[1, 2, 3].map((value) => <option key={value} value={value}>{value}회</option>)}</select></label>
        <div><span>예정 실행</span><strong>{plannedRuns} / {policy?.max_batch_runs ?? 50}</strong></div>
        {policy && usage && <div className="batch-budget"><span>예상 비용 / 남은 한도</span><strong>${(plannedCost / 100).toFixed(2)} / ${(usage.remaining_budget_cents / 100).toFixed(2)}</strong></div>}
        <button className="primary-action" disabled={busy || readOnly || !canRun || policyBlocked || selectedTasks.length === 0 || plannedRuns > 50}>{busy ? '처리 중…' : readOnly ? '읽기 전용' : policyBlocked ? '실행·비용 한도 조정 필요' : !canRun ? executionControl ? '실행 통제 승인 필요' : '온보딩 확인 필요' : '반복 실행 시작 →'}</button>
      </div>
    </form>

    {error && <div className="notice notice--danger" role="alert"><strong>반복 실행 오류</strong><span>{error}</span></div>}
    {batch && <div className="batch-status" aria-live="polite">
      <div className="batch-progress-heading"><div><span>{batch.batch_id}</span><strong>{batch.completed_items} / {batch.total_items} 완료</strong></div><b>{batch.progress_percent}%</b></div>
      <div className="batch-progress" role="progressbar" aria-label="반복 실행 진행률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={batch.progress_percent}><span style={{ width: `${batch.progress_percent}%` }} /></div>
      <dl className="batch-counts">
        <div><dt>성공</dt><dd>{batch.succeeded_items}</dd></div>
        <div><dt>실패</dt><dd>{batch.failed_items}</dd></div>
        <div><dt>실행 중</dt><dd>{batch.running_items}</dd></div>
        <div><dt>대기</dt><dd>{batch.queued_items}</dd></div>
        <div><dt>중단</dt><dd>{batch.cancelled_items}</dd></div>
      </dl>
      <div className="batch-actions" aria-label="반복 실행 제어">
        <button onClick={() => void act('pause')} disabled={busy || readOnly || !pausable}>일시정지</button>
        <button onClick={() => void act('resume')} disabled={busy || readOnly || !resumable}>재개</button>
        <button onClick={() => void act('cancel')} disabled={busy || readOnly || !cancellable}>중단</button>
        <button onClick={() => void act('retry')} disabled={busy || readOnly || !retryable}>실패만 재시도</button>
      </div>
      <div className="batch-items" role="table" aria-label="반복 실행 항목">
        <div role="row" className="batch-items__head"><span role="columnheader">업무 / 반복</span><span role="columnheader">시도</span><span role="columnheader">상태</span><span role="columnheader">실행 ID</span></div>
        {batch.items.map((item) => <div role="row" key={item.item_id} className={`batch-item is-${item.status.toLowerCase()}`}>
          <span role="cell"><strong>{item.task_label}</strong><small>{item.task_id} · {item.repetition}회차</small></span>
          <span role="cell">{item.attempt} / {batch.max_attempts}</span>
          <span role="cell">{itemStateLabels[item.status]}{item.error_code ? ` · ${item.error_code}` : ''}</span>
          <span role="cell">{item.run_id ? <button onClick={() => onOpenRun(item.run_id!)}>{item.run_id}</button> : '—'}</span>
        </div>)}
      </div>
    </div>}
    {!batch && <p className="batch-empty">배치를 시작하면 각 실행의 상태와 새 run ID가 여기에 기록됩니다.</p>}
    <p className="runner-copy">단일 API 프로세스용 영속 큐입니다. 프로세스 재시작 중이던 항목은 성공으로 추정하지 않고 실패로 표시한 뒤 배치를 일시정지합니다.</p>
  </section>;
}
