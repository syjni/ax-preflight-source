# Phase 6 Product Demo Results

- Scope: `PRODUCT_SANITY_DEMO_NOT_RESEARCH_BENCHMARK`
- Question: 현재 반품 가능 기간은 며칠인가요?
- Model: `claude-sonnet-5`
- Official runs: 2
- Sanity criterion: FAIL

This is a product sanity/demo result. It is not merged into v3/v5 metrics and is not claimed as a new research benchmark result.

## Static comparison

| State | Readiness | Accessibility | Completeness | Redundancy | Timeliness | Safety | Version warnings |
|---|---:|---:|---:|---:|---:|---:|---:|
| demo-return-before | 100.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1 |
| demo-return-after | 100.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0 |

Totals equal: `True`; all five dimensions equal: `True`.

## Run results

| # | Run ID | Profile | Delivery | Payload | Abstention reason | Source IDs | Evidence |
|---:|---|---|---|---|---|---|---|
| 1 | `phase6demo-pilot-pilot-001-01-before-40f89ff8` | demo-return-before | REJECTED | - | - | - | UNCONFIRMED |
| 2 | `phase6demo-pilot-pilot-001-02-after-23e6ccb3` | demo-return-after | REJECTED | - | - | - | UNCONFIRMED |

## Observed frequencies

- demo-return-before: ANSWERED 0, ABSTAINED 0, REJECTED 1
- demo-return-after: ANSWERED 0, ABSTAINED 0, REJECTED 1

The observed frequencies are stochastic outcomes from these six runs; they are not a guarantee of future behavior.
