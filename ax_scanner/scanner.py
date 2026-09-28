from __future__ import annotations

import hashlib
import os
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    DuplicateGroup,
    FileRecord,
    LiveLLMStatus,
    PIIFinding,
    ParseStatus,
    ScanMetadata,
    ScanReport,
    TableProfile,
    UnreadableSource,
)
from .parsers import SUPPORTED_EXTENSIONS, parse_file
from .pii import detect_pii, mask_text
from .versioning import group_probable_versions


SCHEMA_VERSION = "ax-scan-report-v1"
SCANNER_VERSION = "0.1.0"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_file_id(relative_path: str) -> str:
    normalized = unicodedata.normalize("NFC", relative_path)
    return f"FILE_{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def _modified_at(path: Path) -> str:
    value = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:500]}"


def _mask_table_samples(tables: list[TableProfile]) -> None:
    for table in tables:
        for column in table.columns:
            masked_samples = []
            for value in column.sample_values:
                if isinstance(value, str):
                    masked_samples.append(mask_text(value, detect_pii(value)))
                else:
                    masked_samples.append(value)
            column.sample_values = masked_samples


def scan_folder(
    root: Path,
    *,
    live_llm: LiveLLMStatus,
    ocr_min_chars_per_page: int = 20,
    exclude_paths: set[Path] | None = None,
) -> ScanReport:
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    excluded = {path.resolve() for path in (exclude_paths or set())}
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.resolve() not in excluded),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    files: list[FileRecord] = []
    tables = []
    pii_findings: list[PIIFinding] = []
    unreadable_sources: list[UnreadableSource] = []

    for path in paths:
        relative_path = path.relative_to(root).as_posix()
        extension = path.suffix.lower()
        file_id = _stable_file_id(relative_path)
        stat = path.stat()
        common = {
            "file_id": file_id,
            "relative_path": relative_path,
            "filename": path.name,
            "extension": extension,
            "size": stat.st_size,
            "modified_at": _modified_at(path),
            "sha256": _sha256_file(path),
        }
        if extension not in SUPPORTED_EXTENSIONS:
            files.append(
                FileRecord(
                    **common,
                    parse_status=ParseStatus.UNSUPPORTED,
                    text_char_count=0,
                    parse_error=f"Unsupported extension: {extension or '[none]'}",
                )
            )
            continue
        try:
            parsed = parse_file(path, file_id, ocr_min_chars_per_page=ocr_min_chars_per_page)
            detected = detect_pii(parsed.text)
            masked = mask_text(parsed.text, detected)
            for finding in detected:
                pii_findings.append(
                    PIIFinding(
                        file_id=file_id,
                        pii_type=finding.pii_type,
                        start=finding.start,
                        end=finding.end,
                        match_length=finding.end - finding.start,
                        masked_token=finding.masked_token,
                    )
                )
            files.append(
                FileRecord(
                    **common,
                    parse_status=ParseStatus.PARSED,
                    parser=parsed.parser,
                    text=masked,
                    text_char_count=len(parsed.text),
                    pii_finding_count=len(detected),
                    parser_metadata=parsed.metadata,
                )
            )
            _mask_table_samples(parsed.tables)
            tables.extend(parsed.tables)
            if parsed.requires_ocr:
                unreadable_sources.append(
                    UnreadableSource(
                        file_id=file_id,
                        relative_path=relative_path,
                        reason=parsed.unreadable_reason or "OCR_REQUIRED",
                        extracted_char_count=len(parsed.text),
                        requires_ocr=True,
                    )
                )
        except Exception as exc:  # isolate one corrupt/unsupported file from the folder scan
            files.append(
                FileRecord(
                    **common,
                    parse_status=ParseStatus.ERROR,
                    text_char_count=0,
                    parse_error=_safe_error(exc),
                )
            )

    by_hash: dict[str, list[FileRecord]] = defaultdict(list)
    for file in files:
        by_hash[file.sha256].append(file)
    duplicates = []
    for digest, members in sorted(by_hash.items()):
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda file: file.relative_path)
        duplicates.append(
            DuplicateGroup(
                duplicate_group_id=f"DUP_{digest[:16]}",
                sha256=digest,
                file_ids=[file.file_id for file in ordered],
                relative_paths=[file.relative_path for file in ordered],
                copy_count=len(ordered),
            )
        )

    status_counts = defaultdict(int)
    for file in files:
        status_counts[file.parse_status] += 1
    return ScanReport(
        scan_metadata=ScanMetadata(
            schema_version=SCHEMA_VERSION,
            scanner_version=SCANNER_VERSION,
            source_root_name=root.name,
            supported_extensions=list(SUPPORTED_EXTENSIONS),
            ocr_min_chars_per_page=ocr_min_chars_per_page,
            file_count=len(files),
            parsed_file_count=status_counts[ParseStatus.PARSED],
            unsupported_file_count=status_counts[ParseStatus.UNSUPPORTED],
            error_file_count=status_counts[ParseStatus.ERROR],
        ),
        files=files,
        duplicates=duplicates,
        probable_version_groups=group_probable_versions(files),
        pii_findings=sorted(pii_findings, key=lambda finding: (finding.file_id, finding.start, finding.pii_type.value)),
        unreadable_sources=sorted(unreadable_sources, key=lambda item: item.relative_path),
        tables=sorted(tables, key=lambda table: (table.file_id, table.sheet_name)),
        live_llm=live_llm,
    )
