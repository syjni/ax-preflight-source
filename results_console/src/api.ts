import type { BatchCreateRequest, BatchStatus, DatasetsResponse, DeliveryEnvelope, EvidenceCheckResult, FeaturedCase, FeaturedCasesResponse, FeaturedRunReference, FindingsResponse, OnboardingAssessment, ReadinessResponse, RetrievalTrace, RunRequest, RunningRun, TasksResponse } from './generated/api';

export type RunResult = RunningRun | DeliveryEnvelope;
export type { FeaturedCase, FeaturedRunReference };

export class ApiError extends Error {
  constructor(readonly status: number, readonly detail: string) {
    super(detail);
  }
}

const runtimeEnv = import.meta.env ?? {};
const base = (runtimeEnv.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
const staticMode = runtimeEnv.VITE_STATIC_DEMO === 'true';
export const isStaticDemo = staticMode;

type StaticDemoSnapshot = {
  schema_version: 'ax-static-demo-v5';
  read_only: true;
  default_dataset: string;
  featured_cases: FeaturedCase[];
  datasets: DatasetsResponse;
  readiness: Record<string, ReadinessResponse>;
  onboarding: Record<string, OnboardingAssessment>;
  tasks: Record<string, TasksResponse>;
  findings: Record<string, FindingsResponse>;
  runs: Record<string, RunResult>;
  evidence: Record<string, EvidenceCheckResult>;
  retrieval_traces: Record<string, RetrievalTrace>;
};

let staticSnapshotPromise: Promise<StaticDemoSnapshot> | null = null;

async function loadStaticSnapshot(): Promise<StaticDemoSnapshot> {
  if (!staticSnapshotPromise) {
    staticSnapshotPromise = fetch(`${runtimeEnv.BASE_URL ?? '/'}static-demo.json`)
      .then(async (response) => {
        if (!response.ok) throw new ApiError(response.status, `HTTP_${response.status}`);
        return await response.json() as StaticDemoSnapshot;
      })
      .catch((error: unknown) => {
        staticSnapshotPromise = null;
        if (error instanceof ApiError) throw error;
        throw new ApiError(0, 'API_CONNECTION_FAILED');
      });
  }
  return staticSnapshotPromise;
}

async function staticLookup<T>(group: 'readiness' | 'onboarding' | 'tasks' | 'findings' | 'runs' | 'evidence' | 'retrieval_traces', key: string): Promise<T> {
  const snapshot = await loadStaticSnapshot();
  const value = snapshot[group][key];
  if (!value) throw new ApiError(404, 'NOT_FOUND');
  return value as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    });
  } catch {
    throw new ApiError(0, 'API_CONNECTION_FAILED');
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError(response.status, 'INVALID_API_RESPONSE');
  }
  if (!response.ok) {
    const detail = typeof body === 'object' && body !== null && 'detail' in body
      ? String(body.detail) : `HTTP_${response.status}`;
    throw new ApiError(response.status, detail);
  }
  return body as T;
}

export const api = {
  datasets: () => staticMode ? loadStaticSnapshot().then((snapshot) => snapshot.datasets) : request<DatasetsResponse>('/api/datasets'),
  featuredCases: () => staticMode
    ? loadStaticSnapshot().then((snapshot) => snapshot.featured_cases)
    : request<FeaturedCasesResponse>('/api/featured-cases').then((response) => response.featured_cases),
  readiness: (dataset: string) => staticMode ? staticLookup<ReadinessResponse>('readiness', dataset) : request<ReadinessResponse>(`/api/readiness/${encodeURIComponent(dataset)}`),
  onboarding: (dataset: string) => staticMode ? staticLookup<OnboardingAssessment>('onboarding', dataset) : request<OnboardingAssessment>(`/api/onboarding/${encodeURIComponent(dataset)}`),
  tasks: (dataset: string) => staticMode ? staticLookup<TasksResponse>('tasks', dataset) : request<TasksResponse>(`/api/tasks/${encodeURIComponent(dataset)}`),
  findings: (dataset: string) => staticMode ? staticLookup<FindingsResponse>('findings', dataset) : request<FindingsResponse>(`/api/findings/${encodeURIComponent(dataset)}`),
  run: (id: string) => staticMode ? staticLookup<RunResult>('runs', id) : request<RunResult>(`/api/runs/${encodeURIComponent(id)}`),
  evidence: (id: string) => staticMode ? staticLookup<EvidenceCheckResult>('evidence', id) : request<EvidenceCheckResult>(`/api/runs/${encodeURIComponent(id)}/evidence-check`),
  retrievalTrace: (id: string) => staticMode ? staticLookup<RetrievalTrace>('retrieval_traces', id) : request<RetrievalTrace>(`/api/runs/${encodeURIComponent(id)}/retrieval-trace`),
  submit: (body: RunRequest) => staticMode
    ? Promise.reject(new ApiError(503, 'RUNNER_UNAVAILABLE'))
    : request<DeliveryEnvelope>('/api/run', { method: 'POST', body: JSON.stringify(body) }),
  createBatch: (body: BatchCreateRequest) => staticMode
    ? Promise.reject(new ApiError(503, 'RUNNER_UNAVAILABLE'))
    : request<BatchStatus>('/api/batches', { method: 'POST', body: JSON.stringify(body) }),
  batch: (id: string) => staticMode
    ? Promise.reject(new ApiError(503, 'RUNNER_UNAVAILABLE'))
    : request<BatchStatus>(`/api/batches/${encodeURIComponent(id)}`),
  pauseBatch: (id: string) => staticMode
    ? Promise.reject(new ApiError(503, 'RUNNER_UNAVAILABLE'))
    : request<BatchStatus>(`/api/batches/${encodeURIComponent(id)}/pause`, { method: 'POST' }),
  resumeBatch: (id: string) => staticMode
    ? Promise.reject(new ApiError(503, 'RUNNER_UNAVAILABLE'))
    : request<BatchStatus>(`/api/batches/${encodeURIComponent(id)}/resume`, { method: 'POST' }),
  cancelBatch: (id: string) => staticMode
    ? Promise.reject(new ApiError(503, 'RUNNER_UNAVAILABLE'))
    : request<BatchStatus>(`/api/batches/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  retryBatch: (id: string) => staticMode
    ? Promise.reject(new ApiError(503, 'RUNNER_UNAVAILABLE'))
    : request<BatchStatus>(`/api/batches/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
};

export function runState(run: RunResult): 'RUNNING' | 'DELIVERED' | 'REJECTED' {
  return 'delivery_status' in run ? run.delivery_status : 'RUNNING';
}
