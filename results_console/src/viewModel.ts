import type {
  EvidenceCheckResult,
  BusinessTaskView,
  ReadinessFlags,
  ReadinessResponse,
  RunRequest,
  TasksResponse,
} from './generated/api';

export type DimensionKey = 'redundancy' | 'completeness' | 'safety' | 'accessibility' | 'timeliness';

export type DetailValue = {
  label: string;
  value: string;
};

export type ReadinessRowView = {
  key: DimensionKey;
  index: string;
  name: string;
  description: string;
  score: number;
  counts: DetailValue[];
  flags: DetailValue[];
};

const dimensionCopy: Record<DimensionKey, { name: string; description: string }> = {
  redundancy: { name: '완전 중복 파일', description: 'Exact duplicate files' },
  completeness: { name: '표 데이터 완결성', description: 'Table completeness' },
  safety: { name: '개인정보 패턴 탐지', description: 'PII pattern detection' },
  accessibility: { name: '파일 접근성', description: 'File accessibility' },
  timeliness: { name: '수정일 최신성', description: 'Modified-date timeliness' },
};

const countLabels: Record<DimensionKey, Record<string, string>> = {
  redundancy: {
    total_files: '전체 파일', exact_duplicate_groups: '완전 중복 그룹', redundant_files: '중복 파일',
  },
  completeness: {
    eligible_tables: '평가 대상 표', total_cells: '전체 셀', estimated_missing_cells: '추정 누락 셀',
  },
  safety: {
    total_files: '전체 파일', pii_affected_files: '개인정보 패턴 탐지 파일', files_without_detected_pii: '개인정보 패턴 미탐지 파일',
  },
  accessibility: {
    total_files: '전체 파일', parsed_files: '파싱 파일', ocr_required_files: 'OCR 필요 파일', accessible_files: '접근 가능 파일',
  },
  timeliness: {
    files_with_valid_modified_at: '유효 수정일 파일', non_stale_files: '최신 파일', stale_files: '오래된 파일',
    future_timestamp_files: '미래 시각 파일', missing_timestamp_files: '수정일 누락 파일', invalid_timestamp_files: '수정일 오류 파일',
  },
};

const flagKeys: Record<DimensionKey, Array<keyof ReadinessFlags>> = {
  redundancy: ['empty_file_set', 'scan_metadata_file_count_mismatch'],
  completeness: ['empty_file_set', 'completeness_not_applicable', 'scan_metadata_file_count_mismatch'],
  safety: ['unknown_pii_file_id_count', 'scan_metadata_file_count_mismatch'],
  accessibility: ['unknown_ocr_file_id_count', 'scan_metadata_file_count_mismatch'],
  timeliness: ['no_valid_modified_at', 'missing_modified_at_count', 'invalid_modified_at_count', 'future_modified_at_count'],
};

const flagLabels: Record<keyof ReadinessFlags, string> = {
  empty_file_set: '빈 파일 집합',
  completeness_not_applicable: '완결성 평가 비적용',
  no_valid_modified_at: '유효 수정일 없음',
  missing_modified_at_count: '수정일 누락 수',
  invalid_modified_at_count: '수정일 오류 수',
  future_modified_at_count: '미래 수정일 수',
  unknown_ocr_file_id_count: '알 수 없는 OCR 파일 ID 수',
  unknown_pii_file_id_count: '알 수 없는 개인정보 탐지 파일 ID 수',
  scan_metadata_file_count_mismatch: '스캔·메타데이터 파일 수 불일치',
};

function displayFlag(value: boolean | number): string {
  if (typeof value === 'boolean') return value ? '예' : '아니요';
  return String(value);
}

export function readinessRows(response: ReadinessResponse): ReadinessRowView[] {
  const order: DimensionKey[] = ['redundancy', 'completeness', 'safety', 'accessibility', 'timeliness'];
  return order.map((key, index) => {
    const counts = response.readiness.counts[key] as unknown as Record<string, number>;
    return {
      key,
      index: String(index + 1).padStart(2, '0'),
      ...dimensionCopy[key],
      score: response.readiness.dimensions[key] * 100,
      counts: Object.entries(counts).map(([name, value]) => ({
        label: countLabels[key][name] ?? name,
        value: String(value),
      })),
      flags: flagKeys[key].map((name) => ({
        label: flagLabels[name],
        value: displayFlag(response.readiness.flags[name]),
      })),
    };
  });
}

export type TaskRowView = {
  id: string | null;
  label: string;
  status: 'CANDIDATE' | 'VERIFIED';
  approvalScope: 'CUSTOMER' | 'CONTROLLED_DEMO' | null;
  fields: DetailValue[];
};

export function taskRows(response: TasksResponse): TaskRowView[] {
  return (response.tasks ?? []).map((task) => ({
    id: task.task_id,
    label: task.question,
    status: task.status,
    approvalScope: task.approval?.approval_scope ?? null,
    fields: [
      { label: 'category', value: task.category },
      { label: 'status', value: task.status ?? '' },
      ...(task.approval ? [
        { label: 'owner', value: task.approval.owner_role },
        { label: 'criteria', value: task.approval.success_criteria.join(' / ') },
        { label: 'approver', value: task.approval.approved_by_role },
        { label: 'approved', value: task.approval.approved_at },
      ] : []),
      { label: 'description', value: task.description },
    ],
  }));
}

export function runRequestFor(
  dataset: string,
  question: string,
  selectedTask: BusinessTaskView | null,
  model?: string,
): RunRequest {
  const approvedModel = model ? { model } : {};
  if (!selectedTask) {
    return { dataset, request_type: 'AD_HOC_QUESTION', question: question.trim(), ...approvedModel };
  }
  if (selectedTask.status === 'VERIFIED') {
    return {
      dataset,
      request_type: 'VERIFIED_BUSINESS_TASK',
      task_id: selectedTask.task_id,
      ...approvedModel,
    };
  }
  return {
    dataset,
    request_type: 'TASK_CANDIDATE',
    task_id: selectedTask.task_id,
    question: question.trim(),
    ...approvedModel,
  };
}

export const evidenceVerdictCopy: Record<EvidenceCheckResult['verdict'], { label: string; summary: string }> = {
  DIRECT_MATCH: { label: '근거 직접 일치', summary: '인용된 구조화 응답에서 전달 값이 직접 확인되었습니다.' },
  DERIVABLE: { label: '계산으로 확인', summary: '허용된 결정적 계산으로 전달 값을 재현했습니다.' },
  PARTIAL_SUPPORT: { label: '부분 일치', summary: '일부 단서는 확인되지만 직접 일치나 단일 계산으로 확정되지 않았습니다.' },
  UNCONFIRMED: { label: '확인 불가', summary: '검사 범위 안에서 근거 지지를 결정적으로 확인하지 못했습니다.' },
};
