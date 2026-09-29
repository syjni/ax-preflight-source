import type { AuthSessionResponse, BatchCreateRequest, BatchStatus, BootstrapRequest, CreateUserRequest, DataTransferApprovalRequest, DataTransferApprovalView, DatasetsResponse, DeliveryEnvelope, EvidenceCheckResult, ExecutionPolicyUpdate, FeaturedCase, FeaturedCasesResponse, FeaturedRunReference, FindingsResponse, LocalDatasetDeleteResult, LocalDatasetRequest, LocalDatasetScanResult, LoginRequest, OnboardingAssessment, PocDecisionUpdate, PocEvaluationReport, ProductCapabilities, ProjectAuditLog, ProjectCreateRequest, ProjectDataInventory, ProjectExecutionControl, ProjectExecutionPolicyView, ProjectMemberRequest, ProjectMemberView, ProjectPurgeResult, ProjectRetentionPolicyUpdate, ProjectRetentionPolicyView, ProjectTaskView, ProjectView, ReadinessResponse, RetrievalTrace, RunRequest, RunningRun, SessionRevocationResult, TaskCreateRequest, TasksResponse, UserView } from './generated/api';

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
let csrfToken: string | null = null;

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
    const isForm = typeof FormData !== 'undefined' && init?.body instanceof FormData;
    const method = (init?.method ?? 'GET').toUpperCase();
    const unsafe = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    response = await fetch(`${base}${path}`, {
      ...init,
      credentials: 'same-origin',
      headers: {
        ...(isForm ? {} : { 'Content-Type': 'application/json' }),
        ...(unsafe && csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(0, 'API_CONNECTION_FAILED');
  }
  if (response.status === 204) return undefined as T;
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
  authSession: async (): Promise<AuthSessionResponse> => {
    const session = staticMode
      ? { authentication_required: false, authenticated: true, bootstrap_required: false, user: null, csrf_token: null, expires_at: null }
      : await request<AuthSessionResponse>('/api/auth/session');
    csrfToken = session.csrf_token ?? null;
    return session;
  },
  bootstrap: async (body: BootstrapRequest): Promise<AuthSessionResponse> => {
    const session = await request<AuthSessionResponse>('/api/auth/bootstrap', { method: 'POST', body: JSON.stringify(body) });
    csrfToken = session.csrf_token ?? null;
    return session;
  },
  login: async (body: LoginRequest): Promise<AuthSessionResponse> => {
    const session = await request<AuthSessionResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify(body) });
    csrfToken = session.csrf_token ?? null;
    return session;
  },
  logout: async (): Promise<void> => {
    await request<void>('/api/auth/logout', { method: 'POST' });
    csrfToken = null;
  },
  projects: (): Promise<ProjectView[]> => staticMode ? Promise.resolve([]) : request<ProjectView[]>('/api/projects'),
  createProject: (body: ProjectCreateRequest): Promise<ProjectView> => request<ProjectView>('/api/projects', { method: 'POST', body: JSON.stringify(body) }),
  users: (): Promise<UserView[]> => request<UserView[]>('/api/users'),
  createUser: (body: CreateUserRequest): Promise<UserView> => request<UserView>('/api/users', { method: 'POST', body: JSON.stringify(body) }),
  revokeUserSessions: (userId: string): Promise<SessionRevocationResult> => request<SessionRevocationResult>(`/api/users/${encodeURIComponent(userId)}/revoke-sessions`, { method: 'POST' }),
  projectMembers: (projectId: string): Promise<ProjectMemberView[]> => request<ProjectMemberView[]>(`/api/projects/${encodeURIComponent(projectId)}/members`),
  addProjectMember: (projectId: string, body: ProjectMemberRequest): Promise<ProjectMemberView> => request<ProjectMemberView>(`/api/projects/${encodeURIComponent(projectId)}/members`, { method: 'POST', body: JSON.stringify(body) }),
  removeProjectMember: (projectId: string, userId: string): Promise<void> => request<void>(`/api/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' }),
  projectDataInventory: (projectId: string): Promise<ProjectDataInventory> => request<ProjectDataInventory>(`/api/projects/${encodeURIComponent(projectId)}/data-inventory`),
  projectAuditLog: (projectId: string): Promise<ProjectAuditLog> => request<ProjectAuditLog>(`/api/projects/${encodeURIComponent(projectId)}/audit-log`),
  updateRetentionPolicy: (projectId: string, body: ProjectRetentionPolicyUpdate): Promise<ProjectRetentionPolicyView> => request<ProjectRetentionPolicyView>(`/api/projects/${encodeURIComponent(projectId)}/retention-policy`, { method: 'PUT', body: JSON.stringify(body) }),
  purgeProject: (projectId: string, confirmation: string): Promise<ProjectPurgeResult> => request<ProjectPurgeResult>(`/api/projects/${encodeURIComponent(projectId)}/purge`, { method: 'POST', body: JSON.stringify({ confirmation }) }),
  pocEvaluation: (projectId: string, datasetProfile: string): Promise<PocEvaluationReport> => request<PocEvaluationReport>(`/api/projects/${encodeURIComponent(projectId)}/poc-evaluation?dataset_profile=${encodeURIComponent(datasetProfile)}`),
  recordPocDecision: (projectId: string, datasetProfile: string, body: PocDecisionUpdate): Promise<PocEvaluationReport> => request<PocEvaluationReport>(`/api/projects/${encodeURIComponent(projectId)}/poc-evaluation/decision?dataset_profile=${encodeURIComponent(datasetProfile)}`, { method: 'PUT', body: JSON.stringify(body) }),
  projectExecutionControl: (projectId: string, datasetProfile?: string): Promise<ProjectExecutionControl> => {
    const query = datasetProfile ? `?dataset_profile=${encodeURIComponent(datasetProfile)}` : '';
    return request<ProjectExecutionControl>(`/api/projects/${encodeURIComponent(projectId)}/execution-control${query}`);
  },
  updateExecutionPolicy: (projectId: string, body: ExecutionPolicyUpdate): Promise<ProjectExecutionPolicyView> => request<ProjectExecutionPolicyView>(`/api/projects/${encodeURIComponent(projectId)}/execution-policy`, { method: 'PUT', body: JSON.stringify(body) }),
  approveDataTransfer: (projectId: string, body: DataTransferApprovalRequest): Promise<DataTransferApprovalView> => request<DataTransferApprovalView>(`/api/projects/${encodeURIComponent(projectId)}/data-transfer-approval`, { method: 'POST', body: JSON.stringify(body) }),
  revokeDataTransfer: (projectId: string, datasetProfile: string): Promise<void> => request<void>(`/api/projects/${encodeURIComponent(projectId)}/data-transfer-approval/${encodeURIComponent(datasetProfile)}`, { method: 'DELETE' }),
  projectTasks: (projectId: string, datasetProfile?: string): Promise<ProjectTaskView[]> => {
    const query = datasetProfile ? `?dataset_profile=${encodeURIComponent(datasetProfile)}` : '';
    return request<ProjectTaskView[]>(`/api/projects/${encodeURIComponent(projectId)}/tasks${query}`);
  },
  createProjectTask: (projectId: string, body: TaskCreateRequest): Promise<ProjectTaskView> => request<ProjectTaskView>(`/api/projects/${encodeURIComponent(projectId)}/tasks`, { method: 'POST', body: JSON.stringify(body) }),
  approveProjectTask: (projectId: string, taskId: string): Promise<ProjectTaskView> => request<ProjectTaskView>(`/api/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/approve`, { method: 'POST' }),
  capabilities: (): Promise<ProductCapabilities> => staticMode
    ? Promise.resolve({
        mode: 'STATIC_DEMO',
        local_dataset_scan: false,
        local_file_upload: false,
        ai_task_execution: false,
        bundled_demo: true,
        source_files_stay_local: true,
        supported_extensions: ['.txt', '.pdf', '.docx', '.csv', '.xlsx'],
        max_upload_files: 5000,
        max_upload_bytes: 1073741824,
        pdf_table_extraction: true,
        ocr_available: false,
        ocr_languages: [],
        ocr_install_hint: '로컬 실행에서 OCR 사용 가능 여부를 확인할 수 있습니다.',
      })
    : request<ProductCapabilities>('/api/capabilities'),
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
  createLocalDataset: (body: LocalDatasetRequest) => staticMode
    ? Promise.reject(new ApiError(403, 'LOCAL_SCAN_UNAVAILABLE'))
    : request<LocalDatasetScanResult>('/api/local-datasets', { method: 'POST', body: JSON.stringify(body) }),
  uploadLocalDataset: (
    files: Array<{ file: File; relativePath: string }>,
    displayName: string | null,
    sourceRootName: string,
    projectId: string | null = null,
  ) => {
    if (staticMode) return Promise.reject(new ApiError(403, 'LOCAL_SCAN_UNAVAILABLE'));
    const body = new FormData();
    files.forEach(({ file }) => body.append('files', file, file.name));
    body.append('relative_paths', JSON.stringify(files.map(({ relativePath }) => relativePath)));
    body.append('source_root_name', sourceRootName);
    if (displayName) body.append('display_name', displayName);
    if (projectId) body.append('project_id', projectId);
    return request<LocalDatasetScanResult>('/api/local-datasets/upload', { method: 'POST', body });
  },
  localDataset: (profile: string) => staticMode
    ? Promise.reject(new ApiError(403, 'LOCAL_SCAN_UNAVAILABLE'))
    : request<LocalDatasetScanResult>(`/api/local-datasets/${encodeURIComponent(profile)}`),
  deleteLocalDataset: (profile: string) => staticMode
    ? Promise.reject(new ApiError(403, 'LOCAL_SCAN_UNAVAILABLE'))
    : request<LocalDatasetDeleteResult>(`/api/local-datasets/${encodeURIComponent(profile)}`, { method: 'DELETE' }),
};

export function runState(run: RunResult): 'RUNNING' | 'DELIVERED' | 'REJECTED' {
  return 'delivery_status' in run ? run.delivery_status : 'RUNNING';
}
