# AX v4 개발·준비 검증 기록

작성일: 2026-09-22. 아래 실행은 v4 후보 16과제의 모델 평가가 아니다. 공식 v3 기록과 점수에는 쓰지 않았다.

## 새 후보 자료와 과제

- `experiment/v4/heldout/온담물류/`에 새 회사 자료 4개를 작성했다. v3의 한빛유통 자료·질문·답을 복사하지 않았다. 정책 임계값·필수 항목·책임팀·검수 불량률을 다룬다. v3의 실패 유형과 유사한 **형식**을 검증하되 사실값과 출처는 새로 만들었다.
- Scanner: 4/4 파싱, 표 1개, OCR 필요 0, PII 탐지 0. `experiment/v4/candidate_scan_report.json`.
- 별도 원문 재산출 `python -m scripts.verify_v4_candidate_truth`: 16/16 일치. 비율은 CSV 수량 합계에서 다시 계산했고, 나머지는 정책 원문 문장을 다시 읽었다.
- `python -m scripts.validate_v4_tool_access`: 새 자료 4/4 검색 가능, 문서 읽기와 표 조회 성공, 런타임 자료 누출 검사 통과. 이는 도구 접근의 정적 점검이며 모델 정답률이 아니다.
- `python -m scripts.v4_preflight --manifest experiment/v4/CANDIDATE_MANIFEST.json --allow-draft`: 검사 통과, `ready_for_official=false`. 이 시점의 매니페스트는 후보 상태였다.

## 개발용 코드 검증

`python -m unittest -v tests.test_v4_development tests.test_output_contract`: 19개 통과. 새 예시는 후보 16과제와 별개의 `DEV_*` 값만 사용했다. 검사 범위는 JSON 앞 설명문·펜스 정규화, 중복·누락·다중 객체 거부, 원문 형식과 전달 형식의 분리, 비율·백분율 단위와 허용오차, 항목 배열의 누락·중복·부정형, 임계값 숫자 타입, 보류, 프롬프트의 정답 비노출, 후보 매니페스트의 v3 문구 중복·파일 해시 탐지다. 기존 v3 `test_output_contract`도 통과했다.

## 실제 Kiro 개발 실행

현재 CLI: `kiro-cli-chat 2.23.0`. 처음 기본 샌드박스의 v2 비대화형 호출은 `dispatch failure`였고 v3 호출은 접근 거부였다. 권한이 허용된 개발 실행에서는 v2와 v3 모두 무해한 `OK` 요청에 응답했다. v2 엔진은 로컬 세션 JSON/JSONL에 Prompt 이벤트를 남겨 v3 수준의 바이트 비교가 가능했다. v3 엔진의 세션은 이 로컬 경로에 없어 공식 백엔드로 선택하지 않았다.

별도 `experiment/v4/development/개발용_책임팀.txt`만 사용하는 Kiro 개발 실행 2회:

1. `scripts.v4_dev_kiro_probe`: 프로세스·스트림·세션 응답 일치, 제출 프롬프트 영수증, 런타임 영수증·식별자, 에이전트 설정 해시, 개발 정답 모두 통과. 원문 JSON과 전달 JSON 모두 유효. 기록: `artifacts/v4_development/kiro_223_probe/`.
2. `scripts.v4_dev_runner_probe`: **공식 실행기 코드 경로**를 개발 자료와 별도 아티팩트 경로로 호출. `VALID`, 프롬프트 1건·Prompt 이벤트 1건, MCP 호출 2건, `CORRECT_SUPPORTED`, 원문·전달 JSON 모두 유효. 기록: `artifacts/v4_development/runner_probe/DEV_KIRO_EXACT_01/r1/`.

두 개발 실행의 동일한 정답은 새 미공개 과제 성과가 아니다. 후보 16과제에 대한 Kiro 호출은 하지 않았다.
