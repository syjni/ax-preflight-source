import type { FormEvent } from 'react';
import type { DatasetOption, OnboardingAssessment } from '../generated/api';
import type { RunFailure } from '../recovery';
import { RecoveryNotice } from './RecoveryNotice';
import { OnboardingPanel } from './OnboardingPanel';

export type FixtureKey = 'running' | 'answered' | 'abstained' | 'rejected' | 'mismatch' | 'legacy' | 'benchmark';

type RunControlsProps = {
  datasetInput: string;
  datasets: DatasetOption[];
  datasetsLoading: boolean;
  datasetsError: string;
  question: string;
  runInput: string;
  fixture: FixtureKey | null;
  submitting: boolean;
  selectedTaskId: string | null;
  selectedTaskStatus: 'CANDIDATE' | 'VERIFIED' | null;
  failure: RunFailure | null;
  onboarding: OnboardingAssessment | null;
  onboardingLoading: boolean;
  onboardingError: string;
  onDatasetInput: (value: string) => void;
  onQuestion: (value: string) => void;
  onRunInput: (value: string) => void;
  onDatasetSubmit: (event: FormEvent) => void;
  onRunSubmit: (event: FormEvent) => void;
  onLookup: (event: FormEvent) => void;
  onFixture: (value: string) => void;
  onRecover: () => void;
};

export function RunControls(props: RunControlsProps) {
  const disabled = Boolean(props.fixture);
  const datasetDisabled = disabled || props.datasetsLoading || Boolean(props.datasetsError) || props.datasets.length === 0;
  const runBlocked = props.onboardingLoading || Boolean(props.onboardingError) || !props.onboarding?.can_run;
  return <section className="report-section controls-section" id="control" aria-labelledby="controls-title">
    <header className="section-heading"><div><div className="section-index">07 / 조회와 실행</div><h2 id="controls-title">조회와 실행</h2></div></header>
    <OnboardingPanel data={props.onboarding} loading={props.onboardingLoading} error={props.onboardingError} />
    <div className="control-grid">
      <form onSubmit={props.onDatasetSubmit}><label htmlFor="dataset">데이터셋 프로필</label><div><select id="dataset" value={props.datasetInput} onChange={(event) => props.onDatasetInput(event.target.value)} disabled={datasetDisabled} aria-describedby={props.datasetsError ? 'dataset-list-error' : undefined}><option value="" disabled>{props.datasetsLoading ? '데이터셋 목록 불러오는 중…' : '데이터셋을 선택하세요'}</option>{props.datasets.map((option) => <option key={option.profile} value={option.profile}>{option.display_label}</option>)}</select><button disabled={datasetDisabled || !props.datasetInput}>불러오기</button></div>{props.datasetsError && <p id="dataset-list-error" className="control-error" role="alert">{props.datasetsError}</p>}</form>
      <form onSubmit={props.onLookup}><label htmlFor="run-id">기존 실행 ID</label><div><input id="run-id" value={props.runInput} onChange={(event) => props.onRunInput(event.target.value)} placeholder="실행 ID" disabled={disabled} /><button disabled={disabled || !props.runInput.trim()}>조회</button></div></form>
    </div>
    <form className="question-control" onSubmit={props.onRunSubmit}><label htmlFor="question">{props.selectedTaskStatus === 'VERIFIED' ? '선택한 검증 업무' : props.selectedTaskId ? '선택한 업무 후보' : '직접 질문'} <span>{props.selectedTaskStatus === 'VERIFIED' ? '승인된 질문으로 실행' : props.selectedTaskId ? '후보 질문이 입력됨' : '자동 정답 채점 없음'}</span></label><textarea id="question" rows={3} value={props.question} onChange={(event) => props.onQuestion(event.target.value)} placeholder="실제 데이터에 대해 물어볼 질문을 입력하세요" disabled={disabled} /><button className="primary-action" disabled={disabled || props.submitting || runBlocked || !props.datasetInput || !props.question.trim()}>{props.submitting ? '요청 중…' : runBlocked ? '온보딩 확인 필요' : props.selectedTaskStatus === 'VERIFIED' ? '검증 업무 실행 ↗' : '실행 요청 ↗'}</button></form>
    {props.failure && <RecoveryNotice failure={props.failure} onAction={props.onRecover} />}
    <p className="runner-copy">읽기 전용 데모에서는 새 실행 요청이 의도적으로 거부됩니다. 라이브 실행은 Kiro CLI와 모델 자격 증명이 있는 환경에서만 켤 수 있습니다.</p>
    {import.meta.env.DEV && <label className="fixture-control">개발용 화면 상태<select value={props.fixture ?? ''} onChange={(event) => props.onFixture(event.target.value)}><option value="">라이브 API</option><option value="running">실행 중</option><option value="answered">전달됨 · 답변</option><option value="abstained">전달됨 · 보류</option><option value="rejected">실행 거절</option><option value="mismatch">데이터셋 불일치</option><option value="legacy">출처 정보 없음</option><option value="benchmark">실험 결과</option></select></label>}
  </section>;
}
