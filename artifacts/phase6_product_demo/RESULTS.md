# Phase 6 Product Demo Results

- Scope: `PRODUCT_SANITY_DEMO_NOT_RESEARCH_BENCHMARK`
- Question: 현재 반품 가능 기간은 며칠인가요?
- Model: `claude-sonnet-5`
- Mode: `official`
- Runs: 6
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
| 1 | `phase6demo-official-official-001-01-before-489834b1` | demo-return-before | DELIVERED | ABSTAINED | CONFLICTING_EVIDENCE | FILE_0190582b04c0b44a, FILE_afb4c3a0cc53d8c8 | UNCONFIRMED |
| 2 | `phase6demo-official-official-001-02-after-02d170f8` | demo-return-after | DELIVERED | ANSWERED | - | FILE_5587cb5d2ae64ba9, FILE_bac911e84aac7c01 | DIRECT_MATCH |
| 3 | `phase6demo-official-official-001-03-before-1c3baf2d` | demo-return-before | DELIVERED | ABSTAINED | CONFLICTING_EVIDENCE | FILE_0190582b04c0b44a, FILE_afb4c3a0cc53d8c8 | UNCONFIRMED |
| 4 | `phase6demo-official-official-001-04-after-7b4095d7` | demo-return-after | DELIVERED | ANSWERED | - | FILE_5587cb5d2ae64ba9 | UNCONFIRMED |
| 5 | `phase6demo-official-official-001-05-before-2e03fdf6` | demo-return-before | DELIVERED | ABSTAINED | CONFLICTING_EVIDENCE | FILE_0190582b04c0b44a, FILE_afb4c3a0cc53d8c8 | UNCONFIRMED |
| 6 | `phase6demo-official-official-001-06-after-233af967` | demo-return-after | DELIVERED | ANSWERED | - | FILE_5587cb5d2ae64ba9 | UNCONFIRMED |

## Observed frequencies

- demo-return-before: ANSWERED 0, ABSTAINED 3, REJECTED 0
- demo-return-after: ANSWERED 3, ABSTAINED 0, REJECTED 0

The observed frequencies are stochastic outcomes from these 6 runs; they are not a guarantee of future behavior.
