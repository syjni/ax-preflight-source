# AX Preflight 검증 산출물 버전 이력

이 문서는 README에서 분리한 내부 검증 계보를 보존합니다. 현재 심사 기준은 공개
소스의 `main`과 `v0.3.0-submission` 릴리스이며, 화면의 대표 결과는 검증된 v4
snapshot을 사용합니다.

## 현재 기준

| 구분 | 현재 기준 | 의미 |
|---|---|---|
| 제품 코드 | 공개 저장소 `main` | 신규 실행과 현재 Results Console의 기준 |
| 제출 릴리스 | `v0.3.0-submission` | 브라우저 파일 선택, PDF 표·OCR와 Docker 실행까지 포함해 독립 검증한 제출 패키지 |
| 로컬 자료 점검 | local reviewer mode | 파일·폴더 선택 또는 경로 입력으로 정적 scan을 실행하고 마스킹된 진단 결과를 Results Console에 표시 |
| 읽기 전용 데모 | frozen v4 | 10업무 × 2상태 × 3회, 총 60회 실행 snapshot |
| 반복 답 비교 | 의미 비교 v2 | 표현 차이와 실제 의미값 차이를 분리하는 현재 화면 기준 |
| 신규 실행 근거 검사 | Evidence Checker v3 | 폐기된 수량을 현재 근거로 취급하지 않는 현재 제품 기준 |

`frozen v4`, `의미 비교 v2`, `Evidence Checker v3`는 서로 다른 계층의 버전입니다.
각각 저장된 실행 묶음, 반복 답 비교 규칙, 신규 실행의 근거 검사기를 가리킵니다.

`v0.1.0-submission`은 frozen v4 조회 중심의 최초 제출 후보로 보존합니다.
`v0.2.0-submission`은 같은 검증 결과에 심사자 자신의 폴더를 점검하는 로컬
reviewer mode와 Windows 원클릭 시작 경로를 추가했습니다. `v0.3.0-submission`은
브라우저 파일·폴더 선택, PDF 표 추출, 선택적 OCR과 Docker reviewer image를 추가한
현재 제출 기준입니다.

## Frozen snapshot 계보

| snapshot | 용도 | 보존 원칙 |
|---|---|---|
| v1 | 최초 제품 sanity demo | 원본 결과 보존 |
| v2 | 같은 6개 실행에 개선된 근거 검사를 별도 계산 | 기존 delivery와 tool response의 바이트 해시 보존 |
| v3 | Before·After 포트폴리오의 업무별 1회 결과 | 이전 snapshot과 분리 보존 |
| v4 | 10개 업무를 Before·After에서 각각 3회 실행 | 60개 실행, manifest와 상위 snapshot hash 검증 |

현재 공개 화면은 v4만 대표 결과로 사용합니다. 이전 snapshot은 회귀 검증과 감사
추적을 위해 저장소에 남아 있으며 제품 헤드라인 수치로 사용하지 않습니다.

## 비교 규칙 계보

v4를 처음 동결할 때 사용한 비교 v1은 문자열과 단위 표기 차이를 그대로 셌습니다.
후속 원자료 감사에서 이 방식이 같은 의미의 표현 차이까지 불일치로 분류할 수 있음을
확인했습니다. 현재 화면은 빈 결과, 식별자 집합, 날짜, 수치·단위와 영업일 표현을
일반 규칙으로 정규화하는 의미 비교 v2를 사용합니다.

- 세 번 모두 같은 의미값으로 답변: `반복 안정`
- 세 번 모두 보류: `일관된 보류`
- 답변과 보류가 섞임: `혼재`
- 답변 간 실제 의미값이 다름: `답변 불일치`

상세 규칙과 업무별 재분류는
[의미 비교 v2 감사](PHASE6_V4_COMPARISON_V2.md)에 기록되어 있습니다.

## Evidence Checker 계보

Evidence Checker는 같은 실행에 저장된 구조화 도구 응답과 최종 답변의 연결을
결정론적으로 확인합니다.

- v1: 인용된 응답의 허용 필드에서 직접 일치, 제한된 합·차·행 수 계산, 부분 일치와 미확인을 구분
- v2: 수치·단위와 구조화 표·lookup 결과에 대한 일반 검사를 확장
- v3: v2 규칙을 유지하면서 문장에 명시적으로 폐기된 수량을 현재 직접 근거에서 제외

새로 실행하는 제품 run은 v3를 사용합니다. 동결 snapshot에 포함된 과거 검사 결과와
구현은 재현성을 위해 변경하지 않습니다. `DIRECT_MATCH`는 인용 근거와 답 값의 직접
일치를 뜻하며 업무 정답률과는 별도입니다.

## 관련 문서

- [반복 실행 v4 설계와 결과](PHASE6_V4.md)
- [의미 비교 v2 감사](PHASE6_V4_COMPARISON_V2.md)
- [Evidence Checker v2 설명](EVIDENCE_CHECKER_V2.md)
- [Evidence Checker v3 설명](EVIDENCE_CHECKER_V3.md)
- [DIRECT_MATCH 수동 감사](PHASE6_V4_DIRECT_MATCH_AUDIT.md)
- [주문 원장 검색 경로 감사](PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md)
