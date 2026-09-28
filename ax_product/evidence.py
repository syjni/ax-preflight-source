"""Run-bound, conservative evidence checking for delivered product answers.

Only the immutable DeliveryEnvelope and successful structured responses recorded
for the same run are inputs.  Raw assistant text and evaluation answers are not
accepted by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import combinations
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from ax_mcp.adapter import AX_MCP_TOOL_NAMES

from .models import DeliveryEnvelope, StrictProductModel
from .results import CompositeResultStore, DEFAULT_RESULTS_ROOT, RUN_ID_PATTERN


EvidenceVerdict = Literal[
    "DIRECT_MATCH", "DERIVABLE", "PARTIAL_SUPPORT", "UNCONFIRMED"
]
DerivationOperation = Literal["SUM", "DIFFERENCE", "COUNT"]

RESPONSE_DIRECTORY = "tool-responses"
CHECK_FILENAME = "evidence-check.json"
MAX_DERIVATION_VALUES = 100
_EXCLUDED_VALUE_FIELDS = {
    "document_id", "file_id", "table_id", "source_id", "source_ids",
    "matched_rows", "rows_returned", "result_rows_before_limit",
    "source_rows_matched", "score", "section", "total_sections", "truncated",
}
_NEGATIVE_MARKERS = (
    "not found", "not available", "not specified", "not set", "no information",
    "없", "않", "미정", "확인할 수 없", "찾을 수 없",
)
_UNIT_FAMILIES = {
    "day": {"day", "days", "일"},
    "hour": {"hour", "hours", "hr", "hrs", "시간"},
    "percent": {"percent", "percentage", "%", "퍼센트"},
    "ratio": {"ratio", "rate", "비율"},
    "krw": {"krw", "원", "₩"},
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


class ToolResponseRecord(StrictProductModel):
    schema_version: Literal["ax-tool-response-v1"] = "ax-tool-response-v1"
    run_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    tool_name: Literal[
        "search_documents", "read_document", "lookup_value", "query_table"
    ]
    output: dict[str, Any]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_record(self) -> "ToolResponseRecord":
        if not RUN_ID_PATTERN.fullmatch(self.run_id):
            raise ValueError("invalid run_id")
        if self.output_sha256 != _sha256_bytes(_canonical_bytes(self.output)):
            raise ValueError("output_sha256 does not match output")
        return self


class EvidenceReference(StrictProductModel):
    sequence: int = Field(ge=1)
    tool_name: str = Field(min_length=1)
    source_ids: list[str]
    match: Literal["CITED_RESPONSE", "DIRECT_VALUE", "DERIVATION_INPUT", "PARTIAL_VALUE"]


class EvidenceDerivation(StrictProductModel):
    operation: DerivationOperation
    field: str | None = None
    operands: list[int | float]
    result: int | float


class EvidenceCheckResult(StrictProductModel):
    schema_version: Literal["ax-evidence-check-v1"] = "ax-evidence-check-v1"
    run_id: str = Field(min_length=1)
    verdict: EvidenceVerdict
    delivery_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cited_source_ids: list[str]
    matched_source_ids: list[str]
    unmatched_source_ids: list[str]
    evidence: list[EvidenceReference]
    derivation: EvidenceDerivation | None = None
    limitations: list[str]
    unconfirmed_is_not_incorrect: Literal[True] = True


class EvidenceArtifactExistsError(ValueError):
    pass


class ToolResponseStore:
    """Write-once structured data-tool responses, isolated by run directory."""

    def __init__(self, root: str | Path = DEFAULT_RESULTS_ROOT):
        self.root = Path(root).resolve()

    def directory(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("invalid run_id")
        return self.root / run_id / RESPONSE_DIRECTORY

    def record(self, *, run_id: str, tool_name: str, output: dict[str, Any]) -> Path:
        if tool_name not in AX_MCP_TOOL_NAMES:
            raise ValueError("only AX data-tool responses may be recorded")
        directory = self.directory(run_id)
        if not directory.parent.is_dir():
            raise FileNotFoundError(f"run has not been reserved: {run_id}")
        directory.mkdir(exist_ok=True)
        sequence = len(list(directory.glob("*.json"))) + 1
        record = ToolResponseRecord(
            run_id=run_id, sequence=sequence, tool_name=tool_name,
            output=output, output_sha256=_sha256_bytes(_canonical_bytes(output)),
        )
        path = directory / f"{sequence:06d}.json"
        _write_json_once(path, record.model_dump(mode="json"))
        return path

    def read(self, run_id: str) -> list[ToolResponseRecord]:
        directory = self.directory(run_id)
        if not directory.is_dir():
            return []
        records = [
            ToolResponseRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        ]
        if any(record.run_id != run_id for record in records):
            raise ValueError("cross-run tool response record")
        if [record.sequence for record in records] != list(range(1, len(records) + 1)):
            raise ValueError("tool response sequence is incomplete or duplicated")
        return records


class EvidenceCheckStore:
    def __init__(self, root: str | Path = DEFAULT_RESULTS_ROOT):
        self.root = Path(root).resolve()

    def path(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("invalid run_id")
        return self.root / run_id / CHECK_FILENAME

    def write(self, result: EvidenceCheckResult) -> Path:
        path = self.path(result.run_id)
        if not path.parent.is_dir():
            raise FileNotFoundError(f"run has not been reserved: {result.run_id}")
        try:
            _write_json_once(path, result.model_dump(mode="json"))
        except FileExistsError as exc:
            raise EvidenceArtifactExistsError(result.run_id) from exc
        return path

    def read(self, run_id: str) -> EvidenceCheckResult:
        return EvidenceCheckResult.model_validate_json(
            self.path(run_id).read_text(encoding="utf-8")
        )


class ReadOnlyEvidenceCheckStore:
    """Evidence lookup surface for a frozen root, without mutation methods."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def path(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("invalid run_id")
        return self.root / run_id / CHECK_FILENAME

    def read(self, run_id: str) -> EvidenceCheckResult:
        return EvidenceCheckResult.model_validate_json(
            self.path(run_id).read_text(encoding="utf-8")
        )


