from __future__ import annotations

import hashlib
import json

import pytest

from ax_product.evidence import ToolResponseRecord
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.retrieval_trace import build_retrieval_trace
from ax_product.tool_attempts import ToolAttemptRecord, summarize_tool_request


def record(run_id: str, sequence: int, tool_name: str, output: dict) -> ToolResponseRecord:
    encoded = json.dumps(
        output, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return ToolResponseRecord(
        run_id=run_id,
        sequence=sequence,
        tool_name=tool_name,
        output=output,
        output_sha256=hashlib.sha256(encoded).hexdigest(),
    )


def delivery(run_id: str = "trace-run") -> DeliveryEnvelope:
    return DeliveryEnvelope(
        delivery_status="DELIVERED",
        run_id=run_id,
        model="test-model",
        dataset="mini",
        source_link_status="LINKED",
        payload=SubmitAnswerInput(
            status="ANSWERED",
            answer="30일",
            explanation="정책에서 확인",
            source_ids=["DOC_POLICY"],
        ),
    )


def test_trace_preserves_search_rank_and_marks_the_cited_path() -> None:
    records = [
        record("trace-run", 1, "search_documents", {
            "results_returned": 2,
            "results": [
                {"document_id": "DOC_POLICY", "title": "반품 정책", "tables": []},
                {"document_id": "DOC_FAQ", "title": "FAQ", "tables": []},
            ],
        }),
        record("trace-run", 2, "read_document", {
            "document_id": "DOC_POLICY", "title": "반품 정책",
            "content": "반품 기간은 30일", "truncated": False,
        }),
    ]

    trace = build_retrieval_trace(delivery(), records)

    assert [step.sequence for step in trace.steps] == [1, 2]
    assert [item.title for item in trace.steps[0].candidates] == ["반품 정책", "FAQ"]
    assert [item.cited for item in trace.steps[0].candidates] == [True, False]
    assert trace.steps[1].cited_source_ids == ["DOC_POLICY"]
    assert trace.steps[1].truncated is False


def test_trace_exposes_counts_without_copying_raw_values() -> None:
    output = {
        "table_id": "TABLE_ORDERS",
        "source_ids": ["DOC_POLICY"],
        "rows": [{"secret_value": 30}],
        "rows_returned": 1,
        "truncated": False,
    }
    trace = build_retrieval_trace(
        delivery(), [record("trace-run", 1, "query_table", output)]
    )
    serialized = trace.model_dump_json()

    assert trace.steps[0].result_count == 1
    assert "secret_value" not in serialized
    assert trace.steps[0].cited_source_ids == ["DOC_POLICY"]


def test_trace_rejects_cross_run_records() -> None:
    mismatched = record("other-run", 1, "read_document", {
        "document_id": "DOC_POLICY", "title": "반품 정책"
    })
    with pytest.raises(ValueError, match="belong to the delivery run"):
        build_retrieval_trace(delivery(), [mismatched])


def test_trace_preserves_failed_attempt_before_success_without_raw_query() -> None:
    records = [record("trace-run", 1, "search_documents", {
        "results_returned": 1,
        "results": [
            {"document_id": "DOC_POLICY", "title": "반품 정책", "tables": []},
        ],
    })]
    attempts = [
        ToolAttemptRecord(
            run_id="trace-run",
            sequence=1,
            tool_name="search_documents",
            status="ERROR",
            request_summary=summarize_tool_request(
                "search_documents", {"query": "민감한 첫 검색", "top_k": 0}
            ),
            error_code="VALIDATION_ERROR",
        ),
        ToolAttemptRecord(
            run_id="trace-run",
            sequence=2,
            tool_name="search_documents",
            status="SUCCESS",
            request_summary=summarize_tool_request(
                "search_documents", {"query": "최종 검색어 비공개", "top_k": 3}
            ),
        ),
    ]

    trace = build_retrieval_trace(delivery(), records, attempts)
    serialized = trace.model_dump_json()

    assert trace.schema_version == "ax-retrieval-trace-v2"
    assert [step.status for step in trace.steps] == ["ERROR", "SUCCESS"]
    assert trace.steps[0].error_code == "VALIDATION_ERROR"
    assert trace.steps[0].result_count == 0
    assert trace.steps[1].sequence == 2
    assert trace.steps[1].candidates[0].cited is True
    assert "민감한 첫 검색" not in serialized
    assert "최종 검색어 비공개" not in serialized
