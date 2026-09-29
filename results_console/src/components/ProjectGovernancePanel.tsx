import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, api } from '../api';
import type { ProjectAuditLog, ProjectDataInventory, ProjectPurgeResult, ProjectView } from '../generated/api';
import { Status, type Tone } from './Status';

type Props = {
  project: ProjectView;
  revision: number;
  onPurged: (result: ProjectPurgeResult) => void;
};

const eventLabels: Record<string, string> = {
  BOOTSTRAP_COMPLETED: '초기 관리자 설정',
  PROJECT_CREATED: '프로젝트 생성',
  PROJECT_MEMBER_SET: '구성원 권한 설정',
  PROJECT_MEMBER_REMOVED: '구성원 권한 회수',
  TASK_CREATED: '업무 등록',
  TASK_APPROVED: '업무 승인',
  EXECUTION_POLICY_UPDATED: '실행 정책 변경',
  DATA_TRANSFER_APPROVED: '자료 전달 승인',
  DATA_TRANSFER_REVOKED: '자료 전달 승인 해제',
  EXECUTION_BUDGET_RESERVED: '실행 예산 예약',
  RETENTION_POLICY_UPDATED: '보존 정책 변경',
  POC_DECISION_RECORDED: 'PoC 판단 기록',
};

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail === 'PROJECT_DATA_IN_USE') return '진행 중인 실행이나 반복 실행이 끝난 뒤 삭제할 수 있습니다.';
    if (error.detail === 'PROJECT_NAME_CONFIRMATION_MISMATCH') return '프로젝트 이름이 정확히 일치하지 않습니다.';
    if (error.detail === 'PROJECT_LEGAL_HOLD') return '법적 보존을 먼저 해제해야 프로젝트를 삭제할 수 있습니다.';
    if (error.detail === 'AUDIT_LEDGER_INVALID') return '감사 원장 무결성 오류를 조사한 뒤 삭제할 수 있습니다.';
    return error.detail.replace(' · ', ' — ');
  }
  return '보관 항목을 확인하지 못했습니다.';
}

function ledgerStatus(audit: ProjectAuditLog | null): { label: string; tone: Tone } {
  if (!audit) return { label: '확인 전', tone: 'neutral' };
  if (audit.ledger_status === 'VERIFIED') return { label: '체인 검증됨', tone: 'positive' };
  if (audit.ledger_status === 'LEGACY_SEALED') return { label: '기존 기록 봉인됨', tone: 'blue' };
  if (audit.ledger_status === 'LEGACY_UNSEALED') return { label: '기존 기록 미봉인', tone: 'warning' };
  return { label: '무결성 오류', tone: 'danger' };
}

