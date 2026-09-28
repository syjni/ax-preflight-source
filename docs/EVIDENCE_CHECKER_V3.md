# Evidence Checker 확장 규칙과 frozen v3 보존

기존 `ax_product/evidence.py`는 frozen Phase 6 v2·v3가 소스 해시로 참조하므로 수정하지 않는다. 신규 실행과 향후 v4 snapshot은 별도 `ax_product/evidence_v2.py`를 사용한다. v2는 먼저 v1 checker를 실행하고, v1이 직접 확인하지 못한 경우에만 아래의 결정론적 규칙을 추가 적용한다.

- `query_table`이 반환한 `count`, `sum_*`, `min_*`, `max_*` 집계 cell과 답의 정규화된 값이 같으면 `DIRECT_MATCH`
- `YYYY-MM-DD`, `YYYY.MM.DD`, `YYYY/MM/DD` 날짜를 실제 달력 날짜로 정규화한 뒤 구조화 cell과 비교
- 비수량 단위가 붙은 식별자가 구조화 cell과 정확히 같으면 `DIRECT_MATCH`
- 잘리지 않은 다중행 표의 문자열 값 전체가 답에 포함되고 2개 이상 field와 4개 이상 고유 값을 포함하면 완전한 표 매핑으로 `DIRECT_MATCH`
- 단일 구조화 행의 문자열 값 2개 이상과 수치 1개가 답에 함께 정확히 나타나면 복합값으로 `DIRECT_MATCH`
- 서로 다른 인용 구조화 응답에서 정확히 확인된 문자열 값 2개 이상이 답에 함께 나타나면 다중 source 복합값으로 `DIRECT_MATCH`
- 답의 단위가 선언되어 있고 답 속 유일한 수치가 `lookup_value`의 반환값과 같으면 typed lookup 값으로 `DIRECT_MATCH`
- 잘린 표 응답들을 합친 고유 행 수가 전체 행 수와 정확히 같고 모든 행에서 `available_qty ≥ reorder_point`이면 “부족 품목 없음”을 완전 표 predicate로 `DIRECT_MATCH`

인용하지 않은 응답, 일부 source ID가 같은 run 응답에 없는 경우, 잘린 표의 목록 완전성, 자연어 의미 추론, 한영 번역, 비율·단위 환산은 승격하지 않는다. 복합값 규칙도 답에 실제로 포함된 구조화 cell만 사용한다. `UNCONFIRMED`는 계속 오답 판정이 아니다.

## frozen v3 사후 원인 분류

`python -m scripts.analyze_phase6_evidence_gaps`는 frozen v3를 읽기만 하고 결과를 `artifacts/posthoc_phase6_evidence_checker_v3`에 쓴다.

- 기존 `DIRECT_MATCH`: 1/20
- 기존 `UNCONFIRMED` 19건 중 신규 규칙으로 확인: 11건
- 확장 규칙 적용 결과: `DIRECT_MATCH` 12/20, `UNCONFIRMED` 8/20
- 새 확인 11건: 집계값 6, 구조화 scalar 2, 완전한 표 매핑 2, 완전 표 predicate 1
- 남은 8건: 인용된 보류 설명 불일치 4, 무인용 보류 2, 의미·언어 변환 2

frozen v3 파일은 재계산하거나 덮어쓰지 않는다. `python -m scripts.verify_phase6_demo_v3`는 확장 후에도 기존 manifest와 v1 checker 소스 해시를 그대로 검증해야 한다.
