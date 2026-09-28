from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ax_agent.errors import AgentToolError
from ax_agent.models import (
    LookupValueInput,
    QueryTableInput,
    ReadDocumentInput,
    SearchDocumentsInput,
    TaskCategory,
)
from ax_agent.tools import AgentToolLayer, tool_schema_catalog

from .telemetry import InvocationLogger, safe_parameters


AX_MCP_TOOL_NAMES = (
    "search_documents",
    "read_document",
    "lookup_value",
    "query_table",
)

_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "search_documents": SearchDocumentsInput,
    "read_document": ReadDocumentInput,
    "lookup_value": LookupValueInput,
    "query_table": QueryTableInput,
}

_DESCRIPTIONS = {
    "search_documents": (
        "Search masked company documents with the existing char 2-3 gram BM25 index. "
        "Tabular hits include document_type='tabular' and tables[] entries containing the exact "
        "table_id and column_names accepted by lookup_value and query_table. "
        "Never guess a table_id. Obtain it from search_documents metadata."
    ),
    "read_document": "Read one bounded section of a company document by document ID.",
    "lookup_value": (
        "Look up one table value after existing canonical value normalization. "
        "Use the exact tables[].table_id returned by search_documents. "
        "Never guess a table_id. Obtain it from search_documents metadata."
    ),
    "query_table": (
        "Query a company table through the existing restricted filter/aggregation DSL. "
        "Use the exact tables[].table_id returned by search_documents. "
        "Never guess a table_id. Obtain it from search_documents metadata."
    ),
}


class AxMcpAdapter:
    """Process-scoped transport adapter backed by one persistent tool session."""

    def __init__(self, scan_report: str | Path, source_root: str | Path,
                 invocation_logger: InvocationLogger | None = None):
        self.layer = AgentToolLayer(scan_report, source_root)
        self.session = self.layer.start_task("mcp", TaskCategory.CROSS_FILE)
        self.invocation_logger = invocation_logger or InvocationLogger()

    def list_tools(self) -> list[dict[str, Any]]:
        schemas = tool_schema_catalog()
        return [
            {
                "name": name,
                "description": _DESCRIPTIONS[name],
                "inputSchema": schemas[name]["input_schema"],
                "outputSchema": schemas[name]["output_schema"],
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            }
            for name in AX_MCP_TOOL_NAMES
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        started_counter = time.perf_counter_ns()
        outcome = "error"
        error_code: str | None = None
        try:
            if name not in _INPUT_MODELS:
                raise AgentToolError("TOOL_NOT_FOUND", f"unknown MCP tool: {name}")
            request = _INPUT_MODELS[name].model_validate(arguments or {})
            result = getattr(self.session, name)(**request.model_dump(mode="json"))
            outcome = "success"
            return result.model_dump(mode="json")
        except ValidationError:
            error_code = "VALIDATION_ERROR"
            raise
        except AgentToolError as exc:
            error_code = exc.code
            raise
        except Exception as exc:
            error_code = type(exc).__name__
            raise
        finally:
            ended_at = datetime.now(timezone.utc)
            event: dict[str, Any] = {
                "tool_name": name,
                "start_time": started_at.isoformat().replace("+00:00", "Z"),
                "end_time": ended_at.isoformat().replace("+00:00", "Z"),
                "elapsed_ms": round((time.perf_counter_ns() - started_counter) / 1_000_000, 3),
                "outcome": outcome,
                "safe_parameters": safe_parameters(name, arguments),
            }
            if error_code is not None:
                event["error_code"] = error_code
            self.invocation_logger.record(event)