class EvidenceCheckLookup:
    """Resolve evidence through the same run origin chosen for delivery reads."""

    def __init__(self, results: CompositeResultStore):
        self.results = results
        self.writable = EvidenceCheckStore(results.root)
        self.frozen = (
            ReadOnlyEvidenceCheckStore(results.frozen.root)
            if results.frozen is not None
            else None
        )

    def read(self, run_id: str) -> EvidenceCheckResult:
        if self.results.origin(run_id) == "frozen":
            assert self.frozen is not None
            return self.frozen.read(run_id)
        return self.writable.read(run_id)


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


def _strings(value: Any) -> set[str]:
    values = value if isinstance(value, list) else [value]
    return {item for item in values if isinstance(item, str) and item}


def _source_ids(tool_name: str, output: dict[str, Any]) -> set[str]:
    """Extract identifiers only from fields defined as citations by each tool."""
    identifiers: set[str] = set()
    if tool_name == "search_documents":
        for hit in output.get("results", []):
            if not isinstance(hit, dict):
                continue
            identifiers.update(_strings(hit.get("document_id")))
            for table in hit.get("tables", []):
                if isinstance(table, dict):
                    identifiers.update(_strings(table.get("table_id")))
    elif tool_name == "read_document":
        identifiers.update(_strings(output.get("document_id")))
    elif tool_name in {"lookup_value", "query_table"}:
        identifiers.update(_strings(output.get("table_id")))
        identifiers.update(_strings(output.get("source_ids")))
    return identifiers


def response_source_ids(tool_name: str, output: dict[str, Any]) -> set[str]:
    """Public, citation-safe source ID extraction for downstream audit views."""
    return _source_ids(tool_name, output)


@dataclass(frozen=True)
class DataCell:
    field: str | None
    value: str | int | float | bool
    row: dict[str, Any] | None = None


@dataclass
class AllowedData:
    texts: list[str]
    cells: list[DataCell]
    row_sets: list[tuple[list[dict[str, Any]], bool]]


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool))


