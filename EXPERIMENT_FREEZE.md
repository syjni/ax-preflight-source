# AX Experiment Freeze Result

Experiment: `ax-exp-v1`

Status: **FROZEN**

Freeze timestamp (UTC): `2026-09-19T12:27:02.417142Z`

Official Agent: Kiro `ax-evaluation`

Model: `claude-sonnet-5`

Execution Backend: `INTERACTIVE_FRESH_PROCESS`

Retrieval: **FROZEN**

Readiness Score: **FROZEN v1**

Readiness Formula: `100 × Σ(dimension × 0.20)`, the equal-weight mean of Accessibility, Completeness, Redundancy, Timeliness, and Safety

Ceiling Readiness: `100.0`

Prompt: v2, SHA-256 `dc783a41a5b06eb871ada33be7dd21aec2e4106757a40921ddf59fcf81176fc8`

Dev semantic grounded: `5/5`

Dev strict output: `3/5`

Dev semantic JSON availability: `5/5`

Headless: **UNAVAILABLE**

Held-out executed: `0`

Regression tests: `88/88 PASS`

Leakage: `0` violations

Frozen artifact count: `159` unique files

Git commit: `null` because this workspace is not a Git repository; no commit was fabricated.

Remaining blocker: none

Next safe action: on a later authorized day, execute the 16 held-out tasks under the frozen interactive protocol. Do not execute held-out runs as part of this freeze.

## Freeze inventory

The machine-verifiable inventory, per-file SHA-256 values, component aggregate hashes, runtime identity, split, and freeze policy are in `experiment/frozen/ax-exp-v1-manifest.json`.

### Behavioral and configuration artifacts

| # | Frozen component | Concrete artifact boundary |
|---:|---|---|
| 1 | Kiro agent configuration | `.kiro/agents/ax-evaluation.json` |
| 2 | Kiro system/behavior prompt | prompt bytes in the agent config plus `.kiro/ax-evaluation.prompt-metadata.json` |
| 3 | Evaluation model ID | `claude-sonnet-5` in the agent config |
| 4 | Interactive execution protocol | `INTERACTIVE_EXECUTION.md` |
| 5 | MCP server implementation | all Python files under `ax_mcp/` |
| 6 | MCP schemas | `ax_agent/models.py`, `ax_mcp/adapter.py`, `agent_tool_schemas.json`, and `runtime_blind_sample.schema.json` |
| 7 | Retrieval implementation/configuration | all Python files under `ax_agent/` |
| 8 | Scanner implementation/configuration | all Python files under `ax_scanner/`, `SCANNER_SCHEMA.md`, and `scan_report.schema.json` |
| 9 | Runtime dataset profile configuration | `runtime_datasets.json`, `ax_mcp/runtime_dataset.py`, and `ax_mcp/runtime_identity.py` |
| 10 | Ceiling dataset manifest | `dataset_manifest.json` |
| 11 | Benchmark manifest | `benchmark_tasks.json` |
| 12 | Ground truth | `ground_truth.json` |
| 13 | Task-to-defect manifest | `task_to_defect_manifest.json` |
| 14 | Control-source manifest | `control_sources.json` |
| 15 | Deterministic scorer | `scripts/ceiling_scoring.py` |
| 16 | Output-contract validator | strict validator in `scripts/output_contract.py` |
| 17 | Semantic JSON extractor | analysis-only extractor in `scripts/output_contract.py` |
| 18 | Failure taxonomy | `EXPERIMENT_FAILURE_TAXONOMY.md`, its existing plan source, scorer, and output-contract implementation |
| 19 | Runtime prompt constructor | `scripts/runtime_prompt.py` |
| 20 | Leakage validator | blind-gate and Ceiling validation modules listed in the manifest |
| 21 | Interactive run recorder | `scripts/interactive_run.py` |
| 22 | Readiness implementation | `readiness_score.py` |
| 23 | Readiness specification | `READINESS_SCORE_SPEC.md` |
| 24 | Dataset-condition generators | the canonical Ceiling generation entry points, generator, and independent-truth generator listed in the manifest |

The frozen boundary also includes `EXPERIMENT_HYPOTHESES.md` and the Python dependency constraints.

### Raw evidence and logs

Raw evidence is inventoried separately from behavior/configuration:

