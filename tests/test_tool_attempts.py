from __future__ import annotations

import io
from pathlib import Path

import pytest
from pydantic import ValidationError

from ax_mcp.telemetry import InvocationLogger
from ax_product.adapter import ProductMcpAdapter
from ax_product.evidence import ToolResponseStore
from ax_product.results import ResultStore
from ax_product.tool_attempts import ToolAttemptStore, summarize_tool_request


ROOT = Path(__file__).resolve().parents[1]


def test_request_summary_excludes_query_and_filter_values() -> None:
    summary = summarize_tool_request("query_table", {
        "table_id": "TABLE_ORDERS",
        "query": "VIP 고객 홍길동",
        "filters": [
            {"field": "customer_name", "op": "eq", "value": "홍길동"},
            {"field": "status", "op": "eq", "value": "VIP"},
        ],
        "limit": 7,
    })
    serialized = summary.model_dump_json()

    assert summary.parameter_names == ["filters", "limit", "table_id"]
    assert summary.query_character_count is None
    assert summary.result_limit == 7
    assert summary.source_ids == ["TABLE_ORDERS"]
    assert summary.filter_fields == ["customer_name", "status"]
    assert "홍길동" not in serialized
    assert '"VIP"' not in serialized


def test_request_summary_drops_unknown_parameter_names() -> None:
    summary = summarize_tool_request(
        "search_documents",
        {"query": "정상 검색", "secret-in-key": "do not retain"},
    )

    assert summary.parameter_names == ["query"]
    assert "secret-in-key" not in summary.model_dump_json()


def test_adapter_records_failed_and_successful_attempts_in_order(
    tmp_path: Path,
) -> None:
    ResultStore(tmp_path).reserve(
        run_id="attempt-run",
        task_id=None,
        model="test-model",
        dataset="mini",
    )
    attempts = ToolAttemptStore(tmp_path)
    responses = ToolResponseStore(tmp_path)
    adapter = ProductMcpAdapter(
        ROOT / "scan_report.json",
        ROOT / "sample_data" / "mini_company",
        run_id="attempt-run",
        model="test-model",
        invocation_logger=InvocationLogger(stream=io.StringIO()),
        response_store=responses,
        attempt_store=attempts,
    )

    with pytest.raises(ValidationError):
        adapter.call_tool("search_documents", {"top_k": 3})
    adapter.call_tool(
        "search_documents",
        {"query": "거래처 주문", "top_k": 3},
    )

    records = attempts.read("attempt-run")
    assert [(item.sequence, item.status) for item in records] == [
        (1, "ERROR"),
        (2, "SUCCESS"),
    ]
    assert records[0].error_code == "VALIDATION_ERROR"
    assert records[0].request_summary.parameter_names == ["top_k"]
    assert records[1].request_summary.query_character_count == len("거래처 주문")
    assert "거래처 주문" not in records[1].model_dump_json()
    assert len(responses.read("attempt-run")) == 1