def _complete_query_rows(output: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    returned = output.get("rows_returned")
    before_limit = output.get("result_rows_before_limit")
    return (
        output.get("truncated") is False
        and isinstance(returned, int) and not isinstance(returned, bool)
        and isinstance(before_limit, int) and not isinstance(before_limit, bool)
        and returned == before_limit == len(rows)
    )


def _allowed_data(records: list[ToolResponseRecord], cited: set[str]) -> AllowedData:
    """Select only documented business-data fields, never arbitrary output leaves."""
    texts: list[str] = []
    cells: list[DataCell] = []
    row_sets: list[tuple[list[dict[str, Any]], bool]] = []
    for record in records:
        output = record.output
        if record.tool_name == "search_documents":
            for hit in output.get("results", []):
                if not isinstance(hit, dict):
                    continue
                hit_ids = _strings(hit.get("document_id"))
                for table in hit.get("tables", []):
                    if isinstance(table, dict):
                        hit_ids.update(_strings(table.get("table_id")))
                snippet = hit.get("snippet")
                if hit_ids.intersection(cited) and isinstance(snippet, str):
                    texts.append(snippet)
        elif record.tool_name == "read_document":
            if output.get("document_id") in cited and isinstance(output.get("content"), str):
                texts.append(output["content"])
        elif record.tool_name == "lookup_value":
            if _source_ids(record.tool_name, output).intersection(cited):
                value = output.get("value")
                if _is_scalar(value):
                    cells.append(DataCell(field="value", value=value))
                    if isinstance(value, str):
                        texts.append(value)
                elif isinstance(value, list):
                    for item in value:
                        if _is_scalar(item):
                            cells.append(DataCell(field="value", value=item))
                            if isinstance(item, str):
                                texts.append(item)
        elif record.tool_name == "query_table":
            if not _source_ids(record.tool_name, output).intersection(cited):
                continue
            raw_rows = output.get("rows")
            if not isinstance(raw_rows, list):
                continue
            rows = [row for row in raw_rows if isinstance(row, dict)]
            row_sets.append((rows, _complete_query_rows(output, rows)))
            for row in rows:
                for field, value in row.items():
                    if str(field) not in _EXCLUDED_VALUE_FIELDS and _is_scalar(value):
                        cells.append(DataCell(field=str(field), value=value, row=row))
                        if isinstance(value, str) and _decimal(value) is None:
                            texts.append(value)
    return AllowedData(texts=texts, cells=cells, row_sets=row_sets)


def _numeric_token_in_text(text: str, target: Decimal) -> bool:
    for token in re.findall(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])", text):
        if _decimal(token) == target:
            return True
    return False


def _unit_family(unit: str) -> tuple[str, set[str]]:
    normalized = _normalize_text(unit).replace("_threshold", "").strip()
    for family, aliases in _UNIT_FAMILIES.items():
        if normalized in aliases or normalized.rstrip("s") in {alias.rstrip("s") for alias in aliases}:
            return family, aliases
    return normalized, {normalized}


def _answer_quantity(answer: Any, unit: str | None) -> tuple[Decimal, str] | None:
    parsed = _decimal(answer)
    if parsed is not None:
        return (parsed, unit) if unit else None
    if not isinstance(answer, str):
        return None
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*([^\d\s].*?)\s*", answer)
    if match is None:
        return None
    value = _decimal(match.group(1))
    if value is None:
        return None
    embedded_unit = match.group(2)
    if unit is not None:
        embedded_family, _ = _unit_family(embedded_unit)
        declared_family, _ = _unit_family(unit)
        if embedded_family != declared_family:
            return None
        return value, unit
    return value, embedded_unit


def _segments(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\n.!?。]+", _normalize_text(text)) if part.strip()]


def _has_unit(text: str, aliases: set[str]) -> bool:
    normalized = _normalize_text(text)
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


def _field_has_unit(field: str | None, family: str, aliases: set[str]) -> bool:
    if field is None:
        return False
    normalized = _normalize_text(field).replace("_", " ")
    if family == "ratio" and normalized in {"rate", "ratio"}:
        return True
    return _has_unit(normalized, aliases)


