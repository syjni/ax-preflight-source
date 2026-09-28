# Phase 6 v4 DIRECT_MATCH 수동 감사

Evidence Checker v2가 `DIRECT_MATCH`로 표시한 After run 18건 중, 확장 규칙과 불안정 업무를 우선해 6건을 원자료로 열어 확인했다. 이 감사의 수용 기준은 “승인된 Delivery의 답이 인용된 같은-run 구조화 응답에 그대로 있거나 허용 규칙으로 재계산되는가”이다. `DIRECT_MATCH`는 업무 정답률이나 문맥 전체의 진실성을 뜻하지 않는다.

| Run | 규칙 | 직접 확인한 구조화 근거 | 판정 |
|---|---|---|---|
| `...inventory_most_available-r1` | `STRUCTURED_MULTI_SOURCE_COMPOSITE` | 재고 query의 첫 행 `P005 / available_qty 281`, 품목 lookup `유기농 그래놀라`가 Delivery의 복합 답과 일치 | PASS |
| `...inventory_most_available-r2` | `STRUCTURED_LOOKUP_NUMERIC_VALUE` | 집계 query의 첫 행 `P005 / total_available_qty 281`, 재고 lookup `281`, 품목 lookup `유기농 그래놀라`가 모두 일치 | PASS |
| `...order_monthly_amount-r1` | `QUERY_AGGREGATE_VALUE` | 주문원장 query가 `sum_amount: 4980700`, `source_rows_matched: 25`, `truncated: false` 반환 | PASS |
| `...inventory_low_stock-r1` | `COMPLETE_TABLE_PREDICATE` | 동일 표의 12행을 10+2행으로 모두 읽었고 각 행에서 `available_qty >= reorder_point`를 확인 | PASS |
| `...order_latest-r3` | `DATE_NORMALIZATION` | 주문원장 query의 최상단 날짜 `2026-09-21`과 Delivery 날짜가 일치 | PASS¹ |
| `...policy_return_window-r1` | v1 exact direct | 인용 문서 본문에 `반품 가능 기간은 구매일로부터 30일입니다`가 있고 Delivery는 `30일` | PASS |

¹ 날짜값의 직접 일치는 확인했지만 “가장 최근”이라는 업무 의미는 query 정렬 계약에 의존한다. v2의 공통 limitation대로 broader contextual entailment를 별도 증명하지 않는다.

## 불안정 업무 교차 확인

최다 가용재고 r1과 r2는 둘 다 `DIRECT_MATCH`지만 서로 다른 사실을 답한 것이 아니다. 두 run 모두 `P005 / 유기농 그래놀라 / 281개`를 가리킨다. frozen 정규화기가 r1은 복합 `text`, r2는 `number:281`로 분류해 불일치 Finding을 만든 것이며, 이는 checker의 상충 정답 허용이 아니라 정규화 형식 민감도다.

월 주문금액은 r1·r2의 `4,980,700원`만 `DIRECT_MATCH`이고 r3은 보류·`UNCONFIRMED`다. 서로 다른 금액을 둘 다 직접 확인한 사례는 아니다.

## 결론과 표현 범위

- 표본 6/6은 v2의 좁은 직접 근거 계약과 일치했다.
- 이 표본 감사만으로 나머지 29건이나 일반 정확도를 보증하지 않는다.
- 발표 문구는 “60회 중 35건에서 인용된 구조화 응답과 답 값이 직접 일치했다”로 한정한다.
- `UNCONFIRMED`는 오답이 아니고, `DIRECT_MATCH`도 업무 정답 보증이 아니다.
