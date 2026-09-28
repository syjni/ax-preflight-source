from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskCategory(str, Enum):
    KNOWLEDGE = "knowledge"
    OPERATIONS = "operations"
    CROSS_FILE = "cross_file"


TOOL_BUDGETS: dict[TaskCategory, int] = {
    TaskCategory.KNOWLEDGE: 6,
    TaskCategory.OPERATIONS: 8,
    TaskCategory.CROSS_FILE: 12,
}


class FilterOperator(str, Enum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CONTAINS = "contains"
    PREFIX = "prefix"
    IN = "in"


class AggregationOperator(str, Enum):
    SUM = "sum"
    AVG = "avg"
    COUNT = "count"
    MIN = "min"
    MAX = "max"
    RATE = "rate"


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class SearchDocumentsInput(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


class SearchTableReference(StrictModel):
    table_id: str = Field(
        description=(
            "Exact identifier accepted by both lookup_value and query_table. "
            "Never guess a table_id. Obtain it from search_documents metadata."
        ))
    sheet_name: str = Field(description="Scanner sheet or logical table name.")
    column_names: list[str] = Field(
        description="Available column names for selecting lookup/query arguments.")


class SearchHit(StrictModel):
    document_id: str
    title: str
    document_type: Literal["document", "tabular"] = Field(
        description="tabular when this source has one or more queryable tables.")
    tables: list[SearchTableReference] = Field(
        description="Queryable table references; empty for non-tabular documents.")
    metadata: dict[str, Any]
    snippet: str = Field(max_length=500)
    score: float = Field(ge=0.0)


class SearchDocumentsOutput(StrictModel):
    results: list[SearchHit]
    results_returned: int = Field(ge=0, le=10)


class ReadDocumentInput(StrictModel):
    document_id: str
    section: int | None = Field(default=None, ge=0)


class ReadDocumentOutput(StrictModel):
    document_id: str
    title: str
    section: int = Field(ge=0)
    content: str = Field(max_length=2500)
    characters_returned: int = Field(ge=0, le=2500)
    total_characters: int = Field(ge=0)
    next_section: int | None = Field(default=None, ge=0)
    truncated: bool


class LookupValueInput(StrictModel):
    table_id: str = Field(
        description=(
            "Exact tables[].table_id returned by search_documents. "
            "Never guess a table_id. Obtain it from search_documents metadata."
        ))
    match_column: str
    value: str | int | float | bool
    return_column: str


class LookupValueOutput(StrictModel):
    table_id: str
    value: Any = None
    matched_rows: int = Field(ge=0)
    ambiguous: bool = False
    source_ids: list[str]


class FilterClause(StrictModel):
    field: str
    op: FilterOperator = FilterOperator.EQ
    value: Any

    @model_validator(mode="after")
    def validate_in_value(self) -> "FilterClause":
        if self.op == FilterOperator.IN and not isinstance(self.value, list):
            raise ValueError("the 'in' operator requires a list value")
        if self.op != FilterOperator.IN and isinstance(self.value, (dict, list)):
            raise ValueError("filter values must be scalar except for the 'in' operator")
        return self


class AggregationSpec(StrictModel):
    op: AggregationOperator
    field: str | None = None
    numerator_field: str | None = None
    denominator_field: str | None = None
    alias: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")

    @model_validator(mode="after")
    def validate_fields(self) -> "AggregationSpec":
        if self.op == AggregationOperator.RATE:
            if not self.numerator_field or not self.denominator_field:
                raise ValueError("rate requires numerator_field and denominator_field")
            if self.field is not None:
                raise ValueError("rate does not accept field")
        elif self.op == AggregationOperator.COUNT:
            if self.numerator_field or self.denominator_field:
                raise ValueError("count does not accept numerator/denominator fields")
        else:
            if not self.field:
                raise ValueError(f"{self.op.value} requires field")
            if self.numerator_field or self.denominator_field:
                raise ValueError(f"{self.op.value} does not accept numerator/denominator fields")
        return self

    def output_field(self) -> str:
        if self.alias:
            return self.alias
        if self.op == AggregationOperator.RATE:
            return "rate"
        if self.op == AggregationOperator.COUNT and self.field is None:
            return "count"
        return f"{self.op.value}_{self.field}"


class OrderByClause(StrictModel):
    field: str
    direction: SortDirection = SortDirection.ASC


class QueryTableInput(StrictModel):
    table_id: str = Field(
        description=(
            "Exact tables[].table_id returned by search_documents. "
            "Never guess a table_id. Obtain it from search_documents metadata."
        ))
    filters: list[FilterClause] | None = None
    select: list[str] | None = Field(default=None, max_length=20)
    aggregation: AggregationSpec | None = None
    group_by: list[str] | None = Field(default=None, max_length=10)
    order_by: list[OrderByClause] | None = Field(default=None, max_length=10)
    limit: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode="after")
    def validate_grouping(self) -> "QueryTableInput":
        if self.group_by and not self.aggregation:
            raise ValueError("group_by requires aggregation in the 9/20 DSL")
        return self


class QueryTableOutput(StrictModel):
    table_id: str
    rows: list[dict[str, Any]] = Field(max_length=10)
    rows_returned: int = Field(ge=0, le=10)
    result_rows_before_limit: int = Field(ge=0)
    source_rows_matched: int = Field(ge=0)
    truncated: bool
    source_ids: list[str]


class AgentOutput(StrictModel):
    final_answer: str | int | float | bool | None = None
    unit: str | None = None
    explanation: str = Field(max_length=2000)
    source_ids: list[str]
    abstain: bool

    @model_validator(mode="after")
    def validate_abstention(self) -> "AgentOutput":
        if self.abstain and self.final_answer is not None:
            raise ValueError("abstaining output must have final_answer=null")
        if not self.abstain and self.final_answer is None:
            raise ValueError("non-abstaining output requires final_answer")
        return self


class ToolCallEvent(StrictModel):
    sequence: int = Field(ge=1)
    tool: str
    arguments: dict[str, Any]
    latency_ms: float = Field(ge=0.0)
    success: bool
    error_code: str | None = None
    source_ids: list[str]
    result_summary: dict[str, Any]


class TaskToolMetrics(StrictModel):
    task_id: str
    category: TaskCategory
    budget: int = Field(ge=1)
    tool_calls: int = Field(ge=0)
    budget_exceeded: bool
    events: list[ToolCallEvent]
