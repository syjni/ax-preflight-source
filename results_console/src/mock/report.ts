import type { BatchStatus, DeliveryEnvelope, EvidenceCheckResult, FindingsResponse, OnboardingAssessment, ReadinessResponse, RetrievalTrace, RunningRun, TasksResponse } from '../generated/api';
import type { BenchmarkDemoReport } from '../components/BenchmarkTab';

// DEV-only fixtures. App.tsx reaches this module solely through an import.meta.env.DEV guarded dynamic import.
export const demoReadiness: ReadinessResponse = {
  dataset: 'mini',
  dataset_name: 'SAMPLE_ORG_NORTHSTAR',
  readiness: {
    schema_version: 'ax-readiness-score-v1', readiness_score: 62,
    dimensions: { accessibility: 0.83, completeness: 0.66, redundancy: 0.48, timeliness: 0.61, safety: 0.72 },
    dimension_weights: { accessibility: 0.2, completeness: 0.2, redundancy: 0.2, timeliness: 0.2, safety: 0.2 },
    counts: {
      accessibility: { total_files: 48, parsed_files: 45, ocr_required_files: 3, accessible_files: 40 },
      completeness: { eligible_tables: 12, total_cells: 428, estimated_missing_cells: 22 },
      redundancy: { total_files: 48, exact_duplicate_groups: 4, redundant_files: 9 },
      timeliness: { files_with_valid_modified_at: 45, non_stale_files: 36, stale_files: 9, future_timestamp_files: 0, missing_timestamp_files: 3, invalid_timestamp_files: 0 },
      safety: { total_files: 48, pii_affected_files: 6, files_without_detected_pii: 42 },
    },
    as_of_date: '2026-09-18', stale_threshold_days: 365,
    flags: { empty_file_set: false, completeness_not_applicable: false, no_valid_modified_at: false, missing_modified_at_count: 3, invalid_modified_at_count: 0, future_modified_at_count: 0, unknown_ocr_file_id_count: 0, unknown_pii_file_id_count: 0, scan_metadata_file_count_mismatch: false },
  },
  unscored_observations: [{ code: 'PROBABLE_VERSION_GROUP', severity: 'warning', message: 'DEV fixture probable version group.', file_ids: ['FILE_DEMO_01', 'FILE_DEMO_02'] }],
};

export const demoTasks: TasksResponse = { dataset: 'mini', catalog_status: 'VERIFIED_TASKS_AVAILABLE', tasks: [
  { task_id: 'TASK_POLICY_RETURN_WINDOW', category: '정책', question: '현재 반품 가능 기간은 며칠인가요?', description: 'DEV fixture 검증 업무입니다.', status: 'VERIFIED', approval: { approval_id: 'DEV_FIXTURE_APPROVAL', owner_role: '정책 운영 담당자', success_criteria: ['현행 기간과 근거를 함께 반환'], approval_scope: 'CONTROLLED_DEMO', approved_by_role: 'DEV fixture 운영자', approved_at: '2026-09-28' } },
  { task_id: 'TASK_ORDER_MONTHLY_AMOUNT', category: '주문', question: '이번 달 주문금액은 얼마인가요?', description: 'DEV fixture 업무 테스트 후보입니다.', status: 'CANDIDATE', approval: null },
] };

export const demoOnboarding: OnboardingAssessment = {
  schema_version: 'ax-onboarding-assessment-v1',
  dataset: 'mini', dataset_name: 'SAMPLE_ORG_NORTHSTAR',
  status: 'REVIEW_REQUIRED', can_run: true, blocker_count: 0, warning_count: 2,
  checks: [
    { code: 'DATASET_INTEGRITY', status: 'PASS', observed: 48, total: 48 },
    { code: 'PARSE_COVERAGE', status: 'WARN', observed: 45, total: 48 },
    { code: 'RETRIEVAL_SURFACE', status: 'PASS', observed: 57, total: null },
    { code: 'RUNTIME_RESOURCE_LEAKAGE', status: 'PASS', observed: 0, total: 49 },
    { code: 'BUSINESS_TASK_REVIEW', status: 'WARN', observed: 1, total: 2 },
  ],
};

