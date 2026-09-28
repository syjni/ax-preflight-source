import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, api, runState, type FeaturedCase, type FeaturedRunReference, type RunResult } from './api';
import type { DatasetOption, EvidenceCheckResult, FindingsResponse, OnboardingAssessment, ReadinessResponse, RetrievalTrace, TasksResponse } from './generated/api';
import { assessRunContext } from './provenance';
import { Sidebar } from './components/Sidebar';
import { SummarySection } from './components/SummarySection';
import { ReadinessTable } from './components/ReadinessTable';
import { TaskTable } from './components/TaskTable';
import { FindingCard } from './components/FindingCard';
import { BlockedCard } from './components/BlockedCard';
import { EvidenceCheckPanel } from './components/EvidenceCheckPanel';
import { BenchmarkTab, type BenchmarkDemoReport } from './components/BenchmarkTab';
import { RunControls, type FixtureKey } from './components/RunControls';
import { BatchPanel } from './components/BatchPanel';
import { Status } from './components/Status';
import { ExecutiveReport } from './components/ExecutiveReport';
import { Portal } from './components/Portal';
import { FeaturedCaseJourney } from './components/FeaturedCaseJourney';
import { runFailureFor, type RunFailure } from './recovery';
import { runRequestFor } from './viewModel';

type DemoModule = typeof import('./mock/report');

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail === 'RUNNER_UNAVAILABLE') return 'RUNNER_UNAVAILABLE · 이 요청에서 모델 runner를 사용할 수 없어 결과 run이 생성되지 않았습니다.';
    if (error.detail === 'VERIFIED_TASK_NOT_ONBOARDED') return 'VERIFIED_TASK_NOT_ONBOARDED · 이 데이터셋과 업무에 유효한 승인 기록이 없습니다.';
    if (error.detail === 'API_CONNECTION_FAILED') return 'API 연결 실패 · FastAPI 서버 주소와 실행 상태를 확인하세요.';
    if (error.status === 404) return '찾을 수 없습니다 · dataset 또는 run ID를 확인하세요.';
    return `${error.status || 'API'} · ${error.detail}`;
  }
  return '요청을 처리하지 못했습니다.';
}

const fixtureKeys: FixtureKey[] = ['running', 'answered', 'abstained', 'rejected', 'mismatch', 'legacy', 'benchmark'];
const defaultDatasetProfile = import.meta.env.VITE_DEFAULT_DATASET ?? 'mini';

function comparisonProfile(dataset: string): string | null {
  const pairs: Record<string, string> = {
    'portfolio-hidden-conflict-before': 'portfolio-ceiling-after',
    'portfolio-ceiling-after': 'portfolio-hidden-conflict-before',
    'demo-return-before': 'demo-return-after',
    'demo-return-after': 'demo-return-before',
  };
  return pairs[dataset] ?? null;
}

