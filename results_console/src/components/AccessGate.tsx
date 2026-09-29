import { useState, type FormEvent } from 'react';
import { ApiError, api } from '../api';
import type { AuthSessionResponse } from '../generated/api';

type Props = {
  session: AuthSessionResponse | null;
  loading: boolean;
  error: string;
  onAuthenticated: (session: AuthSessionResponse) => void;
};

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail.includes('INVALID_CREDENTIALS')) return '아이디 또는 비밀번호를 다시 확인하세요.';
    if (error.detail.includes('LOGIN_RATE_LIMITED')) return error.detail.split(' · ')[1] ?? '로그인 시도가 잠시 제한되었습니다.';
    if (error.status === 422) return '입력값을 확인하세요. 비밀번호는 12자 이상이며 아이디를 포함할 수 없습니다.';
    return error.detail.replace(' · ', ' — ');
  }
  return '요청을 처리하지 못했습니다.';
}

export function AccessGate({ session, loading, error, onAuthenticated }: Props) {
  const bootstrap = Boolean(session?.bootstrap_required);
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [projectName, setProjectName] = useState('사내 PoC');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setFormError('');
    try {
      const next = bootstrap
        ? await api.bootstrap({ username, display_name: displayName, password, project_name: projectName })
        : await api.login({ username, password });
      onAuthenticated(next);
    } catch (nextError) {
      setFormError(message(nextError));
    } finally {
      setSubmitting(false);
    }
  }

  return <main className="access-gate">
    <section className="access-gate__card" aria-labelledby="access-title">
      <div className="section-index">AX PREFLIGHT / SECURE WORKSPACE</div>
      <h1 id="access-title">{bootstrap ? '첫 관리자 계정 설정' : '사내 PoC 로그인'}</h1>
      <p>{bootstrap ? '이 컴퓨터의 첫 관리자와 기본 프로젝트를 만듭니다. 이후 자료와 업무는 프로젝트 구성원에게만 보입니다.' : '프로젝트별로 격리된 자료와 승인 업무를 확인합니다.'}</p>
      {loading && <div className="state-message">접근 설정을 확인하는 중…</div>}
      {(error || formError) && <div className="notice notice--danger" role="alert">{error || formError}</div>}
      {!loading && session && <form onSubmit={submit} className="access-gate__form">
        <label><span>아이디</span><input value={username} onInput={(event) => setUsername(event.currentTarget.value)} minLength={3} maxLength={32} autoComplete="username" required /></label>
        {bootstrap && <>
          <label><span>표시 이름</span><input value={displayName} onInput={(event) => setDisplayName(event.currentTarget.value)} maxLength={80} autoComplete="name" required /></label>
          <label><span>기본 프로젝트</span><input value={projectName} onInput={(event) => setProjectName(event.currentTarget.value)} maxLength={80} required /></label>
        </>}
        <label><span>비밀번호</span><input type="password" value={password} onInput={(event) => setPassword(event.currentTarget.value)} minLength={bootstrap ? 12 : 1} maxLength={256} autoComplete={bootstrap ? 'new-password' : 'current-password'} required /><small>{bootstrap ? '12자 이상, 아이디를 포함하지 않도록 설정하세요.' : '세션은 8시간 뒤 자동 만료됩니다.'}</small></label>
        <button className="primary-action" disabled={submitting}>{submitting ? '확인 중…' : bootstrap ? '관리자와 프로젝트 만들기 →' : '로그인 →'}</button>
      </form>}
      <div className="access-gate__boundary"><strong>보안 경계</strong><span>Argon2id 비밀번호 해시 · 서버 세션 · CSRF 방어 · 프로젝트 권한 검사</span></div>
    </section>
  </main>;
}
