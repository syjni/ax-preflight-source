from __future__ import annotations

import argparse
import json
from pathlib import Path

from .reports import validate_report, write_json_schema, write_report
from .scanner import scan_folder
from .telemetry import detect_live_llm_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan a folder locally and write a deterministic AX scan report")
    parser.add_argument("directory", type=Path, help="Directory to scan recursively")
    parser.add_argument("--output", type=Path, default=Path("scan_report.json"), help="JSON report path")
    parser.add_argument("--schema-output", type=Path, help="Optional JSON Schema output path")
    parser.add_argument("--ocr-min-chars-per-page", type=int, default=20, help="PDF OCR-required threshold per page")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.ocr_min_chars_per_page < 1:
        raise SystemExit("--ocr-min-chars-per-page must be at least 1")
    output = args.output.resolve()
    exclusions = {output}
    if args.schema_output:
        exclusions.add(args.schema_output.resolve())
    report = scan_folder(
        args.directory,
        live_llm=detect_live_llm_status(),
        ocr_min_chars_per_page=args.ocr_min_chars_per_page,
        exclude_paths=exclusions,
    )
    write_report(report, output)
    validate_report(output)
    if args.schema_output:
        write_json_schema(args.schema_output.resolve())
    summary = {
        "output": str(output),
        "files": report.scan_metadata.file_count,
        "parsed": report.scan_metadata.parsed_file_count,
        "duplicates": len(report.duplicates),
        "version_groups": len(report.probable_version_groups),
        "pii_findings": len(report.pii_findings),
        "ocr_required": len(report.unreadable_sources),
        "tables": len(report.tables),
        "live_llm_status": report.live_llm.status,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0

