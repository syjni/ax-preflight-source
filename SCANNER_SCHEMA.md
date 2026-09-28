# Scanner CLI P0 schema

## Scope

This schema covers only the 9/19 local Scanner CLI milestone. The scanner recursively reads a directory, parses supported files locally, masks detected PII before JSON serialization, and emits deterministic structural findings. It has no LLM, database, UI, OCR, remediation, or semantic column-mapping dependency.

Run with the bundled Python environment or install `requirements.txt` and `requirements-dev.txt`:

```powershell
python -m ax_scanner <directory> --output scan_report.json --schema-output scan_report.schema.json
```

## Top-level structure

```text
scan_report.json
├─ scan_metadata
├─ files
├─ duplicates
├─ probable_version_groups
├─ pii_findings
├─ unreadable_sources
├─ tables
└─ live_llm
```

The authoritative typed schema is `ax_scanner.models.ScanReport`. The optional JSON Schema artifact is generated from that Pydantic model and the CLI validates the written report by parsing it back into the model.

## Decisions

- `file_id` is `FILE_` plus the first 16 hex characters of SHA-256 over the Unicode-NFC relative POSIX path. Moving the scan root does not change IDs; renaming a file does.
- `sha256` hashes the full file bytes and is the sole exact-duplicate key.
- `relative_path` is preserved with `/` separators and files are emitted in lexical path order.
- Parsed text and table `sample_values` in JSON are masked. Raw detected PII is never copied into `pii_findings`; findings contain type, offsets, length, and the replacement token.
- `probable_version_groups` use filename-only deterministic signals such as `v2`, a four-digit year, `final`/`최종`, `old`/`구버전`, and `rev`. These are candidates, not authoritative version decisions.
- A PDF is added to `unreadable_sources` when extracted non-whitespace text is below `max(per_page_threshold, page_count × per_page_threshold)`. OCR itself is out of scope.
- CSV uses `utf-8-sig`, UTF-8, then CP949 decoding. Delimiters are detected from a small fixed set.
- Spreadsheet `row_count` excludes the header and fully empty rows. `null_ratio` is computed across retained data rows. Samples are the first three distinct non-null values.
- `merged_cell_present` and `merged_ranges` are populated for XLSX; CSV reports no merged cells.
- Parser failures are recorded as `ERROR` per file so one corrupt file does not abort the folder scan.
- `live_llm` is telemetry state only and is isolated from scanning. Without credentials it remains `LIVE_LLM_PENDING`; this does not block the Scanner CLI.

## Known limitations

- PII rules are deterministic candidates and do not guarantee complete sensitive-data removal. Account-number matching is deliberately labeled as a candidate and can produce false positives.
- PDF extraction handles embedded text only. Image OCR, layout reconstruction, and table extraction are not implemented.
- DOCX extraction covers paragraphs and table-cell text; drawings, text boxes, comments, headers, footers, tracked-change semantics, and embedded objects are not interpreted.
- XLSX uses cached cell values and profiles worksheet cells. It does not calculate formulas, interpret macros, map semantic column aliases, or reconstruct complex multi-header tables.
- CSV dialect and encoding handling are intentionally small P0 heuristics.
