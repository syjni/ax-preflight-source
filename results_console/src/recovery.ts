export type RunFailureSource = 'submit' | 'lookup' | 'poll';
export type RunFailureKind =
  | 'runner-unavailable'
  | 'run-not-found'
  | 'connection'
  | 'invalid-response'
  | 'verified-task-not-onboarded'
  | 'candidate-mismatch'
  | 'onboarding-blocked'
  | 'execution-control'
  | 'request-failed';

export type RunFailure = {
  kind: RunFailureKind;
  source: RunFailureSource;
  code: string;
  title: string;
  message: string;
  actionLabel: string;
};

type ApiFailure = Error & { status: number; detail: string };

function isApiFailure(error: unknown): error is ApiFailure {
  return error instanceof Error
    && typeof (error as Partial<ApiFailure>).status === 'number'
    && typeof (error as Partial<ApiFailure>).detail === 'string';
}

export function runFailureFor(error: unknown, source: RunFailureSource): RunFailure {
  if (isApiFailure(error)) {
    if (new Set([
      'RUNNER_EXECUTABLE_UNAVAILABLE',
      'EXECUTION_POLICY_REQUIRED',
      'DATASET_REQUIRED',
      'DATA_TRANSFER_APPROVAL_REQUIRED',
      'DATA_TRANSFER_APPROVAL_EXPIRED',
      'MODEL_NOT_APPROVED',
      'BATCH_RUN_LIMIT_EXCEEDED',
      'DAILY_RUN_LIMIT_REACHED',
      'DAILY_BUDGET_REACHED',
      'CONCURRENCY_LIMIT_REACHED',
    ]).has(error.detail)) return {
      kind: 'execution-control', source, code: error.detail,
      title: '프로젝트 실행 통제를 확인해 주세요',
      message: '승인된 모델·자료 전달 경계·최근 24시간 실행 및 예상 비용 한도를 서버가 실행 직전에 다시 확인했습니다.',
      actionLabel: '실행 통제 설정 보기',
    };
    if (error.detail === 'RUNNER_UNAVAILABLE') return {
      kind: 'runner-unavailable', source, code: error.detail,
      title: '새 실행을 사용할 수 없습니다',
      message: '현재 공개 배포본은 읽기 전용입니다. 검증된 대표 흐름에서 이미 동결·검증된 실행과 근거를 확인할 수 있습니다.',
      actionLabel: '검증된 대표 흐름 보기',
    };
    if (error.detail === 'VERIFIED_TASK_NOT_ONBOARDED') return {
      kind: 'verified-task-not-onboarded', source, code: error.detail,
      title: '검증 업무가 아직 등록되지 않았습니다',
      message: '이 데이터셋과 업무에 연결된 유효한 승인 기록이 없습니다. 승인 범위를 확인하거나 업무 후보·직접 질문을 사용하세요.',
      actionLabel: '업무 승인 확인',
    };
    if (error.detail === 'TASK_CANDIDATE_MISMATCH') return {
      kind: 'candidate-mismatch', source, code: error.detail,
      title: '업무 후보 정보가 최신 목록과 다릅니다',
      message: '현재 데이터셋의 업무 후보를 다시 선택한 뒤 실행하세요.',
      actionLabel: '업무 후보 다시 선택',
    };
    if (error.detail === 'ONBOARDING_BLOCKED') return {
      kind: 'onboarding-blocked', source, code: error.detail,
      title: '데이터 온보딩 검사를 통과하지 못했습니다',
      message: '원본 무결성, 파싱 범위, 검색 가능 자료 또는 평가 정보 분리 항목의 차단 원인을 먼저 해결하세요.',
      actionLabel: '온보딩 검사 보기',
    };
    if (error.detail === 'API_CONNECTION_FAILED') return {
      kind: 'connection', source, code: error.detail,
      title: 'API에 연결할 수 없습니다',
      message: '서버 주소와 실행 상태를 확인한 뒤 같은 요청을 다시 시도하세요.',
      actionLabel: '다시 시도',
    };
    if (error.detail === 'INVALID_API_RESPONSE') return {
      kind: 'invalid-response', source, code: error.detail,
      title: 'API 응답을 확인할 수 없습니다',
      message: '응답 형식이 제품 계약과 일치하지 않습니다. 서버 상태를 확인한 뒤 다시 시도하세요.',
      actionLabel: '다시 시도',
    };
    if (error.status === 404) return {
      kind: 'run-not-found', source, code: 'RUN_NOT_FOUND',
      title: '실행을 찾을 수 없습니다',
      message: '실행 ID의 오탈자와 배포 환경이 맞는지 확인하세요. 존재하지 않는 실행을 새 결과처럼 표시하지 않습니다.',
      actionLabel: '실행 ID 다시 확인',
    };
    return {
      kind: 'request-failed', source, code: error.detail || `HTTP_${error.status}`,
      title: '실행 요청을 완료하지 못했습니다',
      message: '요청 조건을 확인한 뒤 다시 시도하세요. 같은 문제가 반복되면 표시된 오류 코드를 함께 전달하세요.',
      actionLabel: '다시 시도',
    };
  }
  return {
    kind: 'request-failed', source, code: 'UNEXPECTED_ERROR',
    title: '실행 요청을 완료하지 못했습니다',
    message: '예상하지 못한 오류가 발생했습니다. 입력을 유지한 채 다시 시도할 수 있습니다.',
    actionLabel: '다시 시도',
  };
}