export default function App() {
  const requestedFixture = import.meta.env.DEV ? new URLSearchParams(location.search).get('fixture') : null;
  const [fixture, setFixture] = useState<FixtureKey | null>(fixtureKeys.includes(requestedFixture as FixtureKey) ? requestedFixture as FixtureKey : null);
  const [demo, setDemo] = useState<DemoModule | null>(null);
  const [activeTab, setActiveTab] = useState<'report' | 'benchmark'>(fixture === 'benchmark' ? 'benchmark' : 'report');
  const [datasetInput, setDatasetInput] = useState('');
  const [dataset, setDataset] = useState('');
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [datasetsError, setDatasetsError] = useState('');
  const [featuredCases, setFeaturedCases] = useState<FeaturedCase[]>([]);
  const [featuredRunLoading, setFeaturedRunLoading] = useState<string | null>(null);
  const [featuredError, setFeaturedError] = useState('');
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [onboarding, setOnboarding] = useState<OnboardingAssessment | null>(null);
  const [onboardingLoading, setOnboardingLoading] = useState(false);
  const [onboardingError, setOnboardingError] = useState('');
  const [tasks, setTasks] = useState<TasksResponse | null>(null);
  const [findings, setFindings] = useState<FindingsResponse | null>(null);
  const [comparisonFindings, setComparisonFindings] = useState<FindingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [readinessError, setReadinessError] = useState('');
  const [findingsError, setFindingsError] = useState('');
  const [question, setQuestion] = useState('');
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [runInput, setRunInput] = useState('');
  const [run, setRun] = useState<RunResult | null>(null);
  const [runFailure, setRunFailure] = useState<RunFailure | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [evidence, setEvidence] = useState<EvidenceCheckResult | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceMissing, setEvidenceMissing] = useState(false);
  const [evidenceError, setEvidenceError] = useState('');
  const [retrievalTrace, setRetrievalTrace] = useState<RetrievalTrace | null>(null);
  const [retrievalTraceLoading, setRetrievalTraceLoading] = useState(false);
  const [retrievalTraceMissing, setRetrievalTraceMissing] = useState(false);
  const [retrievalTraceError, setRetrievalTraceError] = useState('');

  const context = run && dataset ? assessRunContext(dataset, run.dataset) : null;
  const finalRun = run && 'delivery_status' in run ? run : null;
  const benchmarkAvailable = import.meta.env.DEV && fixture === 'benchmark' && demo?.benchmarkReport.mode === 'benchmark';
  const selectedTask = selectedTaskId
    ? tasks?.tasks?.find((item) => item.task_id === selectedTaskId) ?? null
    : null;

  useEffect(() => {
    if (import.meta.env.DEV) void import('./mock/report').then(setDemo);
  }, []);

  useEffect(() => {
    if (fixture) {
      setDatasets([]);
      setFeaturedCases([]);
      setDatasetsLoading(false);
      setDatasetsError('');
      return;
    }
    let active = true;
    setDatasetsLoading(true);
    setDatasetsError('');
    Promise.all([api.datasets(), api.featuredCases()])
      .then(([result, nextFeaturedCases]) => {
        if (!active) return;
        const defaultDataset = result.datasets.find((option) => option.profile === defaultDatasetProfile);
        if (!defaultDataset) {
          setDatasets([]);
          setDataset('');
          setDatasetInput('');
          setDatasetsError(`데이터셋 목록 오류 · 기본 ${defaultDatasetProfile} 프로필이 없습니다.`);
          return;
        }
        setDatasets(result.datasets);
        setFeaturedCases(nextFeaturedCases);
        setDataset(defaultDataset.profile);
        setDatasetInput(defaultDataset.profile);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setDatasets([]);
        setFeaturedCases([]);
        setDataset('');
        setDatasetInput('');
        setDatasetsError(messageFor(error));
      })
      .finally(() => { if (active) setDatasetsLoading(false); });
    return () => { active = false; };
  }, [fixture]);

  useEffect(() => {
    if (fixture) {
      if (!demo) return;
      setDataset('mini');
      setDatasetInput('mini');
      setReadiness(demo.demoReadiness);
      setTasks(demo.demoTasks);
      setFindings(demo.demoFindings[fixture]);
      setComparisonFindings(null);
      setRun(demo.demoRuns[fixture]);
      setRunFailure(null);
      setReadinessError('');
      setFindingsError('');
      setLoading(false);
      return;
    }
    if (!dataset) {
      setLoading(false);
      setReadiness(null);
      setTasks(null);
      setFindings(null);
      setComparisonFindings(null);
      return;
    }
    let active = true;
    setLoading(true);
    setReadiness(null);
    setTasks(null);
    setFindings(null);
    setComparisonFindings(null);
    setReadinessError('');
    setFindingsError('');
    const paired = comparisonProfile(dataset);
    Promise.all([
      api.readiness(dataset),
      api.tasks(dataset),
      api.findings(dataset),
      paired ? api.findings(paired).catch(() => null) : Promise.resolve(null),
    ])
      .then(([nextReadiness, nextTasks, nextFindings, nextComparison]) => {
        if (active) { setReadiness(nextReadiness); setTasks(nextTasks); setFindings(nextFindings); setComparisonFindings(nextComparison); }
      })
      .catch((error: unknown) => { if (active) { setReadinessError(messageFor(error)); setFindingsError(messageFor(error)); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [dataset, fixture, demo]);

  useEffect(() => {
    setOnboarding(null);
    setOnboardingError('');
    if (fixture) {
      setOnboardingLoading(false);
      if (demo) setOnboarding(demo.demoOnboarding);
      return;
    }
    if (!dataset) {
      setOnboardingLoading(false);
      return;
    }
    let active = true;
    setOnboardingLoading(true);
    api.onboarding(dataset)
      .then((result) => { if (active) setOnboarding(result); })
      .catch((error: unknown) => {
        if (active) setOnboardingError(messageFor(error));
      })
      .finally(() => { if (active) setOnboardingLoading(false); });
    return () => { active = false; };
  }, [dataset, fixture, demo]);

  useEffect(() => {
    if (fixture || !run || runState(run) !== 'RUNNING') return;
    const timer = window.setInterval(() => {
      api.run(run.run_id).then((next) => { setRun(next); setRunFailure(null); })
        .catch((error: unknown) => setRunFailure(runFailureFor(error, 'poll')));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [fixture, run]);

  useEffect(() => {
    if (fixture || !finalRun || finalRun.dataset !== dataset) return;
    let active = true;
    api.findings(dataset)
      .then((result) => { if (active) { setFindings(result); setFindingsError(''); } })
      .catch((error: unknown) => { if (active) setFindingsError(messageFor(error)); });
    return () => { active = false; };
  }, [dataset, finalRun?.run_id, fixture]);

  useEffect(() => {
    setEvidence(null);
    setEvidenceError('');
    setEvidenceMissing(false);
    if (!finalRun) { setEvidenceLoading(false); return; }
    if (fixture) {
      setEvidenceLoading(false);
      if (demo && finalRun.delivery_status === 'DELIVERED') {
        setEvidence({ ...demo.demoEvidence, run_id: finalRun.run_id });
      } else {
        setEvidenceMissing(true);
      }
      return;
    }
    let active = true;
    setEvidenceLoading(true);
    api.evidence(finalRun.run_id)
      .then((result) => { if (active) setEvidence(result); })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 404) setEvidenceMissing(true);
        else setEvidenceError(messageFor(error));
      })
      .finally(() => { if (active) setEvidenceLoading(false); });
    return () => { active = false; };
  }, [finalRun?.run_id, fixture, demo]);

  useEffect(() => {
    setRetrievalTrace(null);
    setRetrievalTraceError('');
    setRetrievalTraceMissing(false);
    if (!finalRun || fixture) {
      setRetrievalTraceLoading(false);
      if (fixture && finalRun) {
        if (demo && finalRun.delivery_status === 'DELIVERED') {
          setRetrievalTrace({ ...demo.demoRetrievalTrace, run_id: finalRun.run_id });
        } else {
          setRetrievalTraceMissing(true);
        }
      }
      return;
    }
    let active = true;
    setRetrievalTraceLoading(true);
    api.retrievalTrace(finalRun.run_id)
      .then((result) => { if (active) setRetrievalTrace(result); })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 404) setRetrievalTraceMissing(true);
        else setRetrievalTraceError(messageFor(error));
      })
      .finally(() => { if (active) setRetrievalTraceLoading(false); });
    return () => { active = false; };
  }, [finalRun?.run_id, fixture, demo]);

  function selectDataset(event: FormEvent) {
    event.preventDefault();
    const next = datasetInput.trim();
    if (datasets.some((option) => option.profile === next)) {
      setDataset(next);
      setSelectedTaskId(null);
      setRunFailure(null);
    }
  }

  async function submitQuestion() {
    if (!dataset || !question.trim() || fixture || !onboarding?.can_run) return;
    setSubmitting(true);
    setRunFailure(null);
    setRun(null);
    try {
      const result = await api.submit(runRequestFor(dataset, question, selectedTask));
      setRun(result);
      setRunInput(result.run_id);
    } catch (error) {
      setRunFailure(runFailureFor(error, 'submit'));
    } finally {
      setSubmitting(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void submitQuestion();
  }

  async function lookupRun(runId = runInput.trim()) {
    if (!runId || fixture) return;
    setRunFailure(null);
    setRun(null);
    try {
      const result = await api.run(runId);
      setRun(result);
      setRunInput(result.run_id);
    } catch (error) {
      setRunFailure(runFailureFor(error, 'lookup'));
    }
  }

  function lookup(event: FormEvent) {
    event.preventDefault();
    void lookupRun();
  }

  async function openFeaturedRun(reference: FeaturedRunReference) {
    setFeaturedRunLoading(reference.run_id);
    setFeaturedError('');
    setRunFailure(null);
    setDatasetInput(reference.dataset);
    setDataset(reference.dataset);
    setSelectedTaskId(null);
    setRun(null);
    try {
      const result = await api.run(reference.run_id);
      setRun(result);
      setRunInput(result.run_id);
      window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
        document.getElementById(reference.target)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }));
    } catch (error) {
      setFeaturedError(messageFor(error));
    } finally {
      setFeaturedRunLoading(null);
    }
  }

  function chooseFixture(value: string) {
    const next = fixtureKeys.includes(value as FixtureKey) ? value as FixtureKey : null;
    if (next) {
      setDataset('mini');
      setDatasetInput('mini');
    } else {
      const liveDefault = datasets.find((option) => option.profile === defaultDatasetProfile);
      setDataset(liveDefault?.profile ?? '');
      setDatasetInput(liveDefault?.profile ?? '');
    }
    setFixture(next);
    setActiveTab(next === 'benchmark' ? 'benchmark' : 'report');
    const url = new URL(location.href);
    if (next) url.searchParams.set('fixture', next); else url.searchParams.delete('fixture');
    history.replaceState(null, '', url);
    if (!next) { setRun(null); setRunFailure(null); }
  }

  function recoverRun() {
    if (!runFailure) return;
    if (runFailure.kind === 'runner-unavailable') {
      setRunFailure(null);
      document.getElementById('featured-case')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    if (runFailure.kind === 'run-not-found') {
      setRunFailure(null);
      const input = document.getElementById('run-id') as HTMLInputElement | null;
      input?.focus();
      input?.select();
      return;
    }
    if (runFailure.kind === 'verified-task-not-onboarded' || runFailure.kind === 'candidate-mismatch') {
      setRunFailure(null);
      document.getElementById('tasks')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    if (runFailure.kind === 'onboarding-blocked') {
      setRunFailure(null);
      document.getElementById('onboarding-preflight')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    if (runFailure.source === 'submit') void submitQuestion();
    else void lookupRun(run?.run_id ?? runInput.trim());
  }

  function selectTask(taskId: string) {
    const candidate = tasks?.tasks?.find((item) => item.task_id === taskId);
    if (candidate) {
      setSelectedTaskId(candidate.task_id);
      setQuestion(candidate.question);
      window.requestAnimationFrame(() => document.getElementById('control')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
      return;
    }
    const finding = findings?.findings.find((item) => item.affected_task_ids.includes(taskId));
    window.requestAnimationFrame(() => document.getElementById(finding ? `finding-${finding.finding_id}` : 'findings')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  }

  const benchmark = benchmarkAvailable ? demo?.benchmarkReport as BenchmarkDemoReport : null;
  return <Portal consoleContent={<div className="app-shell">
    <Sidebar activeTab={activeTab} benchmarkAvailable={benchmarkAvailable} onTabChange={setActiveTab} dataset={dataset || '선택 안 됨'} datasetName={readiness?.dataset_name} asOfDate={readiness?.readiness.as_of_date} runId={run?.run_id} />
    {activeTab === 'benchmark' && benchmark ? <BenchmarkTab report={benchmark} /> : <main className="report-main">
      <SummarySection readiness={readiness} findings={findings} run={run} loading={loading} />
      <FeaturedCaseJourney cases={featuredCases} currentDataset={dataset} currentRunId={run?.run_id ?? null} loadingRunId={featuredRunLoading} error={featuredError} onOpen={openFeaturedRun} />
      <ExecutiveReport dataset={dataset} readiness={readiness} findings={findings} comparison={comparisonFindings} />
      {context?.warning && <div className="notice notice--warning page-context" role="alert"><strong>{context.kind === 'UNKNOWN' ? 'RUN DATASET · UNKNOWN' : `RUN DATASET · ${context.origin}`}</strong><span>{context.warning}</span></div>}
      <section className="report-section" id="findings" aria-labelledby="findings-title">
        <header className="section-heading"><div><div className="section-index">03 / 진단 신호</div><h2 id="findings-title">발견된 진단 신호</h2></div><Status tone={findings?.findings.some((item) => item.comparison_status !== 'NOT_REPRODUCED_AFTER') ? 'warning' : 'positive'}>{findings ? `${findings.findings.filter((item) => item.comparison_status !== 'NOT_REPRODUCED_AFTER').length} 열림 · ${findings.findings.filter((item) => item.comparison_status === 'NOT_REPRODUCED_AFTER').length} 수정 후 미재현` : '조회 전'}</Status></header>
        <p className="section-lede">충돌과 반복 보류는 데이터 신호로, 답변·보류가 섞인 업무는 별도 불안정 신호로 구분합니다. 원인이 확인된 경우에는 검색 경로 한계처럼 귀속을 명시하며, 고유 업무 수와 반복 실행 수는 별도로 표시합니다.</p>
        {findingsError && <div className="notice notice--danger" role="alert">{findingsError}</div>}
        {run && runState(run) === 'RUNNING' && <div className="running-state"><span aria-hidden="true" /><div><strong>실행 중</strong><p>최종 DeliveryEnvelope가 저장될 때까지 같은 run을 조회합니다.</p><code>{run.run_id}</code></div></div>}
        {findings && findings.findings.length === 0 && <div className="state-message">현재 관측된 실행에서 구조화된 진단 신호를 찾지 못했습니다.</div>}
        {findings?.findings.map((finding, index) => <FindingCard key={finding.finding_id} finding={finding} index={index} />)}
        {finalRun?.delivery_status === 'REJECTED' && context && <BlockedCard delivery={finalRun} context={context} fixture={Boolean(fixture)} />}
      </section>
      <ReadinessTable data={readiness} loading={loading} error={readinessError} />
      <TaskTable data={tasks} error={readinessError} activeTaskId={finalRun?.task_id ?? null} onTaskSelect={selectTask} />
      <EvidenceCheckPanel data={evidence} loading={evidenceLoading} missing={evidenceMissing} error={evidenceError} trace={retrievalTrace} traceLoading={retrievalTraceLoading} traceMissing={retrievalTraceMissing} traceError={retrievalTraceError} />
      <RunControls datasetInput={datasetInput} datasets={datasets} datasetsLoading={datasetsLoading} datasetsError={datasetsError} question={question} runInput={runInput} fixture={fixture} submitting={submitting} selectedTaskId={selectedTaskId} selectedTaskStatus={selectedTask?.status ?? null} failure={runFailure} onboarding={onboarding} onboardingLoading={onboardingLoading} onboardingError={onboardingError} onDatasetInput={setDatasetInput} onQuestion={(value) => { setQuestion(value); setSelectedTaskId(null); }} onRunInput={setRunInput} onDatasetSubmit={selectDataset} onRunSubmit={submit} onLookup={lookup} onFixture={chooseFixture} onRecover={recoverRun} />
      <BatchPanel dataset={dataset} tasks={tasks} canRun={Boolean(onboarding?.can_run)} fixture={Boolean(fixture)} fixtureBatch={fixture ? demo?.demoBatch ?? null : null} onOpenRun={(runId) => void lookupRun(runId)} />
      {import.meta.env.DEV && fixture && <div className="dev-banner" role="status"><strong>DEV FIXTURE</strong><span>합성 화면 검증 모드이며 실제 고객 결과가 아닙니다.</span><button onClick={() => chooseFixture('')}>라이브 API로 돌아가기</button></div>}
      <footer className="report-footer">AX Preflight <span>·</span> Results Console <span>·</span> 읽기 전용 진단 화면</footer>
    </main>}
  </div>} />;
}
