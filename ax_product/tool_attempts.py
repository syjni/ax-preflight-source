"""Privacy-limited, write-once audit records for data-tool attempts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from ax_mcp.adapter import AX_MCP_TOOL_NAMES

from .models import StrictProductModel
from .results import DEFAULT_RESULTS_ROOT, RUN_ID_PATTERN


ATTEMPT_DIRECTORY = "tool-attempts"
_PARAMETERS = {
    "search_documents": {"query", "top_k"},
    "read_document": {"document_id", "section"},
    "lookup_value": {
        "table_id", "match_column", "value", "return_column",
    },
    "query_table": {
        "table_id", "filters", "select", "aggregation", "group_by",
        "order_by", "limit",
    },
}


class ToolRequestSummary(StrictProductModel):
    parameter_names: list[str]
    query_character_count: int | None = Field(default=None, ge=0)
    result_limit: int | None = Field(default=None, ge=1)
    source_ids: list[str]
    filter_fields: list[str]


class ToolAttemptRecord(StrictProductModel):
    schema_version: Literal["ax-tool-attempt-v1"] = "ax-tool-attempt-v1"
    run_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    tool_name: Literal[
        "search_documents", "read_document", "lookup_value", "query_table"
    ]
    status: Literal["SUCCESS", "ERROR"]
    request_summary: ToolRequestSummary
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_record(self) -> "ToolAttemptRecord":
        if not RUN_ID_PATTERN.fullmatch(self.run_id):
            raise ValueError("invalid run_id")
        if (self.status == "ERROR") != (self.error_code is not None):
            raise ValueError("ERROR requires error_code; SUCCESS forbids it")
        return self


def _filter_fields(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    fields = {
        field
        for item in value
        if isinstance(item, dict)
        and isinstance((field := item.get("field")), str)
        and field
    }
    return sorted(fields)


def summarize_tool_request(
    tool_name: str, arguments: dict[str, Any] | None
) -> ToolRequestSummary:
    """Keep diagnostic shape while excluding query text and filter values."""
    if tool_name not in _PARAMETERS:
        raise ValueError("unknown AX data tool")
    values = arguments if isinstance(arguments, dict) else {}
    allowed = _PARAMETERS[tool_name]
    source_ids = [
        value
        for key in ("document_id", "table_id")
        if key in allowed
        if isinstance((value := values.get(key)), str) and value
    ]
    filter_fields = (
        _filter_fields(values.get("filters")) if "filters" in allowed else []
    )
    query = values.get("query") if "query" in allowed else None
    limit = next(
        (
            value
            for key in ("top_k", "limit")
            if key in allowed
            if isinstance((value := values.get(key)), int)
            and not isinstance(value, bool)
            and value >= 1
        ),
        None,
    )
    return ToolRequestSummary(
        parameter_names=sorted(allowed.intersection(values)),
        query_character_count=len(query) if isinstance(query, str) else None,
        result_limit=limit,
        source_ids=source_ids,
        filter_fields=filter_fields,
    )


def _write_json_once(path: Path, value: dict[str, Any]) -> None:
    temporary = path.parent / f".{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ToolAttemptStore:
    def __init__(self, root: str | Path = DEFAULT_RESULTS_ROOT):
        self.root = Path(root).resolve()

    def directory(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("invalid run_id")
        return self.root / run_id / ATTEMPT_DIRECTORY

    def record(
        self,
        *,
        run_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None,
        status: Literal["SUCCESS", "ERROR"],
        error_code: str | None = None,
    ) -> Path:
        if tool_name not in AX_MCP_TOOL_NAMES:
            raise ValueError("only AX data-tool attempts may be recorded")
        directory = self.directory(run_id)
        if not directory.parent.is_dir():
            raise FileNotFoundError(f"run has not been reserved: {run_id}")
        directory.mkdir(exist_ok=True)
        sequence = len(list(directory.glob("*.json"))) + 1
        record = ToolAttemptRecord(
            run_id=run_id,
            sequence=sequence,
            tool_name=tool_name,
            status=status,
            request_summary=summarize_tool_request(tool_name, arguments),
            error_code=error_code,
        )
        path = directory / f"{sequence:06d}.json"
        _write_json_once(path, record.model_dump(mode="json"))
        return path

    def read(self, run_id: str) -> list[ToolAttemptRecord]:
        directory = self.directory(run_id)
        if not directory.is_dir():
            return []
        records = [
            ToolAttemptRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        ]
        if any(record.run_id != run_id for record in records):
            raise ValueError("cross-run tool attempt record")
        if [record.sequence for record in records] != list(
            range(1, len(records) + 1)
        ):
            raise ValueError("tool attempt sequence is incomplete or duplicated")
        return records