def _row_has_unit(row: dict[str, Any] | None, aliases: set[str]) -> bool:
    if row is None:
        return False
    for field, value in row.items():
        normalized_field = _normalize_text(str(field)).replace("_", " ")
        if (normalized_field == "unit" or normalized_field.endswith(" unit")
                or normalized_field in {"currency", "단위"}):
            if isinstance(value, str) and _has_unit(value, aliases):
                return True
    return False


def _quantity_direct(value: Decimal, unit: str, data: AllowedData) -> bool:
    family, aliases = _unit_family(unit)
    for text in data.texts:
        for segment in _segments(text):
            if _numeric_token_in_text(segment, value) and _has_unit(segment, aliases):
                return True
    for cell in data.cells:
        if _decimal(cell.value) != value:
            continue
        if _field_has_unit(cell.field, family, aliases) or _row_has_unit(cell.row, aliases):
            return True
        if isinstance(cell.value, str) and _has_unit(cell.value, aliases):
            return True
    return False


def _direct_match(answer: Any, unit: str | None, data: AllowedData) -> tuple[bool, bool]:
    """Return (all matched, at least one matched) without semantic inference."""
    texts = [_normalize_text(text) for text in data.texts]
    scalar_texts = [_normalize_text(str(cell.value)) for cell in data.cells]
    quantity = _answer_quantity(answer, unit)
    if unit is not None and quantity is None:
        # v1 has no sound unit relationship for lists, booleans, or other
        # non-quantity answer shapes, even when their raw value occurs.
        return False, False
    if isinstance(answer, list):
        matches = [
            any(_normalize_text(item) in text for text in texts)
            or any(_normalize_text(item) == scalar for scalar in scalar_texts)
            for item in answer
        ]
        return bool(matches) and all(matches), any(matches)
    if quantity is not None:
        matched = _quantity_direct(quantity[0], quantity[1], data)
        numeric_clue = any(
            _decimal(cell.value) == quantity[0] for cell in data.cells
        )
        numeric_clue = numeric_clue or any(
            any(_numeric_token_in_text(segment, quantity[0]) for segment in _segments(text))
            for text in data.texts
        )
        return matched, numeric_clue
    numeric_target = _decimal(answer)
    if isinstance(answer, str) and numeric_target is not None:
        matched = any(_decimal(cell.value) == numeric_target for cell in data.cells)
        matched = matched or any(
            _numeric_token_in_text(segment, numeric_target)
            for text in data.texts for segment in _segments(text)
        )
        return matched, matched
    if isinstance(answer, str):
        target = _normalize_text(answer)
        matched = any(target in text for text in texts) or any(
            target == scalar for scalar in scalar_texts
        )
        return matched, matched
    if isinstance(answer, bool):
        matched = any(cell.value is answer for cell in data.cells)
        return matched, matched
    target = _decimal(answer)
    if target is None:
        return False, False
    matched = any(_decimal(cell.value) == target for cell in data.cells)
    matched = matched or any(
        _numeric_token_in_text(segment, target)
        for text in data.texts for segment in _segments(text)
    )
    return matched, matched


def _row_fields(rows: list[dict[str, Any]]) -> dict[str, list[Decimal]]:
    fields: dict[str, list[Decimal]] = {}
    for row in rows:
        for field, value in row.items():
            if str(field) in _EXCLUDED_VALUE_FIELDS:
                continue
            parsed = _decimal(value)
            if parsed is not None:
                fields.setdefault(str(field), []).append(parsed)
    return fields


