# Phase 6 broad demo Evidence Checker 원인 분류

frozen v3 파일은 수정하지 않고, 당시 `UNCONFIRMED` 19건을 현재의 결정론적 규칙으로 다시 검사했다.

- 새 `DIRECT_MATCH`: **11 / 19**
- 남은 `UNCONFIRMED`: **8 / 19**
- frozen v3 수정: **false**

## 원인별 집계

- `ABSTENTION_EXPLANATION_NOT_LEXICALLY_PRESENT`: 4건
- `COMPLETE_TABLE_MAPPING`: 2건
- `COMPLETE_TABLE_PREDICATE`: 1건
- `CROSS_LANGUAGE_OR_SEMANTIC_PARAPHRASE`: 2건
- `QUERY_AGGREGATE_VALUE`: 6건
- `STRUCTURED_SCALAR_VALUE`: 2건
- `UNCITED_ABSTENTION`: 2건

## Run별 판정

| Run | Dataset | Task | 현재 판정 | 원인 |
| --- | --- | --- | --- | --- |
| `portfolio-portfolio-ceiling-after-task_billing_invoice_deadline-r1` | `portfolio-ceiling-after` | `TASK_BILLING_INVOICE_DEADLINE` | `UNCONFIRMED` | `CROSS_LANGUAGE_OR_SEMANTIC_PARAPHRASE` |
| `portfolio-portfolio-ceiling-after-task_customer_count-r1` | `portfolio-ceiling-after` | `TASK_CUSTOMER_COUNT` | `DIRECT_MATCH` | `QUERY_AGGREGATE_VALUE` |
| `portfolio-portfolio-ceiling-after-task_customer_latest_registration-r1` | `portfolio-ceiling-after` | `TASK_CUSTOMER_LATEST_REGISTRATION` | `UNCONFIRMED` | `ABSTENTION_EXPLANATION_NOT_LEXICALLY_PRESENT` |
| `portfolio-portfolio-ceiling-after-task_inventory_low_stock-r1` | `portfolio-ceiling-after` | `TASK_INVENTORY_LOW_STOCK` | `DIRECT_MATCH` | `COMPLETE_TABLE_PREDICATE` |
| `portfolio-portfolio-ceiling-after-task_inventory_most_available-r1` | `portfolio-ceiling-after` | `TASK_INVENTORY_MOST_AVAILABLE` | `DIRECT_MATCH` | `STRUCTURED_SCALAR_VALUE` |
| `portfolio-portfolio-ceiling-after-task_order_latest-r1` | `portfolio-ceiling-after` | `TASK_ORDER_LATEST` | `DIRECT_MATCH` | `QUERY_AGGREGATE_VALUE` |
| `portfolio-portfolio-ceiling-after-task_order_monthly_amount-r1` | `portfolio-ceiling-after` | `TASK_ORDER_MONTHLY_AMOUNT` | `DIRECT_MATCH` | `QUERY_AGGREGATE_VALUE` |
| `portfolio-portfolio-ceiling-after-task_policy_approval_procedure-r1` | `portfolio-ceiling-after` | `TASK_POLICY_APPROVAL_PROCEDURE` | `UNCONFIRMED` | `UNCITED_ABSTENTION` |
| `portfolio-portfolio-ceiling-after-task_support_responsible_team-r1` | `portfolio-ceiling-after` | `TASK_SUPPORT_RESPONSIBLE_TEAM` | `DIRECT_MATCH` | `COMPLETE_TABLE_MAPPING` |
| `portfolio-portfolio-hidden-conflict-before-task_billing_invoice_deadline-r1` | `portfolio-hidden-conflict-before` | `TASK_BILLING_INVOICE_DEADLINE` | `UNCONFIRMED` | `CROSS_LANGUAGE_OR_SEMANTIC_PARAPHRASE` |
| `portfolio-portfolio-hidden-conflict-before-task_customer_count-r1` | `portfolio-hidden-conflict-before` | `TASK_CUSTOMER_COUNT` | `DIRECT_MATCH` | `QUERY_AGGREGATE_VALUE` |
| `portfolio-portfolio-hidden-conflict-before-task_customer_latest_registration-r1` | `portfolio-hidden-conflict-before` | `TASK_CUSTOMER_LATEST_REGISTRATION` | `UNCONFIRMED` | `ABSTENTION_EXPLANATION_NOT_LEXICALLY_PRESENT` |
| `portfolio-portfolio-hidden-conflict-before-task_inventory_low_stock-r1` | `portfolio-hidden-conflict-before` | `TASK_INVENTORY_LOW_STOCK` | `UNCONFIRMED` | `ABSTENTION_EXPLANATION_NOT_LEXICALLY_PRESENT` |
| `portfolio-portfolio-hidden-conflict-before-task_inventory_most_available-r1` | `portfolio-hidden-conflict-before` | `TASK_INVENTORY_MOST_AVAILABLE` | `DIRECT_MATCH` | `STRUCTURED_SCALAR_VALUE` |
| `portfolio-portfolio-hidden-conflict-before-task_order_latest-r1` | `portfolio-hidden-conflict-before` | `TASK_ORDER_LATEST` | `DIRECT_MATCH` | `QUERY_AGGREGATE_VALUE` |
| `portfolio-portfolio-hidden-conflict-before-task_order_monthly_amount-r1` | `portfolio-hidden-conflict-before` | `TASK_ORDER_MONTHLY_AMOUNT` | `DIRECT_MATCH` | `QUERY_AGGREGATE_VALUE` |
| `portfolio-portfolio-hidden-conflict-before-task_policy_approval_procedure-r1` | `portfolio-hidden-conflict-before` | `TASK_POLICY_APPROVAL_PROCEDURE` | `UNCONFIRMED` | `UNCITED_ABSTENTION` |
| `portfolio-portfolio-hidden-conflict-before-task_policy_return_window-r1` | `portfolio-hidden-conflict-before` | `TASK_POLICY_RETURN_WINDOW` | `UNCONFIRMED` | `ABSTENTION_EXPLANATION_NOT_LEXICALLY_PRESENT` |
| `portfolio-portfolio-hidden-conflict-before-task_support_responsible_team-r1` | `portfolio-hidden-conflict-before` | `TASK_SUPPORT_RESPONSIBLE_TEAM` | `DIRECT_MATCH` | `COMPLETE_TABLE_MAPPING` |

`UNCONFIRMED`는 오답 판정이 아니다.
