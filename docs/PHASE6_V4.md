# Phase 6 반복 실행 v4

v4는 기존 frozen v3를 덮어쓰지 않고, 같은 10개 후보 업무를 Before/After에서 각각 3회 실행한 60-run write-once snapshot이다. 목적은 한 번의 성공·보류를 문서 정리 효과로 오해하지 않고, 자신 있게 답한 실행 사이의 값·단위·인용 source 변동까지 제품 Finding으로 드러내는 것이다.

## 결과: 같은 frozen run, 두 비교 규칙

v4 run 60개와 Evidence 파일은 변경하지 않았다. 최초 동결에 사용한 문자열 중심 비교를 `v1`, 이후 일반 의미 규칙으로 다시 계산한 제품 표시 기준을 `v2`라고 부른다.

### 의미 비교 v2 — 현재 제품 표시 기준

| 업무 분류 | Before | After |
|---|---:|---:|
| 3회 모두 같은 의미값으로 답변 | 5 / 10 | 6 / 10 |
| 3회 모두 보류 | 3 / 10 | 2 / 10 |
| 답변·보류 혼재 또는 실제 의미값 차이 | 2 / 10 | 2 / 10 |

세 분류의 합은 각 상태에서 10이다. Before→After 5/10→6/10은 같은 run을 새 규칙으로 다시 분류한 기술적 결과이며, 전체 개선의 인과 효과를 뜻하지 않는다. 실제 변경 파일은 `06_고객지원/FAQ_2026.txt` 하나이므로 수정 효과 주장은 반품 기간 업무의 0/3→3/3에만 한정한다.

### 비교 규칙 v1 — frozen 감사 기준

| 지표 | Before | After |
|---|---:|---:|
| 관측 run | 30 | 30 |
| ANSWERED | 19 | 21 |
| ABSTAINED | 11 | 9 |
| 세 번 모두 같은 문자열·단위로 처리 | 4 / 10 | 2 / 10 |
| 한 번 이상 보류 | 5 / 10 | 4 / 10 |
| 문자열·단위 불일치로 inconclusive | 1 / 10 | 4 / 10 |
| Evidence `DIRECT_MATCH` | 17 / 30 | 18 / 30 |

전체 Evidence는 35/60이 `DIRECT_MATCH`다. 이는 인용 구조화 응답과 답 값의 일치 건수이지 정답률이 아니다. 확장 규칙과 불안정 업무를 우선한 6건 수동 감사 결과는 [DIRECT_MATCH 감사](PHASE6_V4_DIRECT_MATCH_AUDIT.md)에 기록했다. `UNCONFIRMED` 25건은 오답이 아니라 결정론적 checker가 자동 확인하지 못한 범위다.

v1의 4/10·2/10은 원본 동결 산출물의 감사값으로 보존한다. 그러나 원자료 검토에서 표현·구분자·단위 문자열 차이를 실제 답 차이로 세고, 3회 중 1회만 보류한 업무를 데이터 문제로 분류하는 한계가 확인됐다. 현재 화면은 [의미 비교 v2](PHASE6_V4_COMPARISON_V2.md)를 사용하며 v1 수치는 접힌 감사 정보로 함께 제공한다.

실제 수정한 반품 충돌은 Before 3/3 `CONFLICTING_EVIDENCE` 보류, After 3/3 `30일 / DIRECT_MATCH`이며 이 좁은 변화만 수정 전후 결과로 설명한다.

## 의미 비교 v2와 Finding

`submit_answer`는 새 실행에서 `EXACT_TEXT`, `EMPTY_SET`, `ID_LIST`, `NUMERIC_QUANTITY` 답 종류를 선택적으로 기록할 수 있다. 명시된 종류가 없는 frozen delivery에는 정답이나 benchmark label을 사용하지 않는 다음 일반 규칙만 적용한다.

- “없음”, “해당 품목 없음”, “전 품목 기준 충족”처럼 명확한 빈 결과는 `EMPTY_SET`으로 비교
- `P005`, `CS01`처럼 식별자가 있는 답은 정렬된 식별자 집합으로 비교
- 날짜는 ISO 날짜로, 수치는 정규화한 값과 단위 family로 비교
- “다음 달 5영업일”처럼 unit 필드가 빠진 경우에도 답 문장의 명시적 단위만 보완
- 의미값이 같고 인용 source 집합만 다른 경우 답 불일치로 세지 않음

3회 모두 답변되고 의미값이 같으면 반복 안정 처리, 3회 모두 보류면 일관된 보류, ANSWERED와 ABSTAINED가 섞이면 `MIXED_OUTCOMES` 원인 미확인 신호로 분류한다. `INCONSISTENT_ANSWERS`는 v2 의미값이 실제로 다를 때만 생성한다.

혼재 또는 의미값 불일치는 그 자체로 데이터 문제 판정이 아니다. 기본값은 `attribution_status=CAUSE_UNCONFIRMED`이며, 특정 문서의 모호성이나 충돌이 추가 반복에서 재현되기 전에는 문서 수정을 권고하지 않는다. 다만 v4의 두 주문 업무는 후속 감사에서 원장 파일과 테이블이 정상 파싱·인덱싱됐지만 query wording과 BM25 상위-k에 따라 발견 여부가 달라지는 문제가 재현되어 `RETRIEVAL_LIMITATION`으로 별도 표시한다. 자세한 근거는 [주문 원장 검색 경로 감사](PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md)에 기록했다.

## Evidence v2

v1 checker와 frozen v3는 수정하지 않았다. v4는 인용된 같은-run 구조화 응답에 한해 집계값, 날짜, exact scalar, 완전 표 매핑, typed lookup, 완전 표 predicate를 결정론적으로 확인한다. 자연어 의미 추론, 한영 번역, 비율·단위 변환은 여전히 권위 판정에서 제외한다.

## 재현과 검증

```bash
python -m scripts.run_phase6_demo_v4 estimate
python -m scripts.verify_phase6_demo_v3
python -m scripts.verify_phase6_demo_v4
```

실제 60회 실행은 fresh Kiro process, namespace `phase6v4`, 고정된 10×2×3 행렬로 수행했다. v4 verifier는 parent v3 tree/manifest, runtime identity, 모든 run과 Evidence, summary, file inventory를 SHA-256으로 검증한다.
