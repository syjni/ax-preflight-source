# 9/18 Feasibility Test — API and Budget Notes

Generated from `python feasibility_0918.py`. The dataset is tiny and entirely synthetic.

## Scope

Only the 9/18 vertical experiment was implemented. Scanner CLI, production parsers, remediation, Before/After/Ceiling, UI, and later phases were not started.

## Retrieval

- Whitespace BM25 Recall@5: **0.500**
- Character 2–3 gram BM25 Recall@5: **1.000**
- Delta: **+0.500**

## Observed tool calls

| Category | Tasks | Mean | Median | p95* | Max | Budget |
|---|---:|---:|---:|---:|---:|---:|
| knowledge | 4 | 1.75 | 1.50 | 3 | 3 | 6 |
| operations | 1 | 1.00 | 1.00 | 1 | 1 | 8 |
| cross_file | 1 | 4.00 | 4.00 | 4 | 4 | 12 |

*p95 uses nearest-rank and is not stable with this tiny sample; raw per-task traces are in `mini_benchmark_results.json`.*

## LLM measurement limitation

No OpenAI/AWS/local LLM provider or API credential was available in the execution environment. The deterministic task driver therefore made exactly **0 LLM calls** and recorded **0 input/output tokens** and **0 ms LLM latency** for every task. This is an honest measurement of this run, but it **does not validate live-LLM cost or latency**. The related feasibility assertion is intentionally `FAIL`, not silently waived.

For a live OpenAI run, record the Responses API `usage.input_tokens`, `usage.output_tokens`, and `usage.total_tokens`, plus wall-clock request latency. No live path was added because it could not be executed and verified today.

## Feasibility assertions

- **PASS** — `retrieval_char_recall_at_5_not_worse`: char=1.000, whitespace=0.500
- **PASS** — `four_tool_chain`: observed=['search_documents', 'read_document', 'lookup_value', 'query_table']
- **PASS** — `tool_counts_recorded`: per-task traces equal measured counts
- **FAIL** — `live_llm_telemetry`: NOT_RUN_MISSING_PROVIDER; calls/tokens/latency remain zero
- **PASS** — `three_deterministic_scorers`: 6/6 scorer cases passed
- **PASS** — `version_conflict_14_vs_30`: old=14 days, current=30 days
- **PASS** — `correct_abstention`: state=CORRECT_ABSTENTION
- **PASS** — `provenance_classification`: 5/5 provenance cases passed

## Reproduce

```powershell
python .easibility_0918.py
```

The command overwrites only the two JSON reports and this Markdown note with deterministic content except for run timestamp and measured latency.
