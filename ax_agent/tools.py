from __future__ import annotations

import json
import math
import statistics
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from ax_scanner.models import ScanReport
from ax_scanner.pii import detect_pii, mask_text

from .errors import AgentBudgetExceeded, AgentToolError
from .models import (
    AggregationOperator,
    AggregationSpec,
    FilterClause,
    FilterOperator,
    LookupValueInput,
    LookupValueOutput,
    OrderByClause,
    QueryTableInput,
    QueryTableOutput,
    ReadDocumentInput,
    ReadDocumentOutput,
    SearchDocumentsInput,
    SearchDocumentsOutput,
    SortDirection,
    TOOL_BUDGETS,
    TaskCategory,
    TaskToolMetrics,
    ToolCallEvent,
)
from .normalization import normalize_canonical_value, normalize_text
from .retrieval import DocumentIndex
from .table_store import TableStore


READ_CHUNK_CHARACTERS = 2500
MAX_TABLE_ROWS = 10
T = TypeVar("T")


def _mask_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return mask_text(value, detect_pii(value))
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _as_number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise AgentToolError("NON_NUMERIC_AGGREGATION", f"not numeric: {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AgentToolError("NON_NUMERIC_AGGREGATION", f"not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise AgentToolError("NON_NUMERIC_AGGREGATION", f"not finite: {value!r}")
    return number


def _compact_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def tool_schema_catalog() -> dict[str, dict[str, Any]]:
    """Only these four model-callable tools are exposed; no Python, shell, or SQL."""
    pairs: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
        "search_documents": (SearchDocumentsInput, SearchDocumentsOutput),
        "read_document": (ReadDocumentInput, ReadDocumentOutput),
        "lookup_value": (LookupValueInput, LookupValueOutput),
        "query_table": (QueryTableInput, QueryTableOutput),
    }
    return {
        name: {"input_schema": input_model.model_json_schema(), "output_schema": output_model.model_json_schema()}
        for name, (input_model, output_model) in pairs.items()
    }


class AgentToolLayer:
    def __init__(self, scan_report_path: str | Path, source_root: str | Path):
        payload = json.loads(Path(scan_report_path).read_text(encoding="utf-8"))
        self.report = ScanReport.model_validate(payload)
        self.documents = {record.file_id: record for record in self.report.files}
        self.index = DocumentIndex(self.report.files, self.report.tables)
        self.table_store = TableStore(self.report, Path(source_root))

    def start_task(self, task_id: str, category: TaskCategory | str) -> "ToolSession":
        return ToolSession(self, task_id, TaskCategory(category))