export const demoBatch: BatchStatus = {
  schema_version: 'ax-batch-status-v1',
  batch_id: 'demo-batch-safe-point', dataset: 'mini', model: 'demo-model',
  state: 'PAUSED', requested_control: 'PAUSE', repetitions: 2, max_attempts: 2,
  created_at: '2026-09-28T02:10:00Z', updated_at: '2026-09-28T02:12:00Z',
  total_items: 4, completed_items: 3, succeeded_items: 2, failed_items: 1,
  cancelled_items: 0, running_items: 0, queued_items: 1, progress_percent: 75,
  items: [
    { item_id: 't01-r01', task_id: 'TASK_POLICY_RETURN_WINDOW', task_label: '현재 반품 가능 기간은 며칠인가요?', request_type: 'VERIFIED_BUSINESS_TASK', repetition: 1, attempt: 1, status: 'SUCCEEDED', run_id: 'demo-batch-t01-r01-a1', delivery_status: 'DELIVERED' },
    { item_id: 't01-r02', task_id: 'TASK_POLICY_RETURN_WINDOW', task_label: '현재 반품 가능 기간은 며칠인가요?', request_type: 'VERIFIED_BUSINESS_TASK', repetition: 2, attempt: 1, status: 'SUCCEEDED', run_id: 'demo-batch-t01-r02-a1', delivery_status: 'DELIVERED' },
    { item_id: 't02-r01', task_id: 'TASK_ORDER_MONTHLY_AMOUNT', task_label: '이번 달 주문금액은 얼마인가요?', request_type: 'TASK_CANDIDATE', repetition: 1, attempt: 1, status: 'FAILED', run_id: 'demo-batch-t02-r01-a1', delivery_status: 'REJECTED', error_code: 'RUNTIME_ERROR' },
    { item_id: 't02-r02', task_id: 'TASK_ORDER_MONTHLY_AMOUNT', task_label: '이번 달 주문금액은 얼마인가요?', request_type: 'TASK_CANDIDATE', repetition: 2, attempt: 1, status: 'QUEUED' },
  ],
};

const answered: DeliveryEnvelope = {
  delivery_status: 'DELIVERED', run_id: 'demo-answered', dataset: 'mini', task_id: null, model: 'demo-model',
  payload: { status: 'ANSWERED', answer: 'DEV fixture answer', unit: null, explanation: '합성 UI 검증용 답변입니다.', source_ids: ['SOURCE_DEMO_01'], abstention_reason: null },
  reject_reason: null, source_link_status: 'NOT_CHECKED',
};

export const demoRuns: Record<'running' | 'answered' | 'abstained' | 'rejected' | 'mismatch' | 'legacy' | 'benchmark', RunningRun | DeliveryEnvelope> = {
  running: { run_id: 'demo-running', run_status: 'RUNNING', dataset: 'ceiling' },
  answered,
  abstained: {
    ...answered, run_id: 'demo-abstained',
    payload: { status: 'ABSTAINED', answer: null, unit: null, explanation: '합성 근거 부족 사례입니다.', source_ids: ['SOURCE_DEMO_02'], abstention_reason: 'INSUFFICIENT_EVIDENCE' },
  },
  rejected: { delivery_status: 'REJECTED', run_id: 'demo-rejected', dataset: 'mini', task_id: null, model: 'demo-model', payload: null, reject_reason: 'NO_SUBMISSION', source_link_status: null },
  mismatch: { ...answered, run_id: 'demo-mismatch', dataset: 'ceiling' },
  legacy: { ...answered, run_id: 'demo-legacy', dataset: 'UNKNOWN' },
  benchmark: answered,
};

const diagnostics = (overrides: Partial<FindingsResponse['diagnostics']> = {}): FindingsResponse['diagnostics'] => ({
  task_count: 1, processable_task_count: 1, blocked_task_count: 0, inconclusive_task_count: 0,
  observed_run_count: 1, answered_run_count: 1, abstained_run_count: 0, rejected_run_count: 0,
  ...overrides,
});

const answeredFindings: FindingsResponse = {
  schema_version: 'ax-data-findings-v1', dataset: 'mini', diagnostics: diagnostics(), findings: [],
};

const abstainedFindings: FindingsResponse = {
  schema_version: 'ax-data-findings-v1', dataset: 'mini',
  diagnostics: diagnostics({ processable_task_count: 0, blocked_task_count: 1, answered_run_count: 0, abstained_run_count: 1 }),
  findings: [{
    finding_id: 'FINDING_DEMO_01', finding_type: 'INSUFFICIENT_EVIDENCE', source_ids: ['SOURCE_DEMO_02'],
    affected_task_ids: ['ADHOC_DEMO'], affected_tasks: [{ task_id: 'ADHOC_DEMO', label: '반품 가능 기간은 며칠인가요?' }],
    affected_run_ids: ['demo-abstained'], affected_task_count: 1, observed_run_count: 1,
    evidence: [{ source_id: 'SOURCE_DEMO_02', source_title: '반품_정책_초안.txt', tool_name: 'read_document', excerpt: 'DEV fixture에서 실제 반환된 문서 발췌 예시입니다.' }],
    summary: '관련 자료는 찾았지만 답을 확정하기에 정보가 부족했습니다.',
    recommended_action: '해당 업무 기준에 필요한 필드나 문서를 보완하세요.', comparison_status: 'OPEN', comparison: null,
  }],
};

