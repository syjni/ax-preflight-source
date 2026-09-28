# Phase 6 v4 답 비교 규칙 v2 감사

## 목적과 불변 조건

이 후속 감사는 frozen v4의 delivery·tool response·Evidence 파일을 수정하거나 다시 실행하지 않는다. 같은 60개 run에 일반 비교 규칙을 적용해 표현 차이와 실제 의미 차이를 분리한다. 정답 label이나 benchmark expected answer는 사용하지 않는다.

## 사전 정의한 일반 규칙

1. 새 `submit_answer`는 선택적으로 `answer_kind`를 기록한다: `EXACT_TEXT`, `EMPTY_SET`, `ID_LIST`, `NUMERIC_QUANTITY`.
2. 기존 delivery에 종류가 없으면 다음 순서로만 추론한다.
   - 명확한 빈 결과 표현 → `EMPTY_SET`
   - ISO 형태 날짜 → `DATE`
   - 영문자+숫자 식별자가 있는 답 → 정렬된 `ID_LIST`; 다중 식별자와 명시적 `:`·`→` 연결이 있으면 식별자별 연결 값까지 비교
   - 단일 수치와 명시적 단위 → 정규화한 `NUMERIC_QUANTITY`
   - 나머지 → NFKC·공백 정규화 텍스트
3. 인용 source 집합 차이는 감사 정보이지만 답 의미값 불일치로 세지 않는다.
4. 업무 분류는 상호 배타적이다.
   - 3회 모두 ANSWERED + 같은 의미값: 반복 안정 처리
   - 3회 모두 ABSTAINED: 일관된 보류
   - ANSWERED/ABSTAINED/REJECTED 혼재 또는 실제 의미값 차이: 불안정·검토 필요

## 재분류 결과

| 분류 | Before | After |
|---|---:|---:|
| 반복 안정 처리 | 5 / 10 | 6 / 10 |
| 일관된 보류 | 3 / 10 | 2 / 10 |
| 불안정·검토 필요 | 2 / 10 | 2 / 10 |

기존 v1은 Before 4/10 처리·5/10 보류·1/10 불안정, After 2/10 처리·4/10 보류·4/10 불안정이었다. API는 v2를 기본 표시하고 `legacy_diagnostics`에 v1을 함께 반환한다.

## 표현 차이로 판명된 After 네 업무

| 업무 | v1 원인 | v2 의미값 |
|---|---|---|
| 안전재고 부족 품목 | “없음” 주변 설명 문구 차이 | `EMPTY_SET []` |
| 고객 불만 책임팀 | 구분자·어순 차이 | `ID_MAPPING {cs01: 고객지원팀, cs02: 고객지원팀, cs03: 영업운영팀}` |
| 최다 가용재고 품목 | 수량 부가 설명 유무 | `ID_LIST [p005]` |
| 세금계산서 마감 | unit 문자열·본문 형식 차이 | `5 business_day_next_month` |

After에서 실제 불안정으로 남은 업무는 월 주문금액(2회 답변·1회 보류)과 최근 주문일(1회 답변·2회 보류)이다. 이 둘은 `MIXED_OUTCOMES`다. 후속 [주문 원장 검색 경로 감사](PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md)에서 원장 파일과 Orders 테이블은 정상 파싱·인덱싱됐지만, 검색어와 상위-k에 따라 원장 노출 여부가 달라지는 제품 retrieval 한계가 재현됐다. 따라서 현재 표시는 `CAUSE_UNCONFIRMED`가 아니라 `RETRIEVAL_LIMITATION`이다. 거래처 최근 등록일과 일반 예외 승인 절차는 3/3 보류되어 데이터 신호로 남는다.

## 주장 범위

- v2의 Before 5/10→After 6/10은 기술적 재분류 결과이지 전체 개선의 인과 추정이 아니다.
- 실제 변경 파일은 FAQ 하나뿐이다.
- 방어 가능한 수정 효과는 반품 기간 업무의 0/3 충돌 보류→3/3 `30일` 답변 전환이다.
- Evidence `DIRECT_MATCH`와 업무 정답 보장은 서로 다른 주장이다.

## 검증

```powershell
python -m unittest tests.test_answer_comparison_v2 -v
python -m scripts.verify_phase6_demo_v4
```

두 번째 명령은 v1 frozen summary와 manifest가 그대로 재현되는지 확인한다.
