import type { TasksResponse } from '../generated/api';
import { taskRows } from '../viewModel';
import { Status } from './Status';

const fieldLabels: Record<string, string> = { category: '범주', status: '상태', owner: '담당', criteria: '성공 기준', approver: '승인', approved: '승인일', description: '설명' };
const fieldValues: Record<string, string> = { CANDIDATE: '업무 후보', VERIFIED: '검증 업무' };

export function TaskTable({ data, error, activeTaskId, onTaskSelect }: { data: TasksResponse | null; error: string; activeTaskId: string | null; onTaskSelect: (taskId: string) => void }) {
  const rows = data ? taskRows(data) : [];
  const verifiedCount = rows.filter((task) => task.status === 'VERIFIED').length;
  const candidateCount = rows.length - verifiedCount;
  return <section className="report-section" id="tasks" aria-labelledby="tasks-title">
    <header className="section-heading">
      <div><div className="section-index">05 / 업무 검증</div><h2 id="tasks-title">승인된 업무와 후보</h2></div>
      <Status tone={verifiedCount > 0 ? 'positive' : data ? 'blue' : 'neutral'}>{data ? `검증 ${verifiedCount} · 후보 ${candidateCount}` : (error ? 'API 오류' : '조회 전')}</Status>
    </header>
    {error && <div className="notice notice--danger" role="alert">{error}</div>}
    {verifiedCount > 0
      ? <div className="notice"><strong>승인 기록이 있는 업무만 검증 업무로 실행됩니다.</strong><span>승인 범위·담당 역할·성공 기준은 선택한 데이터셋에 고정됩니다. 통제 데모 승인은 실제 고객 승인과 구분해 표시합니다.</span></div>
      : data && <div className="notice"><strong>아직 승인 기록이 없는 업무 테스트 후보입니다.</strong><span>업무 담당자가 데이터셋 범위와 성공 기준을 승인하기 전에는 검증 업무로 실행되지 않습니다.</span></div>}
    {rows.length > 0 && <div className="task-table">
      {rows.map((task, index) => {
        const active = Boolean(task.id && task.id === activeTaskId);
        const scope = task.approvalScope === 'CUSTOMER' ? '고객 승인' : task.approvalScope === 'CONTROLLED_DEMO' ? '통제 데모 승인' : null;
        const content = <><span className="mono task-number">{String(index + 1).padStart(2, '0')}</span><strong>{task.label}</strong>{task.fields.length > 0 && <span className="task-fields">{scope && <span className="task-scope">{scope}</span>}{task.fields.map((field) => <span className={`task-field task-field--${field.label}`} key={field.label}><b>{fieldLabels[field.label] ?? field.label}:</b> {fieldValues[field.value] ?? field.value}</span>)}</span>}</>;
        return task.id ? <button className={task.status === 'VERIFIED' ? 'is-verified' : undefined} key={task.id} onClick={() => onTaskSelect(task.id!)}>{content}<span>{active ? '연결된 진단 보기 ↘' : task.status === 'VERIFIED' ? '검증 업무 선택 ↘' : '후보 질문 선택 ↘'}</span></button>
          : <div className="task-row" key={index}>{content}<span>선택 불가</span></div>;
      })}
    </div>}
  </section>;
}
