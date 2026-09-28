"""Deterministic AX Readiness Score v1 computed only from a Scanner report."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "ax-readiness-score-v1"
AS_OF_DATE = date(2026, 9, 21)
STALE_THRESHOLD_DAYS = 365
DIMENSION_WEIGHTS = {
    "accessibility": Decimal("0.20"),
    "completeness": Decimal("0.20"),
    "redundancy": Decimal("0.20"),
    "timeliness": Decimal("0.20"),
    "safety": Decimal("0.20"),
}
OUTPUT_QUANTUM = Decimal("0.000001")


def _decimal(value: Any, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative integer") from exc
    if result < 0 or result != value:
        raise ValueError(f"{field} must be a non-negative integer")
    return result


def _number(value: Decimal) -> float:
    """Return a stable six-decimal JSON number."""
    return float(value.quantize(OUTPUT_QUANTUM, rounding=ROUND_HALF_UP))


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _timestamp_date(value: Any) -> tuple[date | None, str | None]:
    if value is None or value == "":
        return None, "missing"
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None, "invalid"
    else:
        return None, "invalid"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "invalid"
    return parsed.astimezone(timezone.utc).date(), None


def _as_mapping(report: Any) -> Mapping[str, Any]:
    if hasattr(report, "model_dump"):
        report = report.model_dump(mode="python")
    if not isinstance(report, Mapping):
        raise TypeError("report must be a Scanner report mapping or Pydantic model")
    return report


def calculate_readiness_score(report: Any) -> dict[str, Any]:
    """Calculate AX Readiness Score v1 without reading files or calling an LLM."""
    payload = _as_mapping(report)
    files = list(payload.get("files", []))
    tables = list(payload.get("tables", []))
    duplicates = list(payload.get("duplicates", []))
    unreadable = list(payload.get("unreadable_sources", []))
    pii_findings = list(payload.get("pii_findings", []))
    total_files = len(files)

    file_ids = {item.get("file_id") for item in files if item.get("file_id") is not None}
    if len(file_ids) != total_files:
        raise ValueError("every file must have a unique file_id")

    ocr_required_ids = {
        item.get("file_id")
        for item in unreadable
        if item.get("requires_ocr") is True or item.get("reason") == "OCR_REQUIRED"
    }
    ocr_required_ids.discard(None)
    parsed_ids = {
        item["file_id"]
        for item in files
        if _status_value(item.get("parse_status")) == "PARSED"
    }
    accessible_ids = parsed_ids - ocr_required_ids
    accessibility = Decimal(len(accessible_ids)) / Decimal(total_files) if total_files else Decimal(0)

    total_cells = 0
    estimated_missing_cells = Decimal(0)
    for table_index, table in enumerate(tables):
        row_count = _nonnegative_int(table.get("row_count"), field=f"tables[{table_index}].row_count")
        column_count = _nonnegative_int(
            table.get("column_count"), field=f"tables[{table_index}].column_count"
        )
        columns = list(table.get("columns", []))
        if len(columns) != column_count:
            raise ValueError(
                f"tables[{table_index}] column_count does not match the number of column profiles"
            )
        total_cells += row_count * column_count
        for column_index, column in enumerate(columns):
            ratio = _decimal(
                column.get("null_ratio"),
                field=f"tables[{table_index}].columns[{column_index}].null_ratio",
            )
            if ratio < 0 or ratio > 1:
                raise ValueError("column null_ratio must be between 0 and 1")
            estimated_missing_cells += ratio * row_count
    completeness_not_applicable = total_cells == 0
    completeness = (
        Decimal(1)
        if completeness_not_applicable
        else Decimal(1) - estimated_missing_cells / Decimal(total_cells)
    )

    duplicate_members: set[str] = set()
    redundant_files = 0
    for group_index, group in enumerate(duplicates):
        members = list(group.get("file_ids", []))
        if len(members) < 2:
            raise ValueError(f"duplicates[{group_index}] must contain at least two file_ids")
        if len(set(members)) != len(members):
            raise ValueError(f"duplicates[{group_index}] contains repeated file_ids")
        overlap = duplicate_members.intersection(members)
        if overlap:
            raise ValueError("a file cannot occur in more than one exact duplicate group")
        unknown = set(members) - file_ids
        if unknown:
            raise ValueError("exact duplicate groups must reference known files")
        duplicate_members.update(members)
        redundant_files += len(members) - 1
    redundancy = (
        Decimal(1) - Decimal(redundant_files) / Decimal(total_files)
        if total_files
        else Decimal(0)
    )

    valid_timestamp_count = 0
    non_stale_files = 0
    stale_files = 0
    future_timestamp_count = 0
    missing_timestamp_count = 0
    invalid_timestamp_count = 0
    for item in files:
        modified_date, timestamp_error = _timestamp_date(item.get("modified_at"))
        if timestamp_error == "missing":
            missing_timestamp_count += 1
            continue
        if timestamp_error == "invalid":
            invalid_timestamp_count += 1
            continue
        valid_timestamp_count += 1
        age_days = (AS_OF_DATE - modified_date).days
        if age_days < 0:
            future_timestamp_count += 1
        elif age_days <= STALE_THRESHOLD_DAYS:
            non_stale_files += 1
        else:
            stale_files += 1
    timeliness = (
        Decimal(non_stale_files) / Decimal(valid_timestamp_count)
        if valid_timestamp_count
        else Decimal(0)
    )

    pii_file_ids = {item.get("file_id") for item in pii_findings if item.get("file_id") is not None}
    unknown_pii_file_ids = pii_file_ids - file_ids
    pii_affected_ids = pii_file_ids.intersection(file_ids)
    safety = (
        Decimal(1) - Decimal(len(pii_affected_ids)) / Decimal(total_files)
        if total_files
        else Decimal(0)
    )

    dimensions_decimal = {
        "accessibility": accessibility,
        "completeness": completeness,
        "redundancy": redundancy,
        "timeliness": timeliness,
        "safety": safety,
    }
    weighted_mean = sum(
        dimensions_decimal[name] * DIMENSION_WEIGHTS[name] for name in DIMENSION_WEIGHTS
    )
    metadata_file_count = payload.get("scan_metadata", {}).get("file_count")

    return {
        "schema_version": SCHEMA_VERSION,
        "readiness_score": _number(Decimal(100) * weighted_mean),
        "dimensions": {name: _number(value) for name, value in dimensions_decimal.items()},
        "dimension_weights": {name: _number(value) for name, value in DIMENSION_WEIGHTS.items()},
        "counts": {
            "accessibility": {
                "total_files": total_files,
                "parsed_files": len(parsed_ids),
                "ocr_required_files": len(ocr_required_ids),
                "accessible_files": len(accessible_ids),
            },
            "completeness": {
                "eligible_tables": len(tables),
                "total_cells": total_cells,
                "estimated_missing_cells": _number(estimated_missing_cells),
            },
            "redundancy": {
                "total_files": total_files,
                "exact_duplicate_groups": len(duplicates),
                "redundant_files": redundant_files,
            },
            "timeliness": {
                "files_with_valid_modified_at": valid_timestamp_count,
                "non_stale_files": non_stale_files,
                "stale_files": stale_files,
                "future_timestamp_files": future_timestamp_count,
                "missing_timestamp_files": missing_timestamp_count,
                "invalid_timestamp_files": invalid_timestamp_count,
            },
            "safety": {
                "total_files": total_files,
                "pii_affected_files": len(pii_affected_ids),
                "files_without_detected_pii": total_files - len(pii_affected_ids),
            },
        },
        "as_of_date": AS_OF_DATE.isoformat(),
        "stale_threshold_days": STALE_THRESHOLD_DAYS,
        "flags": {
            "empty_file_set": total_files == 0,
            "completeness_not_applicable": completeness_not_applicable,
            "no_valid_modified_at": valid_timestamp_count == 0,
            "missing_modified_at_count": missing_timestamp_count,
            "invalid_modified_at_count": invalid_timestamp_count,
            "future_modified_at_count": future_timestamp_count,
            "unknown_ocr_file_id_count": len(ocr_required_ids - file_ids),
            "unknown_pii_file_id_count": len(unknown_pii_file_ids),
            "scan_metadata_file_count_mismatch": (
                metadata_file_count is not None and metadata_file_count != total_files
            ),
        },
    }


def canonical_json(result: Mapping[str, Any]) -> str:
    """Serialize a result reproducibly for hashing or byte comparison."""
    return json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def score_scan_report_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return calculate_readiness_score(payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan_report", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    rendered = canonical_json(score_scan_report_file(arguments.scan_report))
    if arguments.output is None:
        print(rendered, end="")
    else:
        arguments.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