export function ProjectGovernancePanel({ project, revision, onPurged }: Props) {
  const [inventory, setInventory] = useState<ProjectDataInventory | null>(null);
  const [audit, setAudit] = useState<ProjectAuditLog | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [purging, setPurging] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [managedDays, setManagedDays] = useState(90);
  const [auditDays, setAuditDays] = useState(365);
  const [legalHold, setLegalHold] = useState(false);
  const [error, setError] = useState('');
  const [feedback, setFeedback] = useState('');
  const canPurge = project.member_role === 'OWNER';

  async function load() {
    setLoading(true);
    setError('');
    try {
      const [nextInventory, nextAudit] = await Promise.all([
        api.projectDataInventory(project.project_id),
        canPurge ? api.projectAuditLog(project.project_id) : Promise.resolve(null),
      ]);
      setInventory(nextInventory);
      setAudit(nextAudit);
      setManagedDays(nextInventory.retention_policy.managed_data_days ?? 90);
      setAuditDays(nextInventory.retention_policy.audit_event_days ?? 365);
      setLegalHold(nextInventory.retention_policy.legal_hold ?? false);
    } catch (nextError) {
      setError(message(nextError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setInventory(null);
    setAudit(null);
    setConfirmation('');
    setFeedback('');
    void load();
  }, [project.project_id, revision]);

  async function saveRetention(event: FormEvent) {
    event.preventDefault();
    if (!canPurge || saving) return;
    setSaving(true);
    setError('');
    setFeedback('');
    try {
      await api.updateRetentionPolicy(project.project_id, {
        managed_data_days: managedDays,
        audit_event_days: auditDays,
        legal_hold: legalHold,
      });
      await load();
      setFeedback('보존 검토 주기와 법적 보존 상태를 기록했습니다. 자동 삭제는 수행하지 않습니다.');
    } catch (nextError) {
      setError(message(nextError));
    } finally {
      setSaving(false);
    }
  }

  async function purge() {
    if (!canPurge || confirmation !== project.name || purging || legalHold) return;
    const confirmed = window.confirm(`'${project.name}' 프로젝트의 AX Preflight 관리 데이터와 접근 권한을 영구 삭제합니다. 원본 폴더의 파일은 삭제하지 않습니다. 계속할까요?`);
    if (!confirmed) return;
    setPurging(true);
    setError('');
    try {
      const result = await api.purgeProject(project.project_id, confirmation);
      onPurged(result);
    } catch (nextError) {
      setError(message(nextError));
      await load();
    } finally {
      setPurging(false);
    }
  }

  const ledger = ledgerStatus(audit);
  const managedRecordCount = inventory
    ? inventory.local_dataset_count + inventory.business_task_count + inventory.writable_run_count
      + inventory.batch_count + inventory.execution_policy_count + inventory.transfer_approval_count
      + inventory.execution_usage_count + inventory.poc_decision_count
    : 0;
  const deletionStatus: { label: string; tone: Tone } = audit?.ledger_status === 'INVALID'
    ? { label: '감사 확인 필요', tone: 'danger' }
    : legalHold
      ? { label: '법적 보존 · 삭제 차단', tone: 'warning' }
      : inventory?.running_run_count || inventory?.active_batch_count
        ? { label: '사용 중 · 삭제 차단', tone: 'warning' }
        : { label: '삭제 가능', tone: 'positive' };

  return <details className="workspace-panel__governance" id="project-governance">
    <summary><div><span className="mono">DATA GOVERNANCE</span><strong>감사·보존·완전 삭제</strong></div><span>{inventory ? `${managedRecordCount}개 관리 기록` : '확인 중'}</span></summary>
    <div className="governance-panel">
      <div className="governance-panel__lead">
        <div><h3>남아 있는 데이터와 변경 이력을 함께 확인합니다.</h3><p>현재 PoC는 설정된 날짜에 자동 삭제하지 않습니다. OWNER가 검토 기한·법적 보존 상태를 기록하고, 인벤토리를 확인한 뒤 명시적으로 삭제합니다.</p></div>
        <button type="button" onClick={() => void load()} disabled={loading}>{loading ? '확인 중…' : '새로고침'}</button>
      </div>
      {error && <div className="notice notice--danger" role="alert">{error}</div>}
      {feedback && <div className="workspace-panel__feedback" role="status">{feedback}</div>}
      {inventory && <>
        <div className="governance-panel__metrics">
          <div><span>DATASETS</span><strong>{inventory.local_dataset_count}</strong><small>점검 기록</small></div>
          <div><span>MANAGED COPIES</span><strong>{inventory.managed_copy_count}</strong><small>로컬 복사본</small></div>
          <div><span>TASKS</span><strong>{inventory.business_task_count}</strong><small>등록 업무</small></div>
          <div><span>RUNS</span><strong>{inventory.writable_run_count}</strong><small>실행 · 반복 {inventory.batch_count}개</small></div>
          <div><span>CONTROL</span><strong>{inventory.execution_policy_count + inventory.transfer_approval_count}</strong><small>정책·전달 승인</small></div>
          <div><span>AUDIT</span><strong>{inventory.audit_event_count}</strong><small>프로젝트 이벤트</small></div>
        </div>
        <div className="governance-panel__boundary">
          <Status tone={deletionStatus.tone}>{deletionStatus.label}</Status>
          <p>원본 경로의 파일은 항상 유지됩니다. 브라우저로 만든 관리 복사본, 점검 보고서, 구성원 권한, 업무·모델 승인, 실행·반복 기록과 PoC 판단만 관리 범위에 포함됩니다.</p>
        </div>
      </>}

      {canPurge && inventory && <form className="governance-panel__retention" onSubmit={saveRetention}>
        <div><span className="mono">RETENTION REVIEW</span><h3>보존 검토 정책</h3><p>기한은 OWNER가 다시 검토해야 할 날짜입니다. 백그라운드 자동 삭제로 오인되지 않도록 실행은 명시적으로 분리합니다.</p></div>
        <div className="governance-panel__retention-grid">
          <label><span>관리 데이터 검토 주기</span><input type="number" value={managedDays} min={1} max={3650} onInput={(event) => setManagedDays(Number(event.currentTarget.value))} /><small>일</small></label>
          <label><span>감사 이벤트 검토 주기</span><input type="number" value={auditDays} min={30} max={3650} onInput={(event) => setAuditDays(Number(event.currentTarget.value))} /><small>일</small></label>
          <label className="governance-panel__hold"><input type="checkbox" checked={legalHold} onChange={(event) => setLegalHold(event.currentTarget.checked)} /><span><strong>법적 보존</strong><small>켜져 있는 동안 프로젝트 삭제를 서버에서 차단합니다.</small></span></label>
        </div>
        <div className="governance-panel__retention-action"><span>다음 검토 {new Date(inventory.retention_policy.next_review_at).toLocaleDateString('ko-KR')}</span><button type="submit" disabled={saving}>{saving ? '저장 중…' : '보존 정책 저장'}</button></div>
      </form>}

      {canPurge && <section className="governance-panel__audit" aria-label="프로젝트 감사 로그">
        <div className="governance-panel__audit-head"><div><span className="mono">AUDIT LEDGER</span><h3>최근 변경 이력</h3></div><Status tone={ledger.tone}>{ledger.label}</Status></div>
        {audit?.ledger_status === 'INVALID' && <div className="notice notice--danger" role="alert">감사 원장의 해시 체인이 일치하지 않습니다. 새 변경 작업을 중단하고 파일 무결성을 조사하세요.</div>}
        {audit && audit.events.length === 0 && audit.ledger_status !== 'INVALID' && <p className="workspace-panel__empty">이 프로젝트에 기록된 감사 이벤트가 없습니다.</p>}
        {audit && audit.events.length > 0 && <div className="governance-panel__audit-list">{audit.events.slice(0, 12).map((item) => <article key={item.event_id}>
          <time dateTime={item.at}>{new Date(item.at).toLocaleString('ko-KR')}</time>
          <div><strong>{eventLabels[item.event] ?? item.event}</strong><small>{item.target ?? '대상 없음'}</small></div>
          <span>{item.integrity_verified ? '검증' : '미검증'}</span>
        </article>)}</div>}
        {audit && audit.event_count > 12 && <p className="governance-panel__audit-more">최근 12건 표시 · 전체 {audit.event_count}건</p>}
      </section>}

      {canPurge ? <div className="governance-panel__danger">
        <div><span className="mono">DANGER ZONE</span><h3>프로젝트 영구 삭제</h3><p>되돌릴 수 없습니다. 서버는 삭제 후 모든 관리 저장소와 감사 로그에서 프로젝트 식별자가 사라졌는지 검증하고 삭제 증명서를 반환합니다.</p></div>
        {legalHold && <div className="notice notice--warning" role="status">법적 보존이 설정되어 삭제가 차단되었습니다.</div>}
        <label><span>프로젝트 이름 <strong>{project.name}</strong> 입력</span><input value={confirmation} onInput={(event) => setConfirmation(event.currentTarget.value)} autoComplete="off" /></label>
        <button type="button" className="is-danger" onClick={() => void purge()} disabled={purging || legalHold || confirmation !== project.name || Boolean(inventory?.running_run_count) || Boolean(inventory?.active_batch_count)}>{purging ? '삭제·검증 중…' : '프로젝트와 관리 데이터 영구 삭제'}</button>
      </div> : <p className="workspace-panel__empty">감사 로그 조회, 보존 정책 변경과 프로젝트 삭제는 OWNER만 수행할 수 있습니다.</p>}
    </div>
  </details>;
}
