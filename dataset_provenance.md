# Ceiling dataset provenance

## Scope

`sample_data/ceiling_company` is a clean, internally consistent synthetic dataset for the AX Benchmark Mode Ceiling condition. It represents **한빛유통**, a 45-person Korean SME distributor of food and household goods. All company names, documents, product names, customers, identifiers, policies, and figures are fictional.

## Numeric distributions

No public dataset was incorporated. The deterministic generator uses Python's standard-library pseudo-random generator with seed `20260921` to create an intentionally realistic distribution:

- 180 orders across 2026-05-01 through the fixed as-of date 2026-09-21;
- weighted customer and product frequencies, rather than uniform selection;
- gamma-distributed integer quantities, bounded from 1 to 42;
- product-specific unit prices and exact `amount = quantity × unit_price` values;
- inventory quantities using a separate bounded gamma distribution;
- returns sampled from shipped orders with quantities no greater than the shipped quantity.

Because these numbers are generated from code rather than copied from a public source, there is no external data license to attribute. The generated fixture and its code are maintained as project test data.

## Leakage boundary

The company folder and `ceiling_scan_report.json` are runtime-facing evidence only. `benchmark_tasks.json`, `ground_truth.json`, `control_sources.json`, and `ceiling_validation.json` are evaluation-only artifacts and are not placed in the runtime company folder or the Kiro agent resources.
