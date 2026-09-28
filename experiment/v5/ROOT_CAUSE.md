# AX v4 스트림 불일치 원인 조사 — v5 개발 근거

2026-09-22. 이 문서는 v4 공식 판정을 변경하지 않는 읽기 전용 사후 조사와 **별도 개발 자료**의 재현 기록이다.

## 관찰

v4 동결 실행기 `scripts/v4_official_runner.py`는 세션 턴 `result.Ok.content`를 `raw_response.txt`로 저장한 뒤, `runFinished.finalText == raw`를 요구한다. `scripts/session_prompt_validation.py`가 반환하는 `assistant_responses[-1]`는 세션의 **마지막** 에이전트 응답이다. 반면 Kiro CLI 2.23.0 v2의 `runFinished.finalText`는 해당 턴의 모든 `AssistantMessage` 텍스트를 구분자 없이 이은 값이다. 스트림의 `agent_message_chunk`를 이은 값도 그 전체와 같다.

v4의 보존된 12개 시도를 읽기 전용으로 대조하면, 11개에서 전체 스트림과 마지막 응답이 다르고 동결 검사에서 `INVALID_STREAM_SESSION_RESPONSE_MISMATCH`가 났다. 모든 12개에서 **세션 `AssistantMessage` 전체 연결 = 스트림 텍스트 조각 연결 = `runFinished.finalText`**이며 **마지막 `AssistantMessage` = 세션 턴 `result.Ok.content`**다. 이는 새 기준을 이용한 원인 진단일 뿐, v4의 11개 INVALID를 소급 유효화하거나 점수에 넣지 않는다. v4는 여전히 1/32 유효 슬롯에서 중단된 미완료 실험이다.

## 독립 개발 재현

v5 후보 과제가 아닌 한울상점 개발 메모로 `DEV_STREAM_MULTI_01`을 새 Kiro 세션에서 실행했다. v4 실행기 경로는 예상대로 `INVALID_STREAM_SESSION_RESPONSE_MISMATCH`를 반환했다. 세션 JSONL에는 `AssistantMessage` 3개(텍스트 길이 0, 82, 261)가 있었고, 스트림 `finalText` 343자는 세 메시지 연결과 같았다. 세션 최종 응답은 마지막 메시지와 같은 261자였다. 정확 프롬프트와 개발 자료 영수증은 통과했다.

새 `scripts/stream_response_validation.py`는 위 두 범위와 스트림 조각을 따로 검증한다. 개발 재현 세션에 적용했을 때 통과했다. 또 새 `scripts/v5_official_runner.py`의 전체 경로를 **동일한 개발 메모만** 사용하는 `DEV_V5_MULTI_01`로 실행했고, 여러 메시지를 포함한 세션에서 `VALID`, 새 스트림 검증 통과, 정답 및 전달 JSON 유효를 확인했다. 이 결과는 v5 미공개 과제의 성과가 아니다.

## 결론과 수정 범위

증거는 스트림 수집 누락보다 **비교 대상의 범위를 혼동한 유효성 기준**을 가리킨다. 전체 턴 텍스트와 마지막 응답은 둘 다 보존하되 서로 같은 값일 필요는 없다. 새 검사기는 세션 전체·스트림 전체·스트림 조각의 일치와 마지막 메시지·세션 턴 결과의 일치를 요구한다. 스트림 조각 삭제, 완료 텍스트 오염, 마지막 세션 메시지 변경, 절단 완료를 거부하는 회귀 테스트를 둔다. CLI 버전이나 이벤트 의미가 바뀌면 공식 실행 전 개발 재검증이 필요하다.