def _as_json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _derivations(answer: Any, data: AllowedData) -> list[EvidenceDerivation]:
    target = _decimal(answer)
    if target is None:
        return []
    candidates: dict[tuple, EvidenceDerivation] = {}
    for rows, complete in data.row_sets:
        if not complete:
            continue
        if Decimal(len(rows)) == target:
            proof = EvidenceDerivation(operation="COUNT", operands=[], result=_as_json_number(target))
            candidates[("COUNT", None, ())] = proof
        for field, values in _row_fields(rows).items():
            if not values or len(values) > MAX_DERIVATION_VALUES:
                continue
            if len(values) > 1 and sum(values, Decimal(0)) == target:
                proof = EvidenceDerivation(
                    operation="SUM", field=field,
                    operands=[_as_json_number(value) for value in values],
                    result=_as_json_number(target),
                )
                candidates[("SUM", field, tuple(values))] = proof
            for left, right in combinations(values, 2):
                if left - right == target or right - left == target:
                    ordered = (left, right) if left - right == target else (right, left)
                    proof = EvidenceDerivation(
                        operation="DIFFERENCE", field=field,
                        operands=[_as_json_number(value) for value in ordered],
                        result=_as_json_number(target),
                    )
                    candidates[("DIFFERENCE", field, ordered)] = proof
    return list(candidates.values())


def _negative_fragments(explanation: str) -> list[str]:
    normalized = _normalize_text(explanation)
    quoted = re.findall(r"['\"“”‘’]([^'\"“”‘’]{12,})['\"“”‘’]", normalized)
    fragments = {
        fragment.strip(" .'\"“”‘’")
        for fragment in re.split(r"[\n.!?。]", "\n".join([normalized, *quoted]))
        if len(fragment.strip()) >= 6
        and any(marker in fragment for marker in _NEGATIVE_MARKERS)
    }
    return sorted(fragments, key=len, reverse=True)


def _abstention_direct(explanation: str, data: AllowedData) -> bool:
    fragments = _negative_fragments(explanation)
    if not fragments:
        return False
    response_segments = [segment for text in data.texts for segment in _segments(text)]
    return any(fragment in segment for fragment in fragments for segment in response_segments)


