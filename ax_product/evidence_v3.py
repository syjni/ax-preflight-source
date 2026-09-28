"""Current product Evidence Checker with explicit retired-value protection.

The Phase 6 v4 snapshot hashes :mod:`ax_product.evidence_v2`, so that module
must remain byte-stable.  This additive wrapper preserves every v2 rule and
only downgrades a direct quantity match when the cited narrative presents that
quantity exclusively as an explicitly retired value.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .evidence import (
    EvidenceCheckResult,
    ToolResponseRecord,
    ToolResponseStore,
    response_source_ids,
)
from .evidence_v2 import check_evidence_v2
from .models import DeliveryEnvelope


_EXCLUDED_FIELDS = {
    "document_id", "file_id", "table_id", "source_id", "source_ids",
    "matched_rows", "rows_returned", "result_rows_before_limit",
    "source_rows_matched", "score", "section", "total_sections", "truncated",
}
_QUANTITY_UNIT_ALIASES = (
    {"day", "days", "일"},
    {"hour", "hours", "hr", "hrs", "시간"},
    {"percent", "percentage", "%", "퍼센트"},
    {"krw", "원", "₩"},
)
_RETIRED_MARKERS = (
    "폐기", "폐지", "무효", "효력 없음", "사용 중단", "적용 중단", "대체",
    "obsolete", "deprecated", "superseded", "retired", "withdrawn",
    "no longer valid", "replaced",
)
_RETIRED_EXCEPTIONS = (
    "폐기되지 않", "폐지되지 않", "무효가 아니", "중단되지 않",
    "not obsolete", "not deprecated", "not superseded", "not retired",
    "not withdrawn", "not replaced",
)
_CONTEXT_BOUNDARY = re.compile(
    r"[,;]|\b(?:but|whereas|instead)\b|하지만|반면|대신|"
    r"(?=(?:현재|현행|지금|과거|이전|종전)(?:은|는|의|에|부터|까지|\s))|"
    r"(?=\b(?:current|now|previous|former|historical|old)\b)",
    re.I,
)


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


def _numbers(value: Any) -> set[Decimal]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = _decimal(value)
        return set() if parsed is None else {parsed}
    if not isinstance(value, str):
        return set()
    return {
        parsed
        for token in re.findall(r"(?<![\w])[-+]?\d[\d,]*(?:\.\d+)?", value)
        if (parsed := _decimal(token)) is not None
    }


def _unit_aliases(unit: str) -> set[str]:
    normalized = _normalize(unit).replace("_threshold", "").strip()
    for aliases in _QUANTITY_UNIT_ALIASES:
        normalized_aliases = {_normalize(alias) for alias in aliases}
        if normalized in normalized_aliases or normalized.rstrip("s") in {
            alias.rstrip("s") for alias in normalized_aliases
        }:
            return normalized_aliases
    return {normalized}


def _has_unit(value: str, aliases: set[str]) -> bool:
    normalized = _normalize(value)
    for alias in aliases:
        if not alias:
            continue
        escaped = re.escape(alias)
        if any("a" <= char <= "z" for char in alias):
            pattern = rf"(?<![a-z]){escaped}(?![a-z])"
        elif re.search(r"[\uac00-\ud7a3]", alias):
            particles = r"(?:입니다|이다|으로|에서|부터|까지|마다|은|는|이|가|을|를|의|에|로|와|과|도)"
            pattern = rf"(?<![\uac00-\ud7a3]){escaped}(?=$|[^\uac00-\ud7a3]|{particles}(?=$|[^\uac00-\ud7a3]))"
        else:
            pattern = escaped
        if re.search(pattern, normalized):
            return True
    return False


def _is_retired_context(value: str) -> bool:
    normalized = _normalize(value)
    if any(exception in normalized for exception in _RETIRED_EXCEPTIONS):
        return False
    return any(marker in normalized for marker in _RETIRED_MARKERS)


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


def _structured_values(record: ToolResponseRecord) -> list[Any]:
    if record.tool_name == "lookup_value":
        value = record.output.get("value")
        return [value] if isinstance(value, (str, int, float, bool)) else []
    if record.tool_name != "query_table":
        return []
    rows = record.output.get("rows")
    if not isinstance(rows, list):
        return []
    return [
        value
        for row in rows if isinstance(row, dict)
        for field, value in row.items()
        if str(field) not in _EXCLUDED_FIELDS
        and isinstance(value, (str, int, float, bool))
    ]


def _narrative_texts(
    delivery: DeliveryEnvelope, records: list[ToolResponseRecord]
) -> list[str]:
    payload = delivery.payload
    if payload is None:
        return []
    cited = set(payload.source_ids)
    texts: list[str] = []
    for record in _cited_records(delivery, records):
        if record.tool_name == "read_document":
            content = record.output.get("content")
            if record.output.get("document_id") in cited and isinstance(content, str):
                texts.append(content)
        elif record.tool_name == "search_documents":
            for hit in record.output.get("results", []):
                if not isinstance(hit, dict):
                    continue
                hit_ids = {hit.get("document_id")}
                hit_ids.update(
                    table.get("table_id")
                    for table in hit.get("tables", [])
                    if isinstance(table, dict)
                )
                snippet = hit.get("snippet")
                if hit_ids.intersection(cited) and isinstance(snippet, str):
                    texts.append(snippet)
    return texts


def _supported_only_as_retired_quantity(
    delivery: DeliveryEnvelope, records: list[ToolResponseRecord]
) -> bool:
    payload = delivery.payload
    if payload is None or payload.status != "ANSWERED" or payload.unit is None:
        return False
    target = _answer_number(payload.answer)
    if target is None:
        return False

    cited_records = _cited_records(delivery, records)
    if any(
        target in _numbers(value)
        for record in cited_records
        for value in _structured_values(record)
    ):
        return False

    aliases = _unit_aliases(payload.unit)
    retired_match = False
    for text in _narrative_texts(delivery, records):
        for sentence in re.split(r"[\n.!?。]+", _normalize(text)):
            for clause in _CONTEXT_BOUNDARY.split(sentence):
                if target not in _numbers(clause) or not _has_unit(clause, aliases):
                    continue
                if _is_retired_context(clause):
                    retired_match = True
                else:
                    return False
    return retired_match


def check_evidence_v3(
    delivery: DeliveryEnvelope, records: list[ToolResponseRecord]
) -> EvidenceCheckResult:
    """Apply frozen v2 rules, then reject retired-only direct quantities."""
    baseline = check_evidence_v2(delivery, records)
    if (
        baseline.verdict != "DIRECT_MATCH"
        or not _supported_only_as_retired_quantity(delivery, records)
    ):
        return baseline
    return baseline.model_copy(update={
        "verdict": "PARTIAL_SUPPORT",
        "evidence": [
            item.model_copy(update={"match": "PARTIAL_VALUE"})
            for item in baseline.evidence
        ],
        "limitations": [
            *baseline.limitations,
            "Evidence Checker v3 does not treat an explicitly retired quantity as current direct support.",
        ],
    })


def check_run_v3(root: str | Path, run_id: str) -> EvidenceCheckResult:
    """Read one stored run and apply the current product checker read-only."""
    from .results import ResultStore

    result_root = Path(root).resolve()
    result_store = ResultStore(result_root)
    delivery = result_store.read(run_id)
    records = ToolResponseStore(result_root).read(run_id)
    result = check_evidence_v3(delivery, records)
    return result.model_copy(update={
        "delivery_sha256": hashlib.sha256(
            result_store.path(run_id).read_bytes()
        ).hexdigest()
    })