- all 30 Ceiling source files under `sample_data/ceiling_company/`;
- `ceiling_scan_report.json`, `ceiling_validation.json`, and dataset provenance;
- Dev-only interactive run evidence and headless-availability diagnostics;
- prepared-not-run blind-gate receipts;
- pre-freeze MCP logs, runtime-identity receipts, and tool-contract captures.

Evidence and log artifacts do not redefine behavior. Their bytes are hashed so the provenance supporting this receipt can be checked without mixing them into the behavioral component list.

## Readiness Score v1 freeze

The frozen deterministic definitions are:

- Accessibility = `accessible_files / total_files`
- Completeness = cell-weighted non-missing fraction
- Redundancy = `1 - redundant_files / total_files`
- Timeliness = `non_stale_files / valid_timestamp_files`
- Safety = `1 - PII_affected_files / total_files`
- Weights = `0.20` each
- `AS_OF_DATE = 2026-09-21`
- `STALE_THRESHOLD_DAYS = 365`

The implementation makes no LLM call, reads no held-out Agent result, and reads no benchmark expected answer. Ceiling deterministically scores `100.0`; the formula was not altered because Ceiling is perfect.

## Official run protocol

One official run is:

```text
fresh Kiro interactive process
→ ax-evaluation
→ claude-sonnet-5
→ explicit dataset profile
→ exactly one task
→ preserve raw response
→ preserve MCP invocation log
→ record metadata/result
→ terminate process
```

Resume, cross-task session context, manual answer correction, model fallback, and tool expansion are forbidden. The frozen tool surface is exactly `search_documents`, `read_document`, `lookup_value`, and `query_table` through the AX MCP server.

## Frozen output-contract limitation

Strict Dev compliance is `3/5`, semantic grounded correctness is `5/5`, and semantic JSON availability is `5/5`. This is a measured limitation; no further prompt tuning is allowed.

Leading/trailing prose or Markdown fences set `output_contract_valid = 0`, and the primary failure may be `F6_OUTPUT_CONTRACT`. One unambiguous schema-valid JSON object may still be extracted for separate answer/source analysis, but the raw response remains unchanged and malformed JSON is never repaired.

## Dev and held-out inventory

Dev tasks are:

- `O01_CUSTOMER_COUNT`
- `O05_HIGHEST_AVAILABLE_STOCK`
- `C01_HANBIT_AUGUST_TOTAL`
- `C04_YUNSEONG_LAST_ORDER`
- `C07_DAON_TOP_ORDER_PRODUCT`

The 16 held-out task IDs are:

- `K01_RETURN_WINDOW`
- `K02_RETURN_REQUIREMENTS`
- `K03_DELAY_COMPENSATION_THRESHOLD`
- `K04_DISCOUNT_APPROVER`
- `K05_STOCK_REFERENCE_FIELD`
- `K06_FIRST_RESPONSE_TARGET`
- `O02_SEPTEMBER_ORDER_TOTAL`
- `O03_GREEN_TABLE_LAST_ORDER`
- `O04_PRODUCT_MASTER_COUNT`
- `O06_RETURN_RATE`
- `O07_SEOUL_LEAD_TIME`
- `C02_DONGHAE_SEPTEMBER_TOTAL`
- `C03_TEA_STOCK`
- `C05_SAEBOM_JULY_TOTAL`
- `C06_ARAM_AUGUST_RETURNS`
- `K07_VENDOR_FORECAST_ABSTAIN`

No held-out answer is reproduced in this receipt, and no held-out task was executed.

## Freeze validation

- Every manifest artifact hash recomputed with zero mismatches.
- Ceiling runtime identity is unchanged.
- Model is `claude-sonnet-5`.
- Exactly four AX MCP tools are exposed.
- Runtime leakage has zero violations.
- Held-out execution count is zero.
- The 5/16 Dev/held-out split is unchanged.
- Retrieval, dataset, benchmark, ground truth, and prompt v2 hash are unchanged.
- Readiness implementation/spec hashes are recorded and Ceiling remains `100.0`.
- The interactive protocol is complete and headless unavailability is explicit.

## Post-freeze change policy

Any outcome-affecting change after this freeze requires existing `ax-exp-v1` results, if any, to be archived or marked invalid, creation of `ax-exp-v2`, recomputation of all hashes, and rerunning both compared conditions under v2. Display-only report formatting may change only when it cannot affect raw data, scoring, or interpretation.

## Final state

**AX is READY_FOR_HELDOUT. Do not execute held-out runs today.**
