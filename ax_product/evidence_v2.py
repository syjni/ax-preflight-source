"""Additive Evidence Checker v2 rules for new runs and post-hoc snapshots.

The frozen v1 checker remains byte-stable in :mod:`ax_product.evidence`.
This module first applies that checker, then promotes only deterministic matches
that v1 deliberately did not cover.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .evidence import (
    EvidenceCheckResult,
    ToolResponseRecord,
    ToolResponseStore,
    check_evidence,
    response_source_ids,
)
from .models import DeliveryEnvelope


_EXCLUDED_FIELDS = {
    "document_id", "file_id", "table_id", "source_id", "source_ids",
    "matched_rows", "rows_returned", "result_rows_before_limit",
    "source_rows_matched", "score", "section", "total_sections", "truncated",
}
_AGGREGATE_FIELD = re.compile(r"^(?:count|(?:sum|count|min|max)_.+)$", re.I)


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        parsed = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _answer_number(answer: Any) -> Decimal | None:
    parsed = _decimal(answer)
    if parsed is not None:
        return parsed
    if not isinstance(answer, str):
        return None
    match = re.fullmatch(r"\s*([+-]?\d[\d,]*(?:\.\d+)?)\s*.*", answer)
    return _decimal(match.group(1)) if match else None


def _numbers_in_text(value: Any) -> set[Decimal]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = _decimal(value)
        return set() if parsed is None else {parsed}
    if not isinstance(value, str):
        return set()
    parsed: set[Decimal] = set()
    for token in re.findall(r"(?<![\w])[-+]?\d[\d,]*(?:\.\d+)?", value):
        number = _decimal(token)
        if number is not None:
            parsed.add(number)
    return parsed


def _canonical_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})(?:[T\s].*)?\s*", value
    )
    if match is None:
        return None
    try:
        parsed = date(*(int(item) for item in match.groups()))
    except ValueError:
        return None
    return parsed.isoformat()


def _complete_rows(output: dict[str, Any]) -> list[dict[str, Any]] | None:
    raw_rows = output.get("rows")
    if not isinstance(raw_rows, list) or not all(isinstance(row, dict) for row in raw_rows):
        return None
    rows = list(raw_rows)
    if not (
        output.get("truncated") is False
        and output.get("rows_returned") == len(rows)
        and output.get("result_rows_before_limit") == len(rows)
    ):
        return None
    return rows


def _complete_table_rows(records: list[ToolResponseRecord]) -> list[dict[str, Any]] | None:
    query_records = [record for record in records if record.tool_name == "query_table"]
    by_table: dict[str, list[ToolResponseRecord]] = {}
    for record in query_records:
        table_id = record.output.get("table_id")
        if isinstance(table_id, str):
            by_table.setdefault(table_id, []).append(record)
    for grouped in by_table.values():
        expected_counts = [
            value for record in grouped
            if isinstance((value := record.output.get("result_rows_before_limit")), int)
        ]
        expected = max(expected_counts, default=0)
        unique: dict[str, dict[str, Any]] = {}
        for record in grouped:
            rows = record.output.get("rows")
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                continue
            for row in rows:
                key = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                unique[key] = row
        if expected > 0 and len(unique) == expected:
            return list(unique.values())
    return None


def _cells(record: ToolResponseRecord) -> list[tuple[str, Any]]:
    if record.tool_name == "lookup_value":
        value = record.output.get("value")
        return [("value", value)] if isinstance(value, (str, int, float, bool)) else []
    if record.tool_name != "query_table":
        return []
    rows = record.output.get("rows")
    if not isinstance(rows, list):
        return []
    return [
        (str(field), value)
        for row in rows if isinstance(row, dict)
        for field, value in row.items()
        if str(field) not in _EXCLUDED_FIELDS
        and isinstance(value, (str, int, float, bool))
    ]


def _cited_records(
    delivery: DeliveryEnvelope, records: list[ToolResponseRecord]
) -> list[ToolResponseRecord]:
    payload = delivery.payload
    if payload is None:
        return []
    cited = set(payload.source_ids)
    return [
        record for record in records
        if response_source_ids(record.tool_name, record.output).intersection(cited)
    ]


def evidence_v2_reason(
    delivery: DeliveryEnvelope, records: list[ToolResponseRecord]
) -> str | None:
    """Return the deterministic v2 promotion rule, if one applies."""
    payload = delivery.payload
    if (
        delivery.delivery_status != "DELIVERED"
        or payload is None
        or payload.status != "ANSWERED"
        or payload.answer is None
        or not payload.source_ids
    ):
        return None
    cited_records = _cited_records(delivery, records)
    observed = set().union(*(
        response_source_ids(record.tool_name, record.output)
        for record in cited_records
    )) if cited_records else set()
    if set(payload.source_ids) - observed:
        return None

    answer_number = _answer_number(payload.answer)
    answer_text = _normalize(str(payload.answer))
    for record in cited_records:
        for field, value in _cells(record):
            if not _AGGREGATE_FIELD.fullmatch(field):
                continue
            if answer_number is not None and _decimal(value) == answer_number:
                return "QUERY_AGGREGATE_VALUE"
            if isinstance(value, str) and _normalize(value) == answer_text:
                return "QUERY_AGGREGATE_VALUE"

    answer_date = _canonical_date(payload.answer)
    if answer_date is not None and any(
        _canonical_date(value) == answer_date
        for record in cited_records for _, value in _cells(record)
    ):
        return "DATE_NORMALIZATION"

    answer_numbers = _numbers_in_text(payload.answer)
    if payload.unit is not None and len(answer_numbers) == 1:
        expected_number = next(iter(answer_numbers))
        if any(
            record.tool_name == "lookup_value"
            and _decimal(record.output.get("value")) == expected_number
            for record in cited_records
        ):
            return "STRUCTURED_LOOKUP_NUMERIC_VALUE"

    structured_text_matches = {
        _normalize(value)
        for record in cited_records
        for _, value in _cells(record)
        if isinstance(value, str)
        and len(_normalize(value)) >= 2
        and _normalize(value) in answer_text
    }
    structured_records_with_matches = {
        record.sequence
        for record in cited_records
        if any(
            isinstance(value, str)
            and len(_normalize(value)) >= 2
            and _normalize(value) in answer_text
            for _, value in _cells(record)
        )
    }
    if (
        len(structured_text_matches) >= 2
        and len(structured_records_with_matches) >= 2
    ):
        return "STRUCTURED_MULTI_SOURCE_COMPOSITE"

    none_answer = (
        answer_text.startswith(("없음", "해당 품목 없음", "none", "no "))
        or "품목은 없습니다" in answer_text
        or "품목 없음" in answer_text
    )
    if none_answer:
        complete_rows = _complete_table_rows(cited_records)
        if complete_rows and all(
            (available := _decimal(row.get("available_qty"))) is not None
            and (threshold := _decimal(row.get("reorder_point"))) is not None
            and available >= threshold
            for row in complete_rows
        ):
            return "COMPLETE_TABLE_PREDICATE"

    for record in cited_records:
        if record.tool_name != "query_table":
            continue
        rows = record.output.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            matched_text = {
                _normalize(value)
                for field, value in row.items()
                if str(field) not in _EXCLUDED_FIELDS
                and isinstance(value, str)
                and len(_normalize(value)) >= 2
                and _normalize(value) in answer_text
            }
            matched_numbers = {
                number
                for field, value in row.items()
                if str(field) not in _EXCLUDED_FIELDS
                for number in [_decimal(value)]
                if number is not None and number in answer_numbers
            }
            if len(matched_text) >= 2 and matched_numbers:
                return "STRUCTURED_COMPOSITE_VALUE"

    for record in cited_records:
        if record.tool_name != "query_table":
            continue
        rows = _complete_rows(record.output)
        if rows is None or len(rows) < 2:
            continue
        fields = {
            str(field)
            for row in rows for field, value in row.items()
            if str(field) not in _EXCLUDED_FIELDS
            and isinstance(value, str) and value.strip()
        }
        values = {
            _normalize(value)
            for row in rows for field, value in row.items()
            if str(field) not in _EXCLUDED_FIELDS
            and isinstance(value, str) and value.strip()
        }
        if len(fields) >= 2 and len(values) >= 4 and all(value in answer_text for value in values):
            return "COMPLETE_TABLE_MAPPING"

    if isinstance(payload.answer, str) and any(
        isinstance(value, str) and _normalize(value) == answer_text
        for record in cited_records for _, value in _cells(record)
    ):
        return "STRUCTURED_SCALAR_VALUE"
    return None


def check_evidence_v2(
    delivery: DeliveryEnvelope, records: list[ToolResponseRecord]
) -> EvidenceCheckResult:
    """Apply v1 first, then promote a narrow set of v2 deterministic matches."""
    baseline = check_evidence(delivery, records)
    if baseline.verdict == "DIRECT_MATCH":
        return baseline
    reason = evidence_v2_reason(delivery, records)
    if reason is None:
        return baseline
    return baseline.model_copy(update={
        "verdict": "DIRECT_MATCH",
        "evidence": [
            item.model_copy(update={"match": "DIRECT_VALUE"})
            for item in baseline.evidence
        ],
        "derivation": None,
        "limitations": [
            *baseline.limitations,
            f"Evidence Checker v2 deterministic promotion: {reason}.",
        ],
    })


def check_run_v2(root: str | Path, run_id: str) -> EvidenceCheckResult:
    """Read one stored run and apply v2 without writing into the source tree."""
    from .results import ResultStore

    result_root = Path(root).resolve()
    result_store = ResultStore(result_root)
    delivery = result_store.read(run_id)
    records = ToolResponseStore(result_root).read(run_id)
    result = check_evidence_v2(delivery, records)
    return result.model_copy(update={
        "delivery_sha256": hashlib.sha256(result_store.path(run_id).read_bytes()).hexdigest()
    })


def canonical_evidence_bytes(result: EvidenceCheckResult) -> bytes:
    """Return stable JSON bytes for v2 snapshot builders."""
    return (
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    ).encode("utf-8")
