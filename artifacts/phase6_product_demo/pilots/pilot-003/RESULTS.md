# Phase 6 Product Demo Results

- Scope: `PRODUCT_SANITY_DEMO_NOT_RESEARCH_BENCHMARK`
- Question: 현재 반품 가능 기간은 며칠인가요?
- Model: `claude-sonnet-5`
- Official runs: 2
- Sanity criterion: PASS

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
| 1 | `phase6demo-pilot-pilot-003-01-before-eeda5407` | demo-return-before | DELIVERED | ABSTAINED | CONFLICTING_EVIDENCE | FILE_0190582b04c0b44a, FILE_afb4c3a0cc53d8c8 | UNCONFIRMED |
| 2 | `phase6demo-pilot-pilot-003-02-after-53225801` | demo-return-after | DELIVERED | ANSWERED | - | FILE_5587cb5d2ae64ba9 | UNCONFIRMED |

## Observed frequencies

- demo-return-before: ANSWERED 0, ABSTAINED 1, REJECTED 0
- demo-return-after: ANSWERED 1, ABSTAINED 0, REJECTED 0

The observed frequencies are stochastic outcomes from these six runs; they are not a guarantee of future behavior.
