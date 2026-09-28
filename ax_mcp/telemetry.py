from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, TextIO


def safe_parameters(tool_name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Return operational metadata without recording company values or query text."""
    values = arguments if isinstance(arguments, dict) else {}
    if tool_name == "search_documents":
        query = values.get("query")
        return {
            "query_length": len(query) if isinstance(query, str) else None,
            "top_k": values.get("top_k", 5),
        }
    if tool_name == "read_document":
        return {
            "document_id": values.get("document_id"),
            "section": values.get("section"),
        }
    if tool_name == "lookup_value":
        value = values.get("value")
        return {
            "table_id": values.get("table_id"),
            "match_column": values.get("match_column"),
            "value_type": type(value).__name__ if value is not None else None,
            "value_length": len(str(value)) if value is not None else None,
            "return_column": values.get("return_column"),
        }
    if tool_name == "query_table":
        filters = values.get("filters") if isinstance(values.get("filters"), list) else []
        select = values.get("select") if isinstance(values.get("select"), list) else []
        group_by = values.get("group_by") if isinstance(values.get("group_by"), list) else []
        order_by = values.get("order_by") if isinstance(values.get("order_by"), list) else []
        aggregation = values.get("aggregation") if isinstance(values.get("aggregation"), dict) else {}
        return {
            "table_id": values.get("table_id"),
            "filter_count": len(filters),
            "filter_fields": [item.get("field") for item in filters if isinstance(item, dict)],
            "filter_operators": [item.get("op") for item in filters if isinstance(item, dict)],
            "select_fields": select,
            "aggregation_op": aggregation.get("op"),
            "aggregation_field": aggregation.get("field"),
            "group_by": group_by,
            "order_by_fields": [item.get("field") for item in order_by if isinstance(item, dict)],
            "limit": values.get("limit"),
        }
    return {"argument_keys": sorted(values)}


class InvocationLogger:
    """Append-only JSONL diagnostics. Logging failures never change tool behavior."""

    def __init__(self, path: str | Path | None = None, stream: TextIO | None = None):
        self.path = Path(path) if path is not None else None
        self.stream = stream if stream is not None else sys.stderr
        self._lock = threading.Lock()

    def record(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            with self._lock:
                if self.path is None:
                    self.stream.write(line)
                    self.stream.flush()
                    return
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="") as handle:
                    handle.write(line)
        except Exception:
            # Diagnostics must never turn a successful read-only tool call into a failure.
            try:
                self.stream.write(json.dumps({
                    "event": "mcp_invocation_log_error",
                    "tool_name": event.get("tool_name"),
                }, separators=(",", ":")) + "\n")
                self.stream.flush()
            except Exception:
                pass
