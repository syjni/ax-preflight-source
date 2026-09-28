# Evidence Checker v1 — v5 수작업 감사 32건 대조

이 문서는 사후 호환성 대조다. 새 Agent 성능 지표가 아니며 v5 공식 결과를 수정하지 않는다. Checker에는 승인된 `delivered.json`과 같은 run의 인용된 구조화 tool 응답만 입력했다.

- 일치: **25/32**
- 불일치: **7/32**
- Checker 판정: `DIRECT_MATCH` 22, `PARTIAL_SUPPORT` 1, `UNCONFIRMED` 9
- `UNCONFIRMED`는 오답이 아니라 확인 불가다.

| 과제 | 회차 | 수작업 감사 | Checker v1 | 대조 | 메모 |
| --- | ---: | --- | --- | --- | --- |
| V5_R01_ONLINE_RETURN_APPROVAL_RATE | 1 | SUPPORTED_AND_CITED | UNCONFIRMED | 불일치 | Manual audit derived a rate/division, but checker v1 excludes division and unit conversion; other unrelated numeric cells no longer create partial support. |
| V5_R01_ONLINE_RETURN_APPROVAL_RATE | 2 | SUPPORTED_AND_CITED | UNCONFIRMED | 불일치 | Manual audit derived a rate/division, but checker v1 excludes division and unit conversion; other unrelated numeric cells no longer create partial support. |
| V5_R02_DEALER_RETURN_APPROVAL_RATE | 1 | SUPPORTED_AND_CITED | UNCONFIRMED | 불일치 | Manual audit derived a rate/division, but checker v1 excludes division and unit conversion; other unrelated numeric cells no longer create partial support. |
| V5_R02_DEALER_RETURN_APPROVAL_RATE | 2 | SUPPORTED_AND_CITED | UNCONFIRMED | 불일치 | Manual audit derived a rate/division, but checker v1 excludes division and unit conversion; other unrelated numeric cells no longer create partial support. |
| V5_R03_DIRECT_RETURN_APPROVAL_RATE | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_R03_DIRECT_RETURN_APPROVAL_RATE | 2 | SUPPORTED_AND_CITED | PARTIAL_SUPPORT | 불일치 | Manual audit verified a rate/division; checker v1 found the answer value but cannot verify the required unit relationship or division. |
| V5_R04_BUSINESS_RETURN_APPROVAL_RATE | 1 | SUPPORTED_AND_CITED | UNCONFIRMED | 불일치 | Manual audit derived a rate/division, but checker v1 excludes division and unit conversion; other unrelated numeric cells no longer create partial support. |
| V5_R04_BUSINESS_RETURN_APPROVAL_RATE | 2 | SUPPORTED_AND_CITED | UNCONFIRMED | 불일치 | Manual audit derived a rate/division, but checker v1 excludes division and unit conversion; other unrelated numeric cells no longer create partial support. |
| V5_T01_COOLANT_PRESSURE_NOTICE_THRESHOLD | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_T01_COOLANT_PRESSURE_NOTICE_THRESHOLD | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_T02_PACKER_SENSOR_NOTICE_THRESHOLD | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_T02_PACKER_SENSOR_NOTICE_THRESHOLD | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_T03_FILLING_LEAK_NOTICE_THRESHOLD | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_T03_FILLING_LEAK_NOTICE_THRESHOLD | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_T04_SHIPPING_LABEL_NOTICE_THRESHOLD | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_T04_SHIPPING_LABEL_NOTICE_THRESHOLD | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_S01_SAFETY_INSPECTION_EVIDENCE | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_S01_SAFETY_INSPECTION_EVIDENCE | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_S02_VENDOR_VISIT_EVIDENCE | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_S02_VENDOR_VISIT_EVIDENCE | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_S03_TEST_MATERIAL_EVIDENCE | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_S03_TEST_MATERIAL_EVIDENCE | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_S04_PROCESS_CHANGE_EVIDENCE | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_S04_PROCESS_CHANGE_EVIDENCE | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_E01_MAINTENANCE_PLAN_APPROVER | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_E01_MAINTENANCE_PLAN_APPROVER | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_E02_VENDOR_REGISTRATION_APPROVER | 1 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_E02_VENDOR_REGISTRATION_APPROVER | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_E03_OVERSEAS_PLANT_APPROVER | 1 | SUPPORTED_SOURCE_ID_MISSING | UNCONFIRMED | 일치 | Manual audit found content support, but the delivery cited no source ID; checker does not use uncited responses. |
| V5_E03_OVERSEAS_PLANT_APPROVER | 2 | SUPPORTED_AND_CITED | DIRECT_MATCH | 일치 |  |
| V5_E04_AI_INSPECTION_APPROVER | 1 | SUPPORTED_SOURCE_ID_MISSING | UNCONFIRMED | 일치 | Manual audit found content support, but the delivery cited no source ID; checker does not use uncited responses. |
| V5_E04_AI_INSPECTION_APPROVER | 2 | SUPPORTED_SOURCE_ID_MISSING | UNCONFIRMED | 일치 | Manual audit found content support, but the delivery cited no source ID; checker does not use uncited responses. |

## 한계

- The 32 records are two repeats of 16 tasks over four short files, not 32 independent tasks.
- Manual auditors allowed division/rate and unit conversion; checker v1 intentionally does not.
- UNCONFIRMED means not verified under the checker contract, not an incorrect answer.
- This retrospective v5 comparison does not establish production or Agent performance.
