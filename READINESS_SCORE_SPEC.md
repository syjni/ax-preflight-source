# AX Readiness Score v1 specification

## Purpose and boundary

AX Readiness Score v1 is a deterministic static proxy calculated only from an AX Scanner report available before Agent execution. It makes no LLM calls and does not read Kiro output, task success, retrieval success, expected answers, primary blockers, semantic judgments, failure-attribution results, or held-out outcomes.

The reference implementation is `readiness_score.py`. Its output schema version is `ax-readiness-score-v1`.

## Frozen constants

- `AS_OF_DATE = 2026-09-21`
- `STALE_THRESHOLD_DAYS = 365`
- Accessibility weight: `0.20`
- Completeness weight: `0.20`
- Redundancy weight: `0.20`
- Timeliness weight: `0.20`
- Safety weight: `0.20`

Equal weights are used because no held-out evidence has been observed that justifies assigning greater predictive importance to any dimension. Weights must not be tuned against downstream task success.

Dimension values are ratios in `[0, 1]`. Numeric output is rounded to six decimal places using decimal round-half-up. The scalar is:

```text
Readiness Score = 100 × (
    0.20 × Accessibility
  + 0.20 × Completeness
  + 0.20 × Redundancy
  + 0.20 × Timeliness
  + 0.20 × Safety
)
```

## Dimensions

### A. Accessibility

A file is accessible exactly when its `parse_status` is `PARSED` and its file ID is not present in a Scanner unreadable-source record marked with `requires_ocr: true` or reason `OCR_REQUIRED`.

```text
Accessibility = accessible_files / total_files
```

If the file set is empty, Accessibility is `0.0` and `empty_file_set` is true.

### B. Completeness

Completeness uses only structured Scanner table profiles and is cell-weighted. For every table:

```text
cell_count = row_count × column_count
estimated_missing_cells = Σ(null_ratio(column) × row_count)
Completeness = 1 - total_estimated_missing_cells / total_cells
```

Tables are not weighted equally. A table profile is valid only when its declared `column_count` equals the number of column profiles, counts are non-negative integers, and every `null_ratio` is finite and within `[0, 1]`; invalid profiles are rejected rather than silently repaired.

NA policy: when there are no cells in eligible tables, Completeness is `1.0` and `completeness_not_applicable` is true. This means only that no structured missing cells were observed. It is not evidence that required data exists or that a non-tabular corpus is substantively complete.

### C. Redundancy

Only exact SHA-256 duplicate groups reported by the Scanner are used.

```text
redundant_files = Σ(group_size - 1)
Redundancy = 1 - redundant_files / total_files
```

Probable-version groups, filename similarity, semantic conflicts, and near-duplicates do not affect this dimension. Duplicate groups with unknown, repeated, or overlapping file IDs are rejected. If the file set is empty, Redundancy is `0.0` and `empty_file_set` is true.

### D. Timeliness

An ISO-8601 `modified_at` value is valid only when it includes a timezone. It is normalized to UTC and compared by calendar date with `AS_OF_DATE`.

```text
age_days = AS_OF_DATE - modified_at_utc_date
non_stale iff 0 <= age_days <= 365
Timeliness = non_stale_files / files_with_valid_modified_at
```

- Missing timestamps are excluded from the denominator and counted in `missing_modified_at_count`.
- Malformed or timezone-naive timestamps are excluded and counted in `invalid_modified_at_count`.
- Future timestamps are valid timestamps, remain in the denominator, fail the non-stale condition, and are counted in `future_modified_at_count`.
- If no valid timestamps exist, Timeliness is `0.0` and `no_valid_modified_at` is true.

The fixed date prevents execution date or future Agent knowledge from changing the metric.

### E. Safety

A PII-affected file is a known Scanner file ID with at least one Scanner `pii_findings` record. Multiple findings in the same file count once.

```text
Safety = 1 - pii_affected_files / total_files
```

Safety measures the fraction of files that do not immediately require PII handling before AI use. It is not a claim that all PII is bad data, and Scanner detection is not a complete privacy guarantee. Findings that reference unknown file IDs are flagged and do not change the numerator. If the file set is empty, Safety is `0.0` and `empty_file_set` is true.

## Output

The implementation returns:

- scalar `readiness_score`;
- all five `dimensions`;
- fixed `dimension_weights`;
- raw `counts` used by every calculation;
- `as_of_date` and `stale_threshold_days`;
- deterministic NA and invalid-data `flags`.

Canonical JSON serialization sorts keys, uses UTF-8-compatible JSON, and appends one newline so repeated runs on identical input are byte-identical.

## Explicit exclusions and limitations

Version 1 intentionally does not measure:

- semantic contradiction;
- terminology inconsistency;
- ontology or entity alignment;
- retrieval quality;
- LLM reasoning quality;
- Agent task success.

It also does not infer required-but-absent files, judge whether a timestamp represents substantive currency, measure PII severity, or treat probable versions as exact redundancy. These omissions allow later RQ3 analysis to reveal static Scanner blind spots instead of baking downstream outcomes into the proxy.
