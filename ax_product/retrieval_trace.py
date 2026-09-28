"""Run-bound retrieval trace derived from stored structured tool responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .evidence import ToolResponseRecord, response_source_ids
from .models import DeliveryEnvelope, StrictProductModel
from .tool_attempts import ToolAttemptRecord, ToolRequestSummary


class RetrievalCandidate(StrictProductModel):
    rank: int = Field(ge=1)
    title: str = Field(min_length=1)
    source_ids: list[str]
    cited: bool


class RetrievalStep(StrictProductModel):
    sequence: int = Field(ge=1)
    tool_name: Literal[
        "search_documents", "read_document", "lookup_value", "query_table"
    ]
    result_count: int = Field(ge=0)
    candidates: list[RetrievalCandidate]
    cited_source_ids: list[str]
    truncated: bool | None = None
    status: Literal["SUCCESS", "ERROR"] = "SUCCESS"
    request_summary: ToolRequestSummary | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "RetrievalStep":
        if self.status == "SUCCESS" and self.error_code is not None:
            raise ValueError("successful retrieval step forbids error_code")
        if self.status == "ERROR":
            if self.error_code is None:
                raise ValueError("failed retrieval step requires error_code")
            if self.result_count or self.candidates or self.cited_source_ids:
                raise ValueError("failed retrieval step cannot claim results or citations")
        return self


class RetrievalTrace(StrictProductModel):
    schema_version: Literal["ax-retrieval-trace-v2"] = "ax-retrieval-trace-v2"
    run_id: str = Field(min_length=1)
    cited_source_ids: list[str]
    steps: list[RetrievalStep]
    limitations: list[str]


def _strings(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [item for item in values if isinstance(item, str) and item]


def _count(output: dict[str, Any], field: str, fallback: int) -> int:
    value = output.get(field)
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else fallback
    )


def _candidate(
    *, rank: int, title: Any, source_ids: list[str], cited: set[str]
) -> RetrievalCandidate:
    clean_title = (
        title.strip()
        if isinstance(title, str) and title.strip()
        else source_ids[0]
        if source_ids
        else "식별자 없는 응답"
    )
    return RetrievalCandidate(
        rank=rank,
        title=clean_title,
        source_ids=source_ids,
        cited=bool(set(source_ids).intersection(cited)),
    )


def _search_step(
    record: ToolResponseRecord,
    cited: set[str],
    *,
    sequence: int | None = None,
    request_summary: ToolRequestSummary | None = None,
) -> RetrievalStep:
    raw_results = record.output.get("results")
    results = raw_results if isinstance(raw_results, list) else []
    candidates: list[RetrievalCandidate] = []
    for rank, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        source_ids = _strings(item.get("document_id"))
        tables = item.get("tables")
        if isinstance(tables, list):
            for table in tables:
                if isinstance(table, dict):
                    source_ids.extend(_strings(table.get("table_id")))
        candidates.append(
            _candidate(
                rank=rank,
                title=item.get("title"),
                source_ids=list(dict.fromkeys(source_ids)),
                cited=cited,
            )
        )
    observed = response_source_ids(record.tool_name, record.output)
    return RetrievalStep(
        sequence=sequence or record.sequence,
        tool_name=record.tool_name,
        result_count=_count(record.output, "results_returned", len(candidates)),
        candidates=candidates,
        cited_source_ids=sorted(observed.intersection(cited)),
        request_summary=request_summary,
    )


def _direct_step(
    record: ToolResponseRecord,
    cited: set[str],
    *,
    sequence: int | None = None,
    request_summary: ToolRequestSummary | None = None,
) -> RetrievalStep:
    source_ids = sorted(response_source_ids(record.tool_name, record.output))
    if record.tool_name == "read_document":
        result_count = 1 if source_ids else 0
        title = record.output.get("title")
    elif record.tool_name == "query_table":
        rows = record.output.get("rows")
        result_count = _count(
            record.output,
            "rows_returned",
            len(rows) if isinstance(rows, list) else 0,
        )
        title = record.output.get("table_id")
    else:
        value = record.output.get("value")
        result_count = 0 if value is None else len(value) if isinstance(value, list) else 1
        title = record.output.get("table_id")
    candidates = (
        [_candidate(rank=1, title=title, source_ids=source_ids, cited=cited)]
        if source_ids
        else []
    )
    truncated = record.output.get("truncated")
    return RetrievalStep(
        sequence=sequence or record.sequence,
        tool_name=record.tool_name,
        result_count=result_count,
        candidates=candidates,
        cited_source_ids=sorted(set(source_ids).intersection(cited)),
        truncated=truncated if isinstance(truncated, bool) else None,
        request_summary=request_summary,
    )


def build_retrieval_trace(
    delivery: DeliveryEnvelope,
    records: list[ToolResponseRecord],
    attempts: list[ToolAttemptRecord] | None = None,
) -> RetrievalTrace:
    """Expose sequence, candidates, and citation linkage without raw source content."""
    if any(record.run_id != delivery.run_id for record in records):
        raise ValueError("tool responses must belong to the delivery run")
    if attempts and any(attempt.run_id != delivery.run_id for attempt in attempts):
        raise ValueError("tool attempts must belong to the delivery run")
    cited = set(delivery.payload.source_ids) if delivery.payload is not None else set()
    if attempts:
        response_index = 0
        steps: list[RetrievalStep] = []
        for attempt in attempts:
            if attempt.status == "ERROR":
                steps.append(RetrievalStep(
                    sequence=attempt.sequence,
                    tool_name=attempt.tool_name,
                    result_count=0,
                    candidates=[],
                    cited_source_ids=[],
                    status="ERROR",
                    request_summary=attempt.request_summary,
                    error_code=attempt.error_code,
                ))
                continue
            if response_index >= len(records):
                raise ValueError("successful tool attempt is missing its response")
            record = records[response_index]
            response_index += 1
            if record.tool_name != attempt.tool_name:
                raise ValueError("tool attempt and response order do not match")
            builder = (
                _search_step
                if record.tool_name == "search_documents"
                else _direct_step
            )
            steps.append(builder(
                record,
                cited,
                sequence=attempt.sequence,
                request_summary=attempt.request_summary,
            ))
        if response_index != len(records):
            raise ValueError("tool response is missing its attempt record")
        limitations = [
            "Successful and failed data-tool attempts stored for this run are shown.",
            "Request summaries exclude raw query text and filter values.",
            "Candidate presence or rank is not an accuracy judgment.",
        ]
    else:
        steps = [
            _search_step(record, cited)
            if record.tool_name == "search_documents"
            else _direct_step(record, cited)
            for record in records
        ]
        limitations = [
            "Only successful structured data-tool responses stored for this run are shown.",
            "Tool request arguments are not stored, so the original search query and filters are not reconstructed.",
            "Candidate presence or rank is not an accuracy judgment.",
        ]
    return RetrievalTrace(
        run_id=delivery.run_id,
        cited_source_ids=sorted(cited),
        steps=steps,
        limitations=limitations,
    )
