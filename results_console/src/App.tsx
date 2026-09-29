import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, api, runState, type FeaturedCase, type FeaturedRunReference, type RunResult } from './api';
import type { AuthSessionResponse, DatasetOption, EvidenceCheckResult, FindingsResponse, LocalDatasetScanResult, OnboardingAssessment, ProductCapabilities, ProjectExecutionControl, ProjectPurgeResult, ProjectView, ReadinessResponse, RetrievalTrace, TasksResponse } from './generated/api';
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
import { LocalDatasetPanel } from './components/LocalDatasetPanel';
import { AccessGate } from './components/AccessGate';
import { WorkspacePanel } from './components/WorkspacePanel';
import { PocEvaluationPanel } from './components/PocEvaluationPanel';

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
  const [session, setSession] = useState<AuthSessionResponse | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState('');
  const [projects, setProjects] = useState<ProjectView[]>([]);
  const [projectId, setProjectId] = useState('');
  const [tasksRevision, setTasksRevision] = useState(0);
  const [demo, setDemo] = useState<DemoModule | null>(null);
  const [activeTab, setActiveTab] = useState<'report' | 'benchmark'>(fixture === 'benchmark' ? 'benchmark' : 'report');
  const [datasetInput, setDatasetInput] = useState('');
  const [dataset, setDataset] = useState('');
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [datasetsError, setDatasetsError] = useState('');
  const [capabilities, setCapabilities] = useState<ProductCapabilities | null>(null);
  const [capabilitiesError, setCapabilitiesError] = useState('');
  const [featuredCases, setFeaturedCases] = useState<FeaturedCase[]>([]);
  const [featuredRunLoading, setFeaturedRunLoading] = useState<string | null>(null);
  const [featuredError, setFeaturedError] = useState('');
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [onboarding, setOnboarding] = useState<OnboardingAssessment | null>(null);
  const [onboardingLoading, setOnboardingLoading] = useState(false);
  const [onboardingError, setOnboardingError] = useState('');
  const [executionControl, setExecutionControl] = useState<ProjectExecutionControl | null>(null);
  const [executionControlLoading, setExecutionControlLoading] = useState(false);
  const [executionControlError, setExecutionControlError] = useState('');
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
  const [purgeReceipt, setPurgeReceipt] = useState<ProjectPurgeResult | null>(null);
  const [purgeRetrying, setPurgeRetrying] = useState(false);
  const [purgeRetryError, setPurgeRetryError] = useState('');

  const context = run && dataset ? assessRunContext(dataset, run.dataset) : null;
  const finalRun = run && 'delivery_status' in run ? run : null;
  const benchmarkAvailable = import.meta.env.DEV && fixture === 'benchmark' && demo?.benchmarkReport.mode === 'benchmark';
  const selectedTask = selectedTaskId
    ? tasks?.tasks?.find((item) => item.task_id === selectedTaskId) ?? null
    : null;
  const selectedDataset = datasets.find((option) => option.profile === dataset) ?? null;
  const selectedProject = projects.find((project) => project.project_id === projectId) ?? null;
  const selectedDatasetProject = selectedDataset?.origin === 'LOCAL'
    ? projects.find((project) => project.project_id === selectedDataset.project_id) ?? null
    : null;
  const accessGranted = Boolean(fixture || session?.authentication_required === false || session?.authenticated);
  const customerExecutionReady = selectedDataset?.origin === 'LOCAL' && Boolean(executionControl?.can_execute);
  const canExecute = Boolean(onboarding?.can_run && capabilities?.ai_task_execution && customerExecutionReady);
  const executionModel = selectedDataset?.origin === 'LOCAL' ? executionControl?.policy?.model : undefined;

  useEffect(() => {
    if (import.meta.env.DEV) void import('./mock/report').then(setDemo);
  }, []);

  useEffect(() => {
    if (fixture) {
      setSession({ authentication_required: false, authenticated: true, bootstrap_required: false, user: null, csrf_token: null, expires_at: null });
      setAuthLoading(false);
      return;
    }
    let active = true;
    setAuthLoading(true);
    setAuthError('');
    api.authSession()
      .then((next) => { if (active) setSession(next); })
      .catch((error: unknown) => { if (active) setAuthError(messageFor(error)); })
      .finally(() => { if (active) setAuthLoading(false); });
    return () => { active = false; };
  }, [fixture]);

  useEffect(() => {
    if (!session?.authentication_required || !session.authenticated) {
      setProjects([]);
      setProjectId('');
      return;
    }
    let active = true;
    api.projects()
      .then((next) => {
        if (!active) return;
        setProjects(next);
        setProjectId((current) => next.some((project) => project.project_id === current) ? current : next[0]?.project_id ?? '');
      })
      .catch((error: unknown) => { if (active) setAuthError(messageFor(error)); });
    return () => { active = false; };
  }, [session?.authentication_required, session?.authenticated]);

  useEffect(() => {
    if (!accessGranted) {
      setCapabilities(null);
      setCapabilitiesError('');
      return;
    }
    if (fixture) {
      setCapabilities(null);
      setCapabilitiesError('');
      return;
    }
    let active = true;
    setCapabilitiesError('');
    api.capabilities()
      .then((result) => { if (active) setCapabilities(result); })
      .catch((error: unknown) => {
        if (active) {
          setCapabilities(null);
          setCapabilitiesError(messageFor(error));
        }
      });
    return () => { active = false; };
  }, [fixture, accessGranted]);

  useEffect(() => {
    if (!accessGranted) {
      setDatasets([]);
      setFeaturedCases([]);
      setDatasetsLoading(false);
      setDatasetsError('');
      return;
    }
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
  }, [fixture, accessGranted]);

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
  }, [dataset, fixture, demo, tasksRevision]);

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
    if (
      fixture
      || !session?.authenticated
      || !selectedProject
      || selectedDataset?.origin !== 'LOCAL'
      || selectedDataset.project_id !== selectedProject.project_id
    ) {
      setExecutionControl(null);
      setExecutionControlLoading(false);
      setExecutionControlError('');
      return;
    }
    let active = true;
    setExecutionControlLoading(true);
    setExecutionControlError('');
    api.projectExecutionControl(selectedProject.project_id, selectedDataset.profile)
      .then((result) => { if (active) setExecutionControl(result); })
      .catch((error: unknown) => {
        if (active) {
          setExecutionControl(null);
          setExecutionControlError(messageFor(error));
        }
      })
      .finally(() => { if (active) setExecutionControlLoading(false); });
    return () => { active = false; };
  }, [fixture, session?.authenticated, selectedProject?.project_id, selectedDataset?.profile, selectedDataset?.project_id, selectedDataset?.origin]);

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
    const option = datasets.find((candidate) => candidate.profile === next);
    if (option) {
      setDataset(next);
      if (option.origin === 'LOCAL' && option.project_id) setProjectId(option.project_id);
      setSelectedTaskId(null);
      setRunFailure(null);
    }
  }

  function localDatasetScanned(result: LocalDatasetScanResult) {
    setDatasets((current) => [
      ...current.filter((option) => option.profile !== result.dataset.profile),
      result.dataset,
    ]);
    setDatasetInput(result.dataset.profile);
    setDataset(result.dataset.profile);
    setSelectedTaskId(null);
    setRun(null);
    setRunFailure(null);
    setTasksRevision((value) => value + 1);
  }

  function localDatasetDeleted(profile: string) {
    setDatasets((current) => current.filter((option) => option.profile !== profile));
    setTasksRevision((value) => value + 1);
    if (dataset !== profile) return;
    const fallback = datasets.find((option) => option.profile === defaultDatasetProfile);
    setDataset(fallback?.profile ?? '');
    setDatasetInput(fallback?.profile ?? '');
    setSelectedTaskId(null);
    setRun(null);
    setRunFailure(null);
  }

  function selectProject(nextProjectId: string) {
    setProjectId(nextProjectId);
    if (selectedDataset?.origin === 'LOCAL' && selectedDataset.project_id !== nextProjectId) {
      const fallback = datasets.find((option) => option.profile === defaultDatasetProfile);
      setDataset(fallback?.profile ?? '');
      setDatasetInput(fallback?.profile ?? '');
    }
  }

  function projectCreated(project: ProjectView) {
    setProjects((current) => [...current, project]);
    setProjectId(project.project_id);
  }

  function projectPurged(result: ProjectPurgeResult) {
    setPurgeReceipt(result);
    setPurgeRetryError('');
    if (!result.project_deleted) return;
    const remainingProjects = projects.filter((project) => project.project_id !== result.project_id);
    const remainingDatasets = datasets.filter((option) => option.project_id !== result.project_id);
    const fallback = remainingDatasets.find((option) => option.profile === defaultDatasetProfile) ?? remainingDatasets[0];
    setProjects(remainingProjects);
    setProjectId(remainingProjects[0]?.project_id ?? '');
    setDatasets(remainingDatasets);
    setDataset(fallback?.profile ?? '');
    setDatasetInput(fallback?.profile ?? '');
    setSelectedTaskId(null);
    setRun(null);
    setRunFailure(null);
    setTasksRevision((value) => value + 1);
  }

  async function retryProjectPurge() {
    if (!purgeReceipt || purgeReceipt.deletion_status === 'COMPLETED' || purgeRetrying) return;
    setPurgeRetrying(true);
    setPurgeRetryError('');
    try {
      projectPurged(await api.purgeProject(
        purgeReceipt.project_id,
        purgeReceipt.project_name,
        purgeReceipt.operation_id,
      ));
    } catch (error) {
      setPurgeRetryError(messageFor(error));
    } finally {
      setPurgeRetrying(false);
    }
  }

  async function logout() {
    try { await api.logout(); } finally {
      setSession({ authentication_required: true, authenticated: false, bootstrap_required: false, user: null, csrf_token: null, expires_at: null });
      setProjects([]);
      setProjectId('');
      setDatasets([]);
      setDataset('');
    }
  }

  async function refreshExecutionControl() {
    if (
      !selectedProject
      || selectedDataset?.origin !== 'LOCAL'
      || selectedDataset.project_id !== selectedProject.project_id
    ) return;
    setExecutionControlLoading(true);
    setExecutionControlError('');
    try {
      setExecutionControl(await api.projectExecutionControl(selectedProject.project_id, selectedDataset.profile));
    } catch (error) {
      setExecutionControlError(messageFor(error));
      throw error;
    } finally {
      setExecutionControlLoading(false);
    }
  }

  async function submitQuestion() {
    if (!dataset || !question.trim() || fixture || !canExecute) return;
    setSubmitting(true);
    setRunFailure(null);
    setRun(null);
    try {
      const result = await api.submit(runRequestFor(dataset, question, selectedTask, executionModel));
      setRun(result);
      setRunInput(result.run_id);
      if (selectedDataset?.origin === 'LOCAL') void refreshExecutionControl().catch(() => undefined);
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
    if (runFailure.kind === 'execution-control') {
      setRunFailure(null);
      document.getElementById('execution-control')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
  if (authLoading || (session?.authentication_required && !session.authenticated)) {
    return <AccessGate session={session} loading={authLoading} error={authError} onAuthenticated={(next) => { setSession(next); setAuthError(''); }} />;
  }
  return <Portal consoleContent={<div className="app-shell">
    <Sidebar activeTab={activeTab} benchmarkAvailable={benchmarkAvailable} onTabChange={setActiveTab} dataset={dataset || '선택 안 됨'} datasetName={readiness?.dataset_name} asOfDate={readiness?.readiness.as_of_date} runId={run?.run_id} />
    {activeTab === 'benchmark' && benchmark ? <BenchmarkTab report={benchmark} /> : <main className="report-main">
      {session?.authentication_required && session.user && <WorkspacePanel user={session.user} projects={projects} selectedProject={selectedProject} selectedDataset={selectedDataset} onProjectSelect={selectProject} onProjectCreated={projectCreated} onTasksChanged={() => setTasksRevision((value) => value + 1)} executionControl={executionControl} executionControlLoading={executionControlLoading} executionControlError={executionControlError} onExecutionControlRefresh={refreshExecutionControl} governanceRevision={tasksRevision} onProjectPurged={projectPurged} onLogout={() => void logout()} />}
      {purgeReceipt && <div className={`purge-receipt ${purgeReceipt.deletion_status === 'PARTIAL_FAILURE' ? 'purge-receipt--partial' : ''}`} role="status"><div><span className="mono">{purgeReceipt.deletion_status === 'COMPLETED' ? 'PURGE VERIFIED' : 'PURGE PARTIAL'}</span><strong>{purgeReceipt.project_name} {purgeReceipt.deletion_status === 'COMPLETED' ? '관리 데이터 삭제·검증 완료' : '부분 삭제 영수증'}</strong><p>{purgeReceipt.deletion_status === 'COMPLETED' ? `데이터셋 ${purgeReceipt.local_datasets_deleted} · 업무 ${purgeReceipt.business_tasks_deleted} · 실행 ${purgeReceipt.writable_runs_deleted} · 반복 ${purgeReceipt.batches_deleted}건의 삭제를 확인했습니다. 원본 파일과 최소 감사 tombstone은 유지했습니다.` : `${purgeReceipt.failure_detail ?? '삭제 작업을 마치지 못했습니다.'} 남은 항목: ${purgeReceipt.remaining_records.join(', ')}`}</p>{purgeRetryError && <p className="notice notice--danger">{purgeRetryError}</p>}<code>{purgeReceipt.operation_id}</code>{purgeReceipt.deletion_status === 'PARTIAL_FAILURE' && <button type="button" onClick={() => void retryProjectPurge()} disabled={purgeRetrying}>{purgeRetrying ? '재개 중…' : '같은 작업 재개'}</button>}</div><button type="button" onClick={() => setPurgeReceipt(null)} aria-label="삭제 영수증 닫기">×</button></div>}
      <LocalDatasetPanel capabilities={capabilities} capabilitiesError={capabilitiesError} selectedDataset={selectedDataset} projectId={selectedProject?.project_id ?? null} projectRequired={Boolean(session?.authentication_required)} canDelete={!session?.authentication_required || selectedDatasetProject?.member_role === 'OWNER'} onScanned={localDatasetScanned} onDeleted={localDatasetDeleted} />
      <SummarySection readiness={readiness} findings={findings} run={run} loading={loading} />
      <FeaturedCaseJourney cases={featuredCases} currentDataset={dataset} currentRunId={run?.run_id ?? null} loadingRunId={featuredRunLoading} error={featuredError} onOpen={openFeaturedRun} />
      <ExecutiveReport dataset={dataset} readiness={readiness} findings={findings} comparison={comparisonFindings} />
      {session?.authentication_required && <PocEvaluationPanel project={selectedProject} dataset={selectedDataset} revision={`${tasksRevision}:${run?.run_id ?? ''}:${executionControl?.policy?.updated_at ?? ''}`} />}
      {context?.warning && <div className="notice notice--warning page-context" role="alert"><strong>{context.kind === 'UNKNOWN' ? 'RUN DATASET · UNKNOWN' : `RUN DATASET · ${context.origin}`}</strong><span>{context.warning}</span></div>}
      <section className="report-section" id="findings" aria-labelledby="findings-title">
        <header className="section-heading"><div><div className="section-index">03 / 진단 신호</div><h2 id="findings-title">발견된 진단 신호</h2></div><Status tone={findings?.findings.some((item) => item.comparison_status !== 'NOT_REPRODUCED_AFTER') ? 'warning' : 'positive'}>{findings ? `${findings.findings.filter((item) => item.comparison_status !== 'NOT_REPRODUCED_AFTER').length} 열림 · ${findings.findings.filter((item) => item.comparison_status === 'NOT_REPRODUCED_AFTER').length} 수정 후 미재현` : '조회 전'}</Status></header>
        <p className="section-lede">충돌과 반복 보류는 데이터 신호로, 답변·보류가 섞인 업무는 별도 불안정 신호로 구분합니다. 원인이 확인된 경우에는 검색 경로 한계처럼 귀속을 명시하며, 고유 업무 수와 반복 실행 수는 별도로 표시합니다.</p>
        {findingsError && <div className="notice notice--danger" role="alert">{findingsError}</div>}
        {run && runState(run) === 'RUNNING' && <div className="running-state"><span aria-hidden="true" /><div><strong>실행 중</strong><p>최종 DeliveryEnvelope가 저장될 때까지 같은 run을 조회합니다.</p><code>{run.run_id}</code></div></div>}
        {findings && findings.findings.length === 0 && <div className="state-message">현재 관측된 실행에서 구조화된 진단 신호를 찾지 못했습니다.</div>}
        {findings?.findings.map((finding, index) => <FindingCard key={finding.finding_id} finding={finding} index={index} />)}
        {finalRun?.delivery_status === 'REJECTED' && context && <BlockedCard delivery={finalRun} context={context} fixture={Boolean(fixture)} onRetry={() => { setRun(null); setRunInput(''); document.getElementById('control')?.scrollIntoView({ behavior: 'smooth' }); }} />}
      </section>
      <ReadinessTable data={readiness} loading={loading} error={readinessError} />
      <TaskTable data={tasks} error={readinessError} activeTaskId={finalRun?.task_id ?? null} onTaskSelect={selectTask} />
      <EvidenceCheckPanel data={evidence} loading={evidenceLoading} missing={evidenceMissing} error={evidenceError} trace={retrievalTrace} traceLoading={retrievalTraceLoading} traceMissing={retrievalTraceMissing} traceError={retrievalTraceError} />
      <RunControls datasetInput={datasetInput} datasets={datasets} datasetsLoading={datasetsLoading} datasetsError={datasetsError} question={question} runInput={runInput} fixture={fixture} submitting={submitting} aiTaskExecution={Boolean(capabilities?.ai_task_execution)} executionControl={selectedDataset?.origin === 'LOCAL' ? executionControl : null} executionControlLoading={executionControlLoading} selectedTaskId={selectedTaskId} selectedTaskStatus={selectedTask?.status ?? null} failure={runFailure} onboarding={onboarding} onboardingLoading={onboardingLoading} onboardingError={onboardingError} onDatasetInput={setDatasetInput} onQuestion={(value) => { setQuestion(value); setSelectedTaskId(null); }} onRunInput={setRunInput} onDatasetSubmit={selectDataset} onRunSubmit={submit} onLookup={lookup} onFixture={chooseFixture} onRecover={recoverRun} />
      <BatchPanel dataset={dataset} tasks={tasks} canRun={canExecute} fixture={Boolean(fixture)} fixtureBatch={fixture ? demo?.demoBatch ?? null : null} model={executionModel} executionControl={selectedDataset?.origin === 'LOCAL' ? executionControl : null} onUsageChanged={() => { if (selectedDataset?.origin === 'LOCAL') void refreshExecutionControl().catch(() => undefined); }} onOpenRun={(runId) => void lookupRun(runId)} />
      {import.meta.env.DEV && fixture && <div className="dev-banner" role="status"><strong>DEV FIXTURE</strong><span>합성 화면 검증 모드이며 실제 고객 결과가 아닙니다.</span><button onClick={() => chooseFixture('')}>라이브 API로 돌아가기</button></div>}
      <footer className="report-footer">AX Preflight <span>·</span> Results Console <span>·</span> 로컬 자료 점검과 검증된 예시</footer>
    </main>}
  </div>} />;
}
