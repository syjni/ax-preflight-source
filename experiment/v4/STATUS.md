# AX v4 현재 상태 — 2026-09-22

상태: **공식 실행 중단, 유효 슬롯 1/32**. 32회 완료 및 공식 결과 집계는 이루어지지 않았다.

- 동결 매니페스트: `experiment/frozen/ax-exp-v4-manifest.json`, SHA-256 `9189c846389dd39659a8eb53a4fe42d1717c1275b52d3ab7e871d1838485589c`. 중단 후 다시 실행한 동결 preflight는 `passed=true`, `ready_for_official=true`였다.
- 등록 순서대로 첫 두 슬롯만 시도했다. `V4_R01_NORTH_DEFECT_RATE` r1은 기본 시도 INVALID 뒤 별도 보존 경로의 재시도에서 VALID였다. `V4_R02_SOUTH_DEFECT_RATE` r1은 기본 시도와 9회 재시도, 총 10회 모두 INVALID였다. 이후 과제는 시작하지 않았다.
- 총 시도 12회: VALID 1회, INVALID 11회. 모든 INVALID 사유는 `INVALID_STREAM_SESSION_RESPONSE_MISMATCH` 한 가지였다. Kiro 스트림의 `runFinished.finalText`에 중간 응답이 최종 응답 앞에 합쳐졌지만 세션 JSON에는 최종 응답만 저장되었다. 동결 실행기의 전체 문자열 일치 기준을 바꾸지 않았고 무효 응답을 공식 점수에 넣지 않았다.
- 시도별 원본 스트림·세션 참조·원문·전달 JSON·프롬프트·도구 및 런타임 영수증은 `artifacts/heldout_ax-exp-v4/`와 `artifacts/heldout_ax-exp-v4-retries/`에 별도 보존했다. `artifacts/heldout_ax-exp-v4/PARTIAL_AUDIT.json`의 전수 무결성 감사: `integrity_passed=true`, `official_complete=false`, 중복 유효 슬롯·세션 없음, 오류 0건.
- 원인과 재시도 운영 판단: `artifacts/heldout_ax-exp-v4/EXECUTION_INCIDENTS.md`. 동일한 오류가 10회 연속 발생해 운영 한도에서 멈췄다. 이는 점수·과제·자료·모델·프롬프트·유효성 규칙을 사후 변경하지 않기 위한 결정이다.

이 동결본에 대해서는 **32회 결과나 성공률을 보고하지 않는다**. 현재 과제는 이미 모델에 노출되었으므로, 실행기와 스트림 의미의 불일치를 해결하는 새 사전등록 실험에는 새로운 미공개 과제를 준비해야 한다. 공식 v3의 기록과 점수는 수정하지 않았다.
