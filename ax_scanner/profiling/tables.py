from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable

from ax_scanner.models import ColumnProfile, DataType, TableProfile


_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\d*\.\d+)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?$")


def _is_null(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _value_type(value: Any) -> DataType:
    if _is_null(value):
        return DataType.EMPTY
    if isinstance(value, bool):
        return DataType.BOOLEAN
    if isinstance(value, int):
        return DataType.INTEGER
    if isinstance(value, float):
        return DataType.NUMBER
    if isinstance(value, datetime):
        return DataType.DATETIME
    if isinstance(value, date):
        return DataType.DATE
    text = str(value).strip()
    lowered = text.lower()
    if lowered in {"true", "false", "yes", "no"}:
        return DataType.BOOLEAN
    if _INTEGER_RE.fullmatch(text):
        return DataType.INTEGER
    if _NUMBER_RE.fullmatch(text):
        return DataType.NUMBER
    if _DATETIME_RE.fullmatch(text):
        return DataType.DATETIME
    if _DATE_RE.fullmatch(text):
        return DataType.DATE
    return DataType.STRING


def _column_type(values: list[Any]) -> DataType:
    types = {_value_type(value) for value in values if not _is_null(value)}
    if not types:
        return DataType.EMPTY
    if types <= {DataType.INTEGER}:
        return DataType.INTEGER
    if types <= {DataType.INTEGER, DataType.NUMBER}:
        return DataType.NUMBER
    if len(types) == 1:
        return next(iter(types))
    return DataType.MIXED


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _unique_headers(values: Iterable[Any], width: int) -> list[str]:
    seen: dict[str, int] = {}
    headers = []
    source = list(values)
    for index in range(width):
        raw = source[index] if index < len(source) else None
        base = str(raw).strip() if not _is_null(raw) else f"column_{index + 1}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        headers.append(base if count == 1 else f"{base}_{count}")
    return headers


def profile_rows(
    rows: Iterable[Iterable[Any]],
    *,
    file_id: str,
    sheet_name: str,
    merged_ranges: list[str] | None = None,
) -> TableProfile:
    materialized = [list(row) for row in rows]
    while materialized and not any(not _is_null(value) for value in materialized[-1]):
        materialized.pop()
    first_nonempty = next((i for i, row in enumerate(materialized) if any(not _is_null(value) for value in row)), None)
    if first_nonempty is None:
        return TableProfile(
            table_id=f"TABLE_{file_id}_{sheet_name}",
            file_id=file_id,
            sheet_name=sheet_name,
            row_count=0,
            column_count=0,
            column_names=[],
            columns=[],
            merged_cell_present=bool(merged_ranges),
            merged_ranges=merged_ranges or [],
        )

    header_row = materialized[first_nonempty]
    candidate_rows = materialized[first_nonempty + 1 :]
    data_rows = [row for row in candidate_rows if any(not _is_null(value) for value in row)]
    width = max([len(header_row), *(len(row) for row in data_rows)] if data_rows else [len(header_row)])
    headers = _unique_headers(header_row, width)
    padded = [row + [None] * (width - len(row)) for row in data_rows]
    columns = []
    for index, name in enumerate(headers):
        values = [row[index] for row in padded]
        null_count = sum(_is_null(value) for value in values)
        samples = []
        for value in values:
            if _is_null(value):
                continue
            safe = _json_value(value)
            if safe not in samples:
                samples.append(safe)
            if len(samples) == 3:
                break
        columns.append(
            ColumnProfile(
                name=name,
                inferred_type=_column_type(values),
                null_ratio=(null_count / len(values)) if values else 0.0,
                sample_values=samples,
            )
        )
    safe_sheet = re.sub(r"[^0-9A-Za-z가-힣]+", "_", sheet_name).strip("_") or "sheet"
    return TableProfile(
        table_id=f"TABLE_{file_id}_{safe_sheet}",
        file_id=file_id,
        sheet_name=sheet_name,
        row_count=len(padded),
        column_count=width,
        column_names=headers,
        columns=columns,
        merged_cell_present=bool(merged_ranges),
        merged_ranges=merged_ranges or [],
    )

