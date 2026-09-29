import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, api } from '../api';
import type { DatasetOption, ProjectExecutionControl, ProjectMemberView, ProjectPurgeResult, ProjectTaskView, ProjectView, UserView } from '../generated/api';
import { Status } from './Status';
import { ExecutionControlPanel } from './ExecutionControlPanel';
import { ProjectGovernancePanel } from './ProjectGovernancePanel';

type Props = {
  user: UserView;
  projects: ProjectView[];
  selectedProject: ProjectView | null;
  selectedDataset: DatasetOption | null;
  onProjectSelect: (projectId: string) => void;
  onProjectCreated: (project: ProjectView) => void;
  onTasksChanged: () => void;
  executionControl: ProjectExecutionControl | null;
  executionControlLoading: boolean;
  executionControlError: string;
  onExecutionControlRefresh: () => Promise<void>;
  governanceRevision: number;
  onProjectPurged: (result: ProjectPurgeResult) => void;
  onLogout: () => void;
};

function message(error: unknown): string {
  if (error instanceof ApiError) return error.detail.replace(' · ', ' — ');
  return '요청을 처리하지 못했습니다.';
}

export function WorkspacePanel({ user, projects, selectedProject, selectedDataset, onProjectSelect, onProjectCreated, onTasksChanged, executionControl, executionControlLoading, executionControlError, onExecutionControlRefresh, governanceRevision, onProjectPurged, onLogout }: Props) {
  const [showProjectForm, setShowProjectForm] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [tasks, setTasks] = useState<ProjectTaskView[]>([]);
  const [members, setMembers] = useState<ProjectMemberView[]>([]);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [busyTask, setBusyTask] = useState<string | null>(null);
  const [busyMember, setBusyMember] = useState<string | null>(null);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');
  const [category, setCategory] = useState('');
  const [question, setQuestion] = useState('');
  const [description, setDescription] = useState('');
  const [ownerRole, setOwnerRole] = useState('');
  const [criteria, setCriteria] = useState('');
  const [newUsername, setNewUsername] = useState('');
  const [newDisplayName, setNewDisplayName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [memberUsername, setMemberUsername] = useState('');
  const [memberRole, setMemberRole] = useState<'EDITOR' | 'VIEWER'>('VIEWER');
  const localDataset = selectedDataset?.origin === 'LOCAL' && selectedDataset.project_id === selectedProject?.project_id
    ? selectedDataset : null;
  const canWrite = selectedProject?.member_role === 'OWNER' || selectedProject?.member_role === 'EDITOR';
  const canApprove = selectedProject?.member_role === 'OWNER';

  useEffect(() => {
    if (!selectedProject) { setMembers([]); return; }
    let active = true;
    setError('');
    setFeedback('');
    api.projectMembers(selectedProject.project_id)
      .then((next) => { if (active) setMembers(next); })
      .catch((nextError) => { if (active) setError(message(nextError)); });
    return () => { active = false; };
  }, [selectedProject?.project_id]);

  useEffect(() => {
    if (!selectedProject || !localDataset) {
      setTasks([]);
      setLoadingTasks(false);
      return;
    }
    let active = true;
    setLoadingTasks(true);
    setError('');
    api.projectTasks(selectedProject.project_id, localDataset.profile)
      .then((next) => { if (active) setTasks(next); })
      .catch((nextError) => { if (active) setError(message(nextError)); })
      .finally(() => { if (active) setLoadingTasks(false); });
    return () => { active = false; };
  }, [selectedProject?.project_id, localDataset?.profile]);

  async function createProject(event: FormEvent) {
    event.preventDefault();
    if (!projectName.trim()) return;
    setError('');
    try {
      const project = await api.createProject({ name: projectName.trim(), description: '' });
      setProjectName('');
      setShowProjectForm(false);
      onProjectCreated(project);
    } catch (nextError) { setError(message(nextError)); }
  }

  async function createTask(event: FormEvent) {
    event.preventDefault();
    if (!selectedProject || !localDataset || !canWrite) return;
    const successCriteria = criteria.split('\n').map((value) => value.trim()).filter(Boolean);
    if (!successCriteria.length) return;
    setBusyTask('create');
    setError('');
    try {
      const task = await api.createProjectTask(selectedProject.project_id, {
        dataset_profile: localDataset.profile,
        category: category.trim(), question: question.trim(), description: description.trim(),
        owner_role: ownerRole.trim(), success_criteria: successCriteria,
      });
      setTasks((current) => [...current, task]);
      setCategory(''); setQuestion(''); setDescription(''); setOwnerRole(''); setCriteria('');
      onTasksChanged();
    } catch (nextError) { setError(message(nextError)); }
    finally { setBusyTask(null); }
  }

  async function createUser(event: FormEvent) {
    event.preventDefault();
    setError('');
    try {
      await api.createUser({
        username: newUsername.trim(), display_name: newDisplayName.trim(),
        password: newPassword, global_role: 'MEMBER',
      });
      setMemberUsername(newUsername.trim().toLocaleLowerCase());
      setNewUsername(''); setNewDisplayName(''); setNewPassword('');
    } catch (nextError) { setError(message(nextError)); }
  }

  async function addMember(event: FormEvent) {
    event.preventDefault();
    if (!selectedProject || !canApprove) return;
    setError('');
    try {
      const member = await api.addProjectMember(selectedProject.project_id, {
        username: memberUsername.trim(), role: memberRole,
      });
      setMembers((current) => [...current.filter((item) => item.user.user_id !== member.user.user_id), member]);
      setMemberUsername('');
      setFeedback(`${member.user.display_name}님의 프로젝트 권한을 ${member.role}로 설정했습니다.`);
    } catch (nextError) { setError(message(nextError)); }
  }

  async function removeMember(member: ProjectMemberView) {
    if (!selectedProject || !canApprove || member.role === 'OWNER') return;
    if (!window.confirm(`${member.user.display_name}님의 '${selectedProject.name}' 접근 권한을 제거할까요?`)) return;
    setBusyMember(`remove:${member.user.user_id}`);
    setError(''); setFeedback('');
    try {
      await api.removeProjectMember(selectedProject.project_id, member.user.user_id);
      setMembers((current) => current.filter((item) => item.user.user_id !== member.user.user_id));
      setFeedback(`${member.user.display_name}님의 프로젝트 접근 권한을 제거했습니다.`);
    } catch (nextError) { setError(message(nextError)); }
    finally { setBusyMember(null); }
  }

  async function revokeSessions(member: ProjectMemberView) {
    if (user.global_role !== 'ADMIN' || member.user.user_id === user.user_id) return;
    if (!window.confirm(`${member.user.display_name}님의 모든 로그인 세션을 종료할까요?`)) return;
    setBusyMember(`revoke:${member.user.user_id}`);
    setError(''); setFeedback('');
    try {
      const result = await api.revokeUserSessions(member.user.user_id);
      setFeedback(`${member.user.display_name}님의 로그인 세션 ${result.revoked_sessions}개를 종료했습니다.`);
    } catch (nextError) { setError(message(nextError)); }
    finally { setBusyMember(null); }
  }

  async function approve(taskId: string) {
    if (!selectedProject || !canApprove) return;
    setBusyTask(taskId);
    setError('');
    try {
      const approved = await api.approveProjectTask(selectedProject.project_id, taskId);
      setTasks((current) => current.map((task) => task.task_id === taskId ? approved : task));
      onTasksChanged();
    } catch (nextError) { setError(message(nextError)); }
    finally { setBusyTask(null); }
  }

  return <section className="workspace-panel report-section" aria-labelledby="workspace-title">
    <header className="workspace-panel__header">
      <div><div className="section-index">POC WORKSPACE / 접근 격리</div><h2 id="workspace-title">{selectedProject?.name ?? '프로젝트 선택'}</h2><p>{user.display_name} · {user.global_role === 'ADMIN' ? '관리자' : '구성원'} · {selectedProject?.member_role ?? '권한 없음'}</p></div>
      <button type="button" className="workspace-panel__logout" onClick={onLogout}>로그아웃</button>
    </header>
    <div className="workspace-panel__selector">
      <label><span>현재 프로젝트</span><select value={selectedProject?.project_id ?? ''} onChange={(event) => onProjectSelect(event.currentTarget.value)}>{projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.name} · {project.member_role}</option>)}</select></label>
      <button type="button" onClick={() => setShowProjectForm((value) => !value)}>새 프로젝트 +</button>
    </div>
    {showProjectForm && <form className="workspace-panel__project-form" onSubmit={createProject}><input value={projectName} onInput={(event) => setProjectName(event.currentTarget.value)} placeholder="프로젝트 이름" maxLength={80} required /><button>만들기</button></form>}
    {error && <div className="notice notice--danger" role="alert">{error}</div>}
    {feedback && <div className="workspace-panel__feedback" role="status">{feedback}</div>}
    {selectedProject && <details className="workspace-panel__members">
      <summary><div><span className="mono">PROJECT ACCESS</span><strong>구성원과 권한</strong></div><span>{members.length}명</span></summary>
      <div className="workspace-panel__member-list">{members.map((member) => <div key={member.user.user_id}><span><strong>{member.user.display_name}</strong><small>{member.user.username}</small></span><div className="workspace-panel__member-actions"><Status tone={member.role === 'OWNER' ? 'positive' : 'neutral'}>{member.role}</Status>{user.global_role === 'ADMIN' && member.user.user_id !== user.user_id && <button type="button" onClick={() => void revokeSessions(member)} disabled={busyMember !== null}>{busyMember === `revoke:${member.user.user_id}` ? '종료 중…' : '세션 종료'}</button>}{canApprove && member.role !== 'OWNER' && <button type="button" className="is-danger" onClick={() => void removeMember(member)} disabled={busyMember !== null}>{busyMember === `remove:${member.user.user_id}` ? '제거 중…' : '권한 제거'}</button>}</div></div>)}</div>
      {user.global_role === 'ADMIN' && <form className="workspace-panel__member-form" onSubmit={createUser}><strong>새 로그인 계정 만들기</strong><div><input value={newUsername} onInput={(event) => setNewUsername(event.currentTarget.value)} placeholder="아이디" minLength={3} maxLength={32} required /><input value={newDisplayName} onInput={(event) => setNewDisplayName(event.currentTarget.value)} placeholder="표시 이름" maxLength={80} required /></div><input type="password" value={newPassword} onInput={(event) => setNewPassword(event.currentTarget.value)} placeholder="초기 비밀번호 · 12자 이상" minLength={12} maxLength={256} autoComplete="new-password" required /><button>계정 만들기</button></form>}
      {canApprove && <form className="workspace-panel__member-form" onSubmit={addMember}><strong>기존 계정에 프로젝트 권한 주기</strong><div><input value={memberUsername} onInput={(event) => setMemberUsername(event.currentTarget.value)} placeholder="사용자 아이디" required /><select value={memberRole} onChange={(event) => setMemberRole(event.currentTarget.value as 'EDITOR' | 'VIEWER')}><option value="VIEWER">VIEWER · 조회</option><option value="EDITOR">EDITOR · 등록</option></select></div><button>구성원 추가·변경</button></form>}
    </details>}
    <details className="workspace-panel__tasks" open>
      <summary><div><span className="mono">BUSINESS TASK CONTROL</span><strong>업무 등록·승인</strong></div><span>{localDataset ? `${tasks.filter((task) => task.status === 'APPROVED').length}/${tasks.length} 승인` : '내 자료 선택 필요'}</span></summary>
      {!localDataset && <p className="workspace-panel__empty">이 프로젝트에서 점검한 로컬 자료를 선택하면 실제 업무 질문과 성공 기준을 등록할 수 있습니다.</p>}
      {loadingTasks && <div className="state-message">등록 업무를 불러오는 중…</div>}
      {localDataset && tasks.length > 0 && <div className="workspace-panel__task-list">{tasks.map((task) => <article key={task.task_id}>
        <div><Status tone={task.status === 'APPROVED' ? 'positive' : 'warning'}>{task.status === 'APPROVED' ? '승인됨' : '검토 대기'}</Status><span>{task.category}</span></div>
        <strong>{task.question}</strong><p>{task.description}</p><small>책임 {task.owner_role} · 성공 기준 {task.success_criteria.length}개</small>
        {task.status === 'DRAFT' && canApprove && <button type="button" onClick={() => void approve(task.task_id)} disabled={busyTask === task.task_id}>{busyTask === task.task_id ? '승인 중…' : '업무 승인 →'}</button>}
      </article>)}</div>}
      {localDataset && canWrite && <form className="workspace-panel__task-form" onSubmit={createTask}>
        <div><label><span>업무 분류</span><input value={category} onInput={(event) => setCategory(event.currentTarget.value)} placeholder="예: 반품 정책" required /></label><label><span>업무 책임 역할</span><input value={ownerRole} onInput={(event) => setOwnerRole(event.currentTarget.value)} placeholder="예: 고객지원 팀장" required /></label></div>
        <label><span>실제 업무 질문</span><textarea value={question} onInput={(event) => setQuestion(event.currentTarget.value)} placeholder="이 자료를 근거로 반복 확인할 질문" required /></label>
        <label><span>업무 설명</span><textarea value={description} onInput={(event) => setDescription(event.currentTarget.value)} placeholder="판단 범위와 사용 맥락" required /></label>
        <label><span>성공 기준 <small>한 줄에 하나</small></span><textarea value={criteria} onInput={(event) => setCriteria(event.currentTarget.value)} placeholder={'근거 문서를 인용한다\n불확실하면 답을 보류한다'} required /></label>
        <button className="primary-action" disabled={busyTask === 'create'}>{busyTask === 'create' ? '등록 중…' : '검토 대기 업무 등록 →'}</button>
      </form>}
      {localDataset && !canWrite && <p className="workspace-panel__empty">VIEWER는 승인된 업무와 결과를 읽을 수 있습니다. 등록·승인은 EDITOR 또는 OWNER 권한이 필요합니다.</p>}
    </details>
    {selectedProject && <ExecutionControlPanel project={selectedProject} dataset={selectedDataset} control={executionControl} loading={executionControlLoading} loadError={executionControlError} onRefresh={onExecutionControlRefresh} />}
    {selectedProject && <ProjectGovernancePanel project={selectedProject} revision={governanceRevision} onPurged={onProjectPurged} />}
  </section>;
}
