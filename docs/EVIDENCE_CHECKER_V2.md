# Evidence Checker frozen v2 설명

## 무엇이 바뀌었나

Phase 6 v1 결과는 수정하지 않았다. frozen v2는 v1의 6개 `delivery.json`과 같은-run `tool-responses`를 바이트 해시로 복사하고, 현재 Evidence Checker로 `evidence-check.json`만 다시 계산한 별도 snapshot이다.

변경 규칙은 특정 반품 문구를 예외 처리하지 않는다. 답 전체가 `숫자 + 단위`인 수량 표현이면 숫자와 단위를 분리하고, payload에 별도 unit이 있을 때 두 단위가 같은 family인지 확인한다. 이후 인용된 같은-run 응답의 같은 문장 또는 구조화 cell에서 동일한 숫자와 허용 단위가 함께 나타날 때만 `DIRECT_MATCH`로 인정한다.

따라서 `30일`, `30 days` 같은 수량 표현을 다루지만 다음은 승격하지 않는다.

- 인용되지 않은 다른 run 또는 다른 source의 값
- 숫자만 우연히 같은 값
- 선언 unit과 embedded unit의 family가 다른 값
- division, 비율 변환, 단위 환산처럼 v1 계약에 없는 계산
- `ABSTAINED` delivery

## 공식 Phase 6 결과

- v1 manifest SHA-256: `515930fde7dee2e1b84fa90b79ccf33511359116a5b44bbd042fab486d8befd9`
- v1 입력 변경: 0
- After: 기존 `DIRECT_MATCH` 1/3 → v2 `DIRECT_MATCH` 3/3
- Before: `UNCONFIRMED` 3/3 → v2에서도 `UNCONFIRMED` 3/3
- 바뀐 파일: v2의 `evidence-check.json` 2개뿐

`UNCONFIRMED`는 오답 판정이 아니라 자동 확인 범위 밖이라는 뜻이다.

## 데모 외 데이터 회귀 확인

기존 v5 연구 실행 32건에 현재 checker를 다시 적용했다. 결과는 보존된 Phase 5 비교 파일과 byte-identical했다.

- 비교 run: 32
- 수작업 감사와 계약상 일치: 25
- 불일치: 7
- checker 판정: `DIRECT_MATCH` 22, `PARTIAL_SUPPORT` 1, `UNCONFIRMED` 9
- JSON SHA-256: `c97073030b868ee5c1543f327d3cc5e60844a3f3d98a33736bbf63bf8754b03e`
- Markdown SHA-256: `cc9ff649d0ee1ba54203e2f66feb7382cc7931e0f2cb0958c70f751033c3e81a`

이 수치는 Agent 성능 지표가 아니다. 데모용 규칙 수정이 무관한 32개 기존 비교 결과를 악화시키거나 바꾸지 않았다는 회귀 확인이다. 7건의 불일치는 checker가 의도적으로 지원하지 않는 division/rate 및 단위 변환 범위에 남아 있다.

## 재현 명령

```bash
python -m scripts.verify_phase6_demo
python -m scripts.verify_phase6_demo_v2
python -m scripts.verify_phase6_demo_v3
python -m scripts.compare_v5_evidence_checker
```

frozen v3의 10업무 포트폴리오에도 같은 checker를 변경 없이 적용했다. Before 10건은 보류를 포함해 모두 `UNCONFIRMED`, After는 반품 기간 1건이 `DIRECT_MATCH`, 나머지 9건은 `UNCONFIRMED`였다. 이는 broad demo에 맞춰 checker 범위를 추가 확장하지 않았다는 보수적 결과이며, 포트폴리오의 성공률 지표로 사용하지 않는다.

마지막 명령 후 `artifacts/phase5_evidence_checker_v1/V5_MANUAL_COMPARISON.json`과 `.md`에 diff가 없어야 한다.
