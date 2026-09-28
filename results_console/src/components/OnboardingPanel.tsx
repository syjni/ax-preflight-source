import type { OnboardingAssessment, OnboardingCheck } from '../generated/api';
import { Status, type Tone } from './Status';

const checkCopy: Record<OnboardingCheck['code'], {
  title: string;
  metric: (check: OnboardingCheck) => string;
  action: string;
}> = {
  DATASET_INTEGRITY: {
    title: '데이터 원본 무결성',
    metric: ({ observed }) => observed == null ? '검증 실패' : `${observed}개 파일 일치`,
    action: '원본과 스캔 보고서의 경로·해시·파일 목록을 다시 맞추세요.',
  },
  PARSE_COVERAGE: {
    title: '문서 파싱 범위',
    metric: ({ observed, total }) => observed == null ? '확인 불가' : `${observed} / ${total ?? '—'}개 파싱`,
    action: '미파싱·OCR 필요 파일을 처리한 뒤 다시 스캔하세요.',
  },
  RETRIEVAL_SURFACE: {
    title: '검색 가능한 자료',
    metric: ({ observed }) => `${observed ?? 0}개 검색 단위`,
    action: '본문 또는 표가 검색 인덱스에 포함되도록 파서와 스캔 결과를 확인하세요.',
  },
  RUNTIME_RESOURCE_LEAKAGE: {
    title: '평가 정보 분리',
    metric: ({ observed }) => observed == null ? '검사 실패' : `금지 표식 ${observed}건`,
    action: '정답·평가 기준·도구 계획을 런타임 자료에서 분리하세요.',
  },
  BUSINESS_TASK_REVIEW: {
    title: '업무 승인 범위',
    metric: ({ observed, total }) => `검증 ${observed ?? 0} / 전체 ${total ?? 0}개`,
    action: '업무 담당자가 질문과 성공 기준을 확인한 뒤 검증 업무로 승격하세요.',
  },
};

const checkStatus: Record<OnboardingCheck['status'], { label: string; tone: Tone }> = {
  PASS: { label: '통과', tone: 'positive' },
  WARN: { label: '확인 필요', tone: 'warning' },
  BLOCK: { label: '차단', tone: 'danger' },
};

const assessmentStatus: Record<OnboardingAssessment['status'], { label: string; tone: Tone }> = {
  READY: { label: '실행 준비 완료', tone: 'positive' },
  REVIEW_REQUIRED: { label: '검토 후 실행 가능', tone: 'warning' },
  BLOCKED: { label: '실행 차단', tone: 'danger' },
};

export function OnboardingPanel({ data, loading, error }: {
  data: OnboardingAssessment | null;
  loading: boolean;
  error: string;
}) {
  const overall = data ? assessmentStatus[data.status] : null;
  return <div className="onboarding-panel" id="onboarding-preflight" aria-labelledby="onboarding-title" aria-live="polite">
    <div className="onboarding-panel__heading">
      <div><span>ONBOARDING PREFLIGHT</span><h3 id="onboarding-title">실행 전 데이터 검사</h3></div>
      {overall && <Status tone={overall.tone}>{overall.label}</Status>}
    </div>
    <p>원본 무결성, 파싱 범위, 검색 가능 자료, 평가 정보 분리와 데이터셋별 업무 승인 범위를 실행 전에 확인합니다.</p>
    {loading && <div className="state-message">온보딩 상태를 검사하는 중…</div>}
    {error && <div className="notice notice--danger" role="alert"><strong>온보딩 검사를 완료하지 못했습니다</strong><span>{error}</span></div>}
    {!data && !loading && !error && <div className="state-message">데이터셋을 선택하면 실행 전 검사를 시작합니다.</div>}
    {data && <>
      <div className="onboarding-panel__summary">
        <strong>{data.can_run ? '실행 가능' : '실행 불가'}</strong>
        <span>차단 {data.blocker_count} · 확인 {data.warning_count}</span>
      </div>
      <ol className="onboarding-checks">
        {data.checks.map((check, index) => {
          const copy = checkCopy[check.code];
          const state = checkStatus[check.status];
          return <li key={check.code} className={`is-${check.status.toLowerCase()}`}>
            <span className="mono">{String(index + 1).padStart(2, '0')}</span>
            <div><strong>{copy.title}</strong><small>{copy.metric(check)}</small></div>
            <Status tone={state.tone}>{state.label}</Status>
            {check.status !== 'PASS' && <p>{copy.action}</p>}
          </li>;
        })}
      </ol>
    </>}
  </div>;
}
