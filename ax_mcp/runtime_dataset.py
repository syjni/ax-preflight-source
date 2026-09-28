from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ax_scanner.models import ParseStatus, ScanReport


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "runtime_datasets.json"
PROFILE_ENV = "AX_RUNTIME_DATASET"
CONFIG_ENV = "AX_RUNTIME_DATASET_CONFIG"
FORBIDDEN_RUNTIME_MARKERS = (
    "expected_answer",
    "primary_blocker",
    "required_sources",
    "tool_plan",
    "defect ground truth",
    "defect_ground_truth",
)


class RuntimeDatasetError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeDataset:
    profile: str
    dataset_name: str
    source_root: Path
    scan_report: Path
    dataset_manifest: Path | None
    config_path: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resolve_runtime_dataset(
    profile: str | None = None,
    config_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> RuntimeDataset:
    env = os.environ if environ is None else environ
    selected = profile or env.get(PROFILE_ENV)
    if not selected:
        raise RuntimeDatasetError(
            f"runtime dataset is not selected; set {PROFILE_ENV} or pass --dataset-profile"
        )
    configured_path = config_path or env.get(CONFIG_ENV) or DEFAULT_CONFIG
    configured = Path(configured_path)
    path = (
        configured.resolve()
        if configured.is_absolute()
        else (ROOT / configured).resolve()
    )
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeDatasetError(f"runtime dataset config not found: {path}") from exc
    if config.get("schema_version") != "ax-runtime-datasets-v1":
        raise RuntimeDatasetError(f"unsupported runtime dataset config schema: {config.get('schema_version')}")
    try:
        entry = config["profiles"][selected]
    except KeyError as exc:
        available = sorted(config.get("profiles", {}))
        raise RuntimeDatasetError(f"unknown runtime dataset profile {selected!r}; available={available}") from exc
    allowed = {"dataset_name", "source_root", "scan_report", "dataset_manifest"}
    if set(entry) != allowed:
        raise RuntimeDatasetError(f"runtime profile {selected!r} must contain exactly {sorted(allowed)}")
    base = path.parent
    source_root = (base / entry["source_root"]).resolve()
    scan_report = (base / entry["scan_report"]).resolve()
    manifest_value = entry["dataset_manifest"]
    manifest = None if manifest_value is None else (base / manifest_value).resolve()
    if not source_root.is_dir():
        raise RuntimeDatasetError(f"runtime source root is missing: {source_root}")
    if not scan_report.is_file():
        raise RuntimeDatasetError(f"runtime scan report is missing: {scan_report}")
    if manifest is not None and not manifest.is_file():
        raise RuntimeDatasetError(f"runtime dataset manifest is missing: {manifest}")
    return RuntimeDataset(
        profile=selected,
        dataset_name=str(entry["dataset_name"]),
        source_root=source_root,
        scan_report=scan_report,
        dataset_manifest=manifest,
        config_path=path,
    )


def _report(dataset: RuntimeDataset) -> ScanReport:
    return ScanReport.model_validate_json(dataset.scan_report.read_text(encoding="utf-8"))


def runtime_identity(dataset: RuntimeDataset) -> dict[str, Any]:
    report = _report(dataset)
    if report.scan_metadata.source_root_name != dataset.source_root.name:
        raise RuntimeDatasetError(
            "scan report/source root mismatch: "
            f"report={report.scan_metadata.source_root_name!r}, root={dataset.source_root.name!r}"
        )
    if report.scan_metadata.file_count != len(report.files):
        raise RuntimeDatasetError("scan report file count does not match its file registry")

    report_paths: dict[str, str] = {}
    for record in report.files:
        source = (dataset.source_root / record.relative_path).resolve()
        if not source.is_relative_to(dataset.source_root):
            raise RuntimeDatasetError(f"scan report path escapes source root: {record.relative_path}")
        if not source.is_file():
            raise RuntimeDatasetError(f"runtime source is missing: {record.relative_path}")
        digest = _sha256(source)
        if digest != record.sha256:
            raise RuntimeDatasetError(f"runtime source hash mismatch: {record.relative_path}")
        report_paths[record.relative_path] = digest

    manifest_hash = None
    if dataset.dataset_manifest is not None:
        manifest = json.loads(dataset.dataset_manifest.read_text(encoding="utf-8"))
        if manifest.get("dataset_id") != dataset.dataset_name:
            raise RuntimeDatasetError("runtime profile dataset name does not match dataset manifest")
        if Path(manifest.get("source_root", "")).name != dataset.source_root.name:
            raise RuntimeDatasetError("runtime source root does not match dataset manifest")
        manifest_paths = {entry["relative_path"]: entry["sha256"] for entry in manifest.get("files", [])}
        if manifest.get("file_count") != len(manifest_paths) or manifest_paths != report_paths:
            raise RuntimeDatasetError("dataset manifest and scan-report file registries do not match")
        manifest_hash = _sha256(dataset.dataset_manifest)

    search_records = [
        {
            "file_id": record.file_id,
            "relative_path": record.relative_path,
            "source_sha256": record.sha256,
            "text_sha256": hashlib.sha256(record.text.encode("utf-8")).hexdigest(),
        }
        for record in report.files
        if record.parse_status == ParseStatus.PARSED and record.text.strip()
    ]
    table_records = [
        {
            "table_id": table.table_id,
            "file_id": table.file_id,
            "sheet_name": table.sheet_name,
            "row_count": table.row_count,
            "column_names": table.column_names,
        }
        for table in report.tables
    ]
    return {
        "schema_version": "ax-runtime-identity-v1",
        "dataset_profile": dataset.profile,
        "dataset_name": dataset.dataset_name,
        "source_root_name": dataset.source_root.name,
        "dataset_manifest_sha256": manifest_hash,
        "file_count": report.scan_metadata.file_count,
        "parsed_file_count": report.scan_metadata.parsed_file_count,
        "scan_report_sha256": _sha256(dataset.scan_report),
        "search_index_document_count": len(search_records),
        "search_index_sha256": _canonical_sha256(search_records),
        "table_count": len(table_records),
        "table_registry_sha256": _canonical_sha256(table_records),
        "corpus_registry_sha256": _canonical_sha256(report_paths),
    }


def _resource_chunks(path: Path) -> list[str]:
    if zipfile.is_zipfile(path):
        chunks = []
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if not name.endswith("/"):
                    chunks.append(archive.read(name).decode("utf-8", errors="ignore"))
        return chunks
    return [path.read_bytes().decode("utf-8", errors="ignore")]


def validate_runtime_resource_leakage(dataset: RuntimeDataset) -> dict[str, Any]:
    runtime_paths = sorted(path for path in dataset.source_root.rglob("*") if path.is_file())
    runtime_paths.append(dataset.scan_report)
    if dataset.dataset_manifest is not None:
        runtime_paths.append(dataset.dataset_manifest)
    violations = []
    for path in runtime_paths:
        for chunk in _resource_chunks(path):
            folded = chunk.casefold()
            for marker in FORBIDDEN_RUNTIME_MARKERS:
                if marker.casefold() in folded:
                    violations.append({"path": str(path), "marker": marker})
    return {
        "passed": not violations,
        "runtime_resource_count": len(runtime_paths),
        "forbidden_markers": list(FORBIDDEN_RUNTIME_MARKERS),
        "violations": violations,
    }


def write_runtime_identity_receipt(path: str | Path, identity: dict[str, Any], leakage: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "ax-mcp-runtime-identity-receipt-v1",
        "passed": bool(leakage.get("passed")),
        "identity": identity,
        "runtime_leakage": leakage,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