class ToolSession:
    def __init__(self, layer: AgentToolLayer, task_id: str, category: TaskCategory):
        self.layer = layer
        self.task_id = task_id
        self.category = category
        self.budget = TOOL_BUDGETS[category]
        self.events: list[ToolCallEvent] = []
        self.budget_exceeded = False

    def _invoke(self, tool: str, arguments: dict[str, Any], operation: Callable[[], T]) -> T:
        if len(self.events) >= self.budget:
            self.budget_exceeded = True
            raise AgentBudgetExceeded(self.category.value, self.budget)
        started = time.perf_counter()
        source_ids: list[str] = []
        summary: dict[str, Any] = {}
        success = False
        error_code: str | None = None
        try:
            result = operation()
            source_ids = list(getattr(result, "source_ids", []))
            if isinstance(result, SearchDocumentsOutput):
                source_ids = [hit.document_id for hit in result.results]
                summary = {"results_returned": result.results_returned}
            elif isinstance(result, ReadDocumentOutput):
                source_ids = [result.document_id]
                summary = {"characters_returned": result.characters_returned, "section": result.section}
            elif isinstance(result, LookupValueOutput):
                summary = {"matched_rows": result.matched_rows, "ambiguous": result.ambiguous}
            elif isinstance(result, QueryTableOutput):
                summary = {"rows_returned": result.rows_returned, "source_rows_matched": result.source_rows_matched}
            success = True
            return result
        except AgentToolError as exc:
            error_code = exc.code
            summary = {"error": exc.message}
            raise
        finally:
            self.events.append(
                ToolCallEvent(
                    sequence=len(self.events) + 1,
                    tool=tool,
                    arguments=arguments,
                    latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    success=success,
                    error_code=error_code,
                    source_ids=source_ids,
                    result_summary=summary,
                )
            )

    def search_documents(self, query: str, top_k: int = 5) -> SearchDocumentsOutput:
        request = SearchDocumentsInput(query=query, top_k=top_k)

        def operation() -> SearchDocumentsOutput:
            results = self.layer.index.search(request.query, request.top_k)
            return SearchDocumentsOutput(results=results, results_returned=len(results))

        return self._invoke("search_documents", request.model_dump(mode="json"), operation)

    def read_document(self, document_id: str, section: int | None = None) -> ReadDocumentOutput:
        request = ReadDocumentInput(document_id=document_id, section=section)

        def operation() -> ReadDocumentOutput:
            record = self.layer.documents.get(request.document_id)
            if record is None:
                raise AgentToolError("DOCUMENT_NOT_FOUND", f"unknown document_id: {request.document_id}")
            section_index = request.section or 0
            start = section_index * READ_CHUNK_CHARACTERS
            if start > len(record.text):
                raise AgentToolError("SECTION_OUT_OF_RANGE", f"section {section_index} is outside the document")
            content = record.text[start : start + READ_CHUNK_CHARACTERS]
            next_section = section_index + 1 if start + READ_CHUNK_CHARACTERS < len(record.text) else None
            return ReadDocumentOutput(
                document_id=record.file_id,
                title=record.filename,
                section=section_index,
                content=content,
                characters_returned=len(content),
                total_characters=len(record.text),
                next_section=next_section,
                truncated=next_section is not None,
            )

        return self._invoke("read_document", request.model_dump(mode="json"), operation)

    def lookup_value(
        self,
        table_id: str,
        match_column: str,
        value: str | int | float | bool,
        return_column: str,
    ) -> LookupValueOutput:
        request = LookupValueInput(
            table_id=table_id,
            match_column=match_column,
            value=value,
            return_column=return_column,
        )

        def operation() -> LookupValueOutput:
            profile = self.layer.table_store.profile(request.table_id)
            self._require_columns(profile.column_names, [request.match_column, request.return_column])
            target = normalize_canonical_value(request.value)
            matches = [
                row
                for row in self.layer.table_store.rows(request.table_id)
                if normalize_canonical_value(row.get(request.match_column)) == target
            ]
            values = {_mask_value(row.get(request.return_column)) for row in matches}
            return LookupValueOutput(
                table_id=request.table_id,
                value=(
                    _mask_value(matches[0].get(request.return_column))
                    if matches and len(values) == 1
                    else None
                ),
                matched_rows=len(matches),
                ambiguous=len(values) > 1,
                source_ids=[request.table_id] if matches else [],
            )

        return self._invoke("lookup_value", request.model_dump(mode="json"), operation)

    def query_table(
        self, table_id: str, filters: list[FilterClause | dict[str, Any]] | None = None,
        select: list[str] | None = None, aggregation: AggregationSpec | dict[str, Any] | None = None,
        group_by: list[str] | None = None, order_by: list[OrderByClause | dict[str, Any]] | None = None,
        limit: int | None = None,
    ) -> QueryTableOutput:
        request = QueryTableInput(table_id=table_id, filters=filters, select=select, aggregation=aggregation,
                                  group_by=group_by, order_by=order_by, limit=limit)

        def operation() -> QueryTableOutput:
            profile = self.layer.table_store.profile(request.table_id)
            columns = profile.column_names
            requested_columns = [clause.field for clause in request.filters or []] + (request.group_by or [])
            if request.aggregation:
                requested_columns += [field for field in (request.aggregation.field,
                    request.aggregation.numerator_field, request.aggregation.denominator_field) if field]
            if not request.aggregation:
                requested_columns += request.select or []
            self._require_columns(columns, requested_columns)
            rows = list(self.layer.table_store.rows(request.table_id))
            for clause in request.filters or []:
                rows = [row for row in rows if self._matches(row.get(clause.field), clause)]
            source_rows_matched = len(rows)
            if request.group_by and request.aggregation:
                grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
                for row in rows:
                    key = tuple(row.get(field) for field in request.group_by)
                    grouped.setdefault(key, []).append(row)
                output = []
                for key, group_rows in grouped.items():
                    result_row = dict(zip(request.group_by, key))
                    result_row.update(self._aggregate(group_rows, request.aggregation))
                    output.append(result_row)
            elif request.aggregation:
                output = [self._aggregate(rows, request.aggregation)]
            else:
                projection = request.select or columns
                output = [{field: row.get(field) for field in projection} for row in rows]
            available = set(output[0]) if output else set(request.group_by or [])
            if request.aggregation:
                available.add(request.aggregation.output_field())
            for ordering in request.order_by or []:
                if ordering.field not in available:
                    raise AgentToolError("UNKNOWN_RESULT_FIELD", f"cannot order by {ordering.field}")
                self._sort(output, ordering)
            if request.select and request.aggregation:
                unknown = sorted(set(request.select) - available)
                if unknown:
                    raise AgentToolError("UNKNOWN_RESULT_FIELD", f"unknown selected result fields: {unknown}")
                output = [{field: row.get(field) for field in request.select} for row in output]
            before_limit = len(output)
            effective_limit = request.limit if request.limit is not None else MAX_TABLE_ROWS
            safe_output = [{key: _mask_value(value) for key, value in row.items()}
                           for row in output[:effective_limit]]
            return QueryTableOutput(table_id=request.table_id, rows=safe_output,
                rows_returned=len(safe_output), result_rows_before_limit=before_limit,
                source_rows_matched=source_rows_matched, truncated=before_limit > effective_limit,
                source_ids=[request.table_id])

        return self._invoke("query_table", request.model_dump(mode="json"), operation)

    def metrics(self) -> TaskToolMetrics:
        return TaskToolMetrics(task_id=self.task_id, category=self.category, budget=self.budget,
            tool_calls=len(self.events), budget_exceeded=self.budget_exceeded, events=self.events)

    @staticmethod
    def _require_columns(columns: list[str], requested: list[str]) -> None:
        unknown = sorted(set(requested) - set(columns))
        if unknown:
            raise AgentToolError("UNKNOWN_COLUMN", f"unknown columns: {unknown}")

    @staticmethod
    def _matches(actual: Any, clause: FilterClause) -> bool:
        expected = clause.value
        if clause.op == FilterOperator.IN:
            return any(normalize_canonical_value(actual) == normalize_canonical_value(item) for item in expected)
        if clause.op in (FilterOperator.EQ, FilterOperator.NE):
            equal = normalize_canonical_value(actual) == normalize_canonical_value(expected)
            return equal if clause.op == FilterOperator.EQ else not equal
        if clause.op == FilterOperator.CONTAINS:
            return normalize_text(expected) in normalize_text(actual)
        if clause.op == FilterOperator.PREFIX:
            return normalize_text(actual).startswith(normalize_text(expected))
        try:
            left, right = _as_number(actual), _as_number(expected)
        except AgentToolError:
            left, right = normalize_text(actual), normalize_text(expected)
        return {FilterOperator.GT: left > right, FilterOperator.GTE: left >= right,
                FilterOperator.LT: left < right, FilterOperator.LTE: left <= right}[clause.op]

    @staticmethod
    def _aggregate(rows: list[dict[str, Any]], spec: AggregationSpec) -> dict[str, Any]:
        name = spec.output_field()
        if spec.op == AggregationOperator.COUNT:
            value = len(rows) if spec.field is None else sum(
                row.get(spec.field) is not None and str(row.get(spec.field)).strip() != "" for row in rows)
            return {name: value}
        if spec.op == AggregationOperator.RATE:
            numerator = sum(_as_number(row.get(spec.numerator_field)) for row in rows)
            denominator = sum(_as_number(row.get(spec.denominator_field)) for row in rows)
            return {name: None if denominator == 0 else numerator / denominator}
        values = [row.get(spec.field) for row in rows if row.get(spec.field) is not None]
        if spec.op in (AggregationOperator.MIN, AggregationOperator.MAX):
            operation = min if spec.op == AggregationOperator.MIN else max
            return {name: operation(values) if values else None}
        numbers = [_as_number(value) for value in values]
        if spec.op == AggregationOperator.SUM:
            return {name: _compact_number(sum(numbers))}
        if spec.op == AggregationOperator.AVG:
            return {name: None if not numbers else sum(numbers) / len(numbers)}
        raise AgentToolError("UNSUPPORTED_AGGREGATION", spec.op.value)

    @staticmethod
    def _sort(rows: list[dict[str, Any]], ordering: OrderByClause) -> None:
        populated = [row for row in rows if row.get(ordering.field) is not None]
        missing = [row for row in rows if row.get(ordering.field) is None]
        populated.sort(key=lambda row: row[ordering.field], reverse=ordering.direction == SortDirection.DESC)
        rows[:] = populated + missing


def tool_call_distribution(metrics: list[TaskToolMetrics]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for category in TaskCategory:
        values = sorted(item.tool_calls for item in metrics if item.category == category)
        if values:
            rank = max(1, math.ceil(0.95 * len(values)))
            result[category.value] = {"observations": values, "mean": statistics.fmean(values),
                "median": statistics.median(values), "p95_nearest_rank": values[rank - 1],
                "max": max(values), "budget": TOOL_BUDGETS[category]}
    return result
