# 9/20 Agent Tools and Context Policy

This layer consumes the 9/19 `ScanReport` as a stable contract. It does not change scanner models, scanner behavior, `scan_report.json`, or `scan_report.schema.json`.

## Model-callable tools

Only these four tools are exposed by `ax_agent.tools.tool_schema_catalog()`:

- `search_documents(query, top_k=5)`: char 2-3 gram BM25 over masked scanner text. `top_k` is validated as 1-10. Each hit contains the scanner file ID, title, `document_type`, limited metadata, a snippet of at most 400 characters, and a score. Tabular hits also contain `tables[]` entries with the exact `table_id`, sheet name, and column names accepted by both table tools.
- `read_document(document_id, section=None)`: numeric, zero-based sections. Each call returns at most 2,500 characters and an optional `next_section`.
- `lookup_value(table_id, match_column, value, return_column)`: exact matching after Unicode NFKC, lowercase, corporate-marker removal, whitespace/punctuation normalization. Use an exact `tables[].table_id` from `search_documents`; fuzzy matching is intentionally out of scope.
- `query_table(...)`: the restricted DSL below. Use an exact `tables[].table_id` from `search_documents`. No SQL string or arbitrary expression is accepted.

There is no model-callable Python, shell, SQL, filesystem, or generic code-execution tool.

Never guess a `table_id`. Obtain it from `search_documents` metadata and pass the exact
`tables[].table_id` unchanged to either `lookup_value` or `query_table`.

## Restricted table DSL

Filters are typed clauses:

```json
{"field":"customer_id","op":"eq","value":"C013"}
```

Supported operators are `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `prefix`, and `in`.

Aggregations are typed objects:

```json
{"op":"sum","field":"amount","alias":"total_amount"}
```

Supported operations are `sum`, `avg`, `count`, `min`, `max`, and `rate`. `rate` requires explicit `numerator_field` and `denominator_field`; a zero denominator returns `null`. `group_by` is accepted only with an aggregation. Ordering is `asc` or `desc`. `limit` is validated as 1-10; values over 10 fail validation rather than being silently clamped.

Source rows are loaded server-side only from CSV/XLSX files referenced by the scanner report. Raw tables are never returned to the model. Results are projected or aggregated first and always capped at 10 rows. String outputs pass through the existing deterministic PII masker.

## Structured output and budgets

Final agent output is validated as:

```json
{
  "final_answer": 200000,
  "unit": "KRW",
  "explanation": "...",
  "source_ids": ["TABLE_...", "TABLE_..."],
  "abstain": false
}
```

An abstaining answer must have `final_answer: null`; a non-abstaining answer must contain a value.

Budgets are fixed at Knowledge 6, Operations 8, and Cross-file 12. Every executed tool call is timed and recorded. A call after the limit is rejected with `AGENT_BUDGET_EXCEEDED`; the budget is not increased and the rejected operation is not executed.

Run the reproducible experiment:

```powershell
python -m scripts.run_agent_tool_smoke
```

It writes `agent_tool_results.json` and `agent_tool_schemas.json`.