export const demoFindings: Record<keyof typeof demoRuns, FindingsResponse> = {
  running: { schema_version: 'ax-data-findings-v1', dataset: 'mini', diagnostics: diagnostics({ task_count: 0, processable_task_count: 0, observed_run_count: 0, answered_run_count: 0 }), findings: [] },
  answered: answeredFindings,
  abstained: abstainedFindings,
  rejected: { schema_version: 'ax-data-findings-v1', dataset: 'mini', diagnostics: diagnostics({ processable_task_count: 0, inconclusive_task_count: 1, answered_run_count: 0, rejected_run_count: 1 }), findings: [] },
  mismatch: answeredFindings,
  legacy: answeredFindings,
  benchmark: answeredFindings,
};

export const demoEvidence: EvidenceCheckResult = {
  schema_version: 'ax-evidence-check-v1', run_id: 'demo-answered', verdict: 'UNCONFIRMED', delivery_sha256: '0'.repeat(64),
  cited_source_ids: ['SOURCE_DEMO_01'], matched_source_ids: ['SOURCE_DEMO_01'], unmatched_source_ids: [],
  evidence: [{ sequence: 1, tool_name: 'read_document', source_ids: ['SOURCE_DEMO_01'], match: 'CITED_RESPONSE' }],
  derivation: null,
  limitations: ['DEV fixture: the cited response does not provide a deterministic match within checker v1 scope.'],
  unconfirmed_is_not_incorrect: true,
};

export const demoRetrievalTrace: RetrievalTrace = {
  schema_version: 'ax-retrieval-trace-v2',
  run_id: 'demo-answered',
  cited_source_ids: ['SOURCE_DEMO_01'],
  steps: [
    {
      sequence: 1, tool_name: 'search_documents', status: 'ERROR',
      result_count: 0, candidates: [], cited_source_ids: [], truncated: null,
      request_summary: { parameter_names: ['query', 'top_k'], query_character_count: 17, result_limit: null, source_ids: [], filter_fields: [] },
      error_code: 'VALIDATION_ERROR',
    },
    {
      sequence: 2, tool_name: 'read_document', status: 'SUCCESS',
      result_count: 1,
      candidates: [{ rank: 1, title: '검증용 정책 문서', source_ids: ['SOURCE_DEMO_01'], cited: true }],
      cited_source_ids: ['SOURCE_DEMO_01'], truncated: false,
      request_summary: { parameter_names: ['document_id'], query_character_count: null, result_limit: null, source_ids: ['SOURCE_DEMO_01'], filter_fields: [] },
      error_code: null,
    },
  ],
  limitations: [
    'Successful and failed data-tool attempts stored for this run are shown.',
    'Request summaries exclude raw query text and filter values.',
    'Candidate presence or rank is not an accuracy judgment.',
  ],
};

export const benchmarkReport: BenchmarkDemoReport = {
  mode: 'benchmark', title: '데이터 정리 전후 비교',
  description: '동일 에이전트·동일 과제 24개를 정리 전 데이터와 수동 정리된 사본에 각각 실행했습니다. 실행일',
  runDate: '2026-09-18',
  before: { passed: 2, total: 24, abstained: 15, refused: 3, wrong: 4 },
  ceiling: { passed: 18, total: 24, abstained: 5, refused: 1, wrong: 0 },
  groups: [
    { group: '규정·정책 (8)', before: '1 / 8', after: '7 / 8', note: '구버전 제거' },
    { group: '매출·수치 (6)', before: '1 / 6', after: '5 / 6', note: '머지 셀 정리' },
    { group: '절차·매뉴얼 (6)', before: '0 / 6', after: '4 / 6', note: '문서 자체 부재' },
    { group: '계약·거래처 (4)', before: '0 / 4', after: '2 / 4', note: '권한 설정' },
  ],
  interpretation: '데이터만 정리해 성공 16건이 늘었습니다. 이 문장은 통제된 DEV fixture에만 해당합니다.',
  limitation: '정리 사본은 수작업이며 과제 분포는 실제 질의와 다를 수 있습니다.',
};