def check_evidence(
    delivery: DeliveryEnvelope, records: list[ToolResponseRecord]
) -> EvidenceCheckResult:
    """Assess support without consulting model prose, source files, or answer keys."""
    delivery_json = delivery.model_dump(mode="json")
    delivery_sha = _sha256_bytes(_canonical_bytes(delivery_json))
    limitations = [
        "Checks only the approved Delivery JSON and cited structured tool responses from this run.",
        "DERIVABLE is limited to exact sum, difference, and row count; division, rates, unit conversion, and semantic inference are out of scope.",
        "A lexical direct match does not independently establish broader contextual entailment.",
    ]
    if delivery.delivery_status != "DELIVERED" or delivery.payload is None:
        return EvidenceCheckResult(
            run_id=delivery.run_id, verdict="UNCONFIRMED", delivery_sha256=delivery_sha,
            cited_source_ids=[], matched_source_ids=[], unmatched_source_ids=[], evidence=[],
            limitations=limitations + ["The delivery has no approved answer payload to check."],
        )
    if any(record.run_id != delivery.run_id for record in records):
        raise ValueError("tool responses must belong to the delivery run")
    cited = delivery.payload.source_ids
    if not records:
        return EvidenceCheckResult(
            run_id=delivery.run_id, verdict="UNCONFIRMED", delivery_sha256=delivery_sha,
            cited_source_ids=cited, matched_source_ids=[], unmatched_source_ids=cited,
            evidence=[], limitations=limitations + ["No structured tool response record is available."],
        )
    if not cited:
        return EvidenceCheckResult(
            run_id=delivery.run_id, verdict="UNCONFIRMED", delivery_sha256=delivery_sha,
            cited_source_ids=[], matched_source_ids=[], unmatched_source_ids=[], evidence=[],
            limitations=limitations + ["The delivery cites no source ID; uncited responses are not inspected."],
        )

    record_ids = [(record, _source_ids(record.tool_name, record.output)) for record in records]
    cited_records = [(record, ids) for record, ids in record_ids if ids.intersection(cited)]
    observed_ids = set().union(*(ids for _, ids in cited_records)) if cited_records else set()
    matched = sorted(set(cited).intersection(observed_ids))
    unmatched = [source_id for source_id in cited if source_id not in matched]
    if not cited_records:
        return EvidenceCheckResult(
            run_id=delivery.run_id, verdict="UNCONFIRMED", delivery_sha256=delivery_sha,
            cited_source_ids=cited, matched_source_ids=[], unmatched_source_ids=cited,
            evidence=[], limitations=limitations + ["No same-run response contains a cited source ID."],
        )
    cited_only_records = [record for record, _ in cited_records]
    data = _allowed_data(cited_only_records, set(cited))
    base_refs = [EvidenceReference(
        sequence=record.sequence, tool_name=record.tool_name,
        source_ids=sorted(ids.intersection(cited)), match="CITED_RESPONSE",
    ) for record, ids in cited_records]

    payload = delivery.payload
    if payload.status == "ABSTAINED":
        direct = _abstention_direct(payload.explanation, data)
        verdict: EvidenceVerdict = "DIRECT_MATCH" if direct and not unmatched else "PARTIAL_SUPPORT" if direct else "UNCONFIRMED"
        refs = [ref.model_copy(update={"match": "DIRECT_VALUE"}) for ref in base_refs] if direct else base_refs
        if not direct:
            limitations.append("The cited response does not contain an exact negative statement from the approved abstention explanation.")
        return EvidenceCheckResult(
            run_id=delivery.run_id, verdict=verdict, delivery_sha256=delivery_sha,
            cited_source_ids=cited, matched_source_ids=matched, unmatched_source_ids=unmatched,
            evidence=refs, limitations=limitations,
        )

    direct, partial = _direct_match(payload.answer, payload.unit, data)
    if direct and not unmatched:
        return EvidenceCheckResult(
            run_id=delivery.run_id, verdict="DIRECT_MATCH", delivery_sha256=delivery_sha,
            cited_source_ids=cited, matched_source_ids=matched, unmatched_source_ids=[],
            evidence=[ref.model_copy(update={"match": "DIRECT_VALUE"}) for ref in base_refs],
            limitations=limitations,
        )
    derivations = [] if payload.unit or _answer_quantity(payload.answer, payload.unit) else _derivations(payload.answer, data)
    if len(derivations) == 1 and not unmatched:
        return EvidenceCheckResult(
            run_id=delivery.run_id, verdict="DERIVABLE", delivery_sha256=delivery_sha,
            cited_source_ids=cited, matched_source_ids=matched, unmatched_source_ids=[],
            evidence=[ref.model_copy(update={"match": "DERIVATION_INPUT"}) for ref in base_refs],
            derivation=derivations[0], limitations=limitations,
        )
    if len(derivations) > 1:
        partial = True
        limitations.append("Multiple fields or allowed operations reproduce the answer, so no unique derivation is selected.")
    if partial:
        limitations.append("The cited response offers a clue, but the answer is not directly matched or reproducible by an allowed derivation.")
        return EvidenceCheckResult(
            run_id=delivery.run_id, verdict="PARTIAL_SUPPORT", delivery_sha256=delivery_sha,
            cited_source_ids=cited, matched_source_ids=matched, unmatched_source_ids=unmatched,
            evidence=[ref.model_copy(update={"match": "PARTIAL_VALUE"}) for ref in base_refs],
            limitations=limitations,
        )
    limitations.append("The cited response does not provide a deterministic match within checker v1 scope.")
    return EvidenceCheckResult(
        run_id=delivery.run_id, verdict="UNCONFIRMED", delivery_sha256=delivery_sha,
        cited_source_ids=cited, matched_source_ids=matched, unmatched_source_ids=unmatched,
        evidence=base_refs, limitations=limitations,
    )


def check_run(root: str | Path, run_id: str) -> EvidenceCheckResult:
    """Read one stored delivery and its same-directory response records."""
    from .results import ResultStore

    result_root = Path(root).resolve()
    result_store = ResultStore(result_root)
    delivery = result_store.read(run_id)
    records = ToolResponseStore(result_root).read(run_id)
    result = check_evidence(delivery, records)
    return result.model_copy(update={
        "delivery_sha256": _sha256_bytes(result_store.path(run_id).read_bytes())
    })
