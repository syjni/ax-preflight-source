from __future__ import annotations

import json
from pathlib import Path

from ax_scanner.models import ScanReport


def write_report(report: ScanReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json_schema(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(ScanReport.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_report(path: Path) -> ScanReport:
    return ScanReport.model_validate_json(path.read_text(encoding="utf-8"))

