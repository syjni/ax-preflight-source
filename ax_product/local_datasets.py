"""Persistent, local-only dataset onboarding for the reviewer console.

Reviewers can either let the local API read an existing directory in place or
select files in the browser. Browser-selected files are copied only into a
managed directory on the same computer. Masked scanner reports and a small
registry are stored under the configured local-audit root so reviews can be
reopened after a restart.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator

from ax_scanner.models import ParseStatus, ScanReport
from ax_scanner.reports import write_report
from ax_scanner.scanner import scan_folder
from ax_scanner.telemetry import detect_live_llm_status
from readiness_score import calculate_readiness_score

from .console_contracts import DatasetOption, ReadinessResponse
from .models import StrictProductModel, UnscoredObservation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_DATASETS_ROOT = ROOT / "artifacts" / "local_datasets"
LOCAL_DATASETS_ROOT_ENV = "AX_PRODUCT_LOCAL_DATASETS_ROOT"
LOCAL_SCAN_MAX_FILES_ENV = "AX_PRODUCT_LOCAL_SCAN_MAX_FILES"
LOCAL_SCAN_MAX_BYTES_ENV = "AX_PRODUCT_LOCAL_SCAN_MAX_BYTES"
LOCAL_SCAN_MAX_FILE_BYTES_ENV = "AX_PRODUCT_LOCAL_SCAN_MAX_FILE_BYTES"
ALLOWED_SCAN_ROOTS_ENV = "AX_ALLOWED_SCAN_ROOTS"
DEFAULT_MAX_FILES = 5_000
DEFAULT_MAX_BYTES = 1_073_741_824  # 1 GiB
DEFAULT_MAX_FILE_BYTES = 104_857_600  # 100 MiB
REGISTRY_SCHEMA = "ax-local-dataset-registry-v1"


def _dataset_revision_fingerprint(report: ScanReport) -> str:
    """Hash the effective model-visible dataset boundary, not presentation metadata."""
    pii_by_file: dict[str, list[dict[str, object]]] = {}
    for finding in report.pii_findings:
        pii_by_file.setdefault(finding.file_id, []).append({
            "type": finding.pii_type.value,
            "start": finding.start,
            "end": finding.end,
            "masked_token": finding.masked_token,
        })
    unreadable_by_file = {
        item.file_id: {
            "reason": item.reason,
            "extracted_char_count": item.extracted_char_count,
            "requires_ocr": item.requires_ocr,
        }
        for item in report.unreadable_sources
    }
    boundary = {
        "revision_schema": "ax-dataset-revision-v1",
        "scanner_version": report.scan_metadata.scanner_version,
        "files": [
            {
                "relative_path": item.relative_path,
                "extension": item.extension,
                "size": item.size,
                "source_sha256": item.sha256,
                "parse_status": item.parse_status.value,
                "parser": item.parser,
                "parse_error": item.parse_error,
                "masked_text_sha256": hashlib.sha256(
                    item.text.encode("utf-8")
                ).hexdigest(),
                "text_is_masked": item.text_is_masked,
                "pii_findings": sorted(
                    pii_by_file.get(item.file_id, []),
                    key=lambda value: (
                        str(value["type"]), int(value["start"]), int(value["end"])
                    ),
                ),
                "unreadable": unreadable_by_file.get(item.file_id),
            }
            for item in sorted(report.files, key=lambda value: value.relative_path)
        ],
    }
    encoded = json.dumps(
        boundary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class LocalDatasetError(ValueError):
    """A user-actionable local dataset registration error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LocalDatasetRequest(StrictProductModel):
    source_path: str = Field(min_length=1, max_length=2_048)
    display_name: str | None = Field(default=None, max_length=80)
    project_id: str | None = Field(default=None, pattern=r"^prj_[a-f0-9]{32}$")

    @field_validator("source_path")
    @classmethod
    def trim_source_path(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("source_path must not be blank")
        return trimmed

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class LocalDatasetFile(StrictProductModel):
    relative_path: str
    extension: str
    size_bytes: int = Field(ge=0)
    modified_at: datetime
    parse_status: Literal["PARSED", "UNSUPPORTED", "ERROR"]
    parser: str | None = None
    text_char_count: int = Field(ge=0)
    pii_finding_count: int = Field(ge=0)
    requires_ocr: bool
    ocr_status: Literal[
        "NOT_APPLICABLE", "NOT_REQUIRED", "COMPLETED", "DISABLED",
        "UNAVAILABLE", "PAGE_LIMIT_EXCEEDED", "FAILED",
    ] = "NOT_APPLICABLE"
    ocr_page_count: int = Field(default=0, ge=0)
    ocr_mean_confidence: float | None = Field(default=None, ge=0, le=100)
    pdf_table_count: int = Field(default=0, ge=0)
    pdf_table_status: Literal["NOT_APPLICABLE", "COMPLETED", "ERROR"] = (
        "NOT_APPLICABLE"
    )
    issue: str | None = None


class LocalDatasetIssue(StrictProductModel):
    code: Literal[
        "PARSE_ERROR",
        "UNSUPPORTED_FORMAT",
        "OCR_REQUIRED",
        "PDF_TABLE_EXTRACTION_FAILED",
        "EXACT_DUPLICATE",
        "PROBABLE_VERSION_GROUP",
        "PII_PATTERN",
        "STALE_FILE",
    ]
    severity: Literal["info", "warning", "error"]
    count: int = Field(ge=1)
    title: str
    action: str
    relative_paths: list[str] = Field(default_factory=list)


class LocalDatasetAudit(StrictProductModel):
    schema_version: Literal["ax-local-dataset-audit-v1"] = (
        "ax-local-dataset-audit-v1"
    )
    profile: str
    revision_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_name: str
    display_label: str
    source_root_name: str
    scanned_at: datetime
    as_of_date: date
    local_only: Literal[True] = True
    source_mode: Literal["PATH", "UPLOAD"] = "PATH"
    source_files_copied: bool = False
    managed_copy_deleted_with_record: bool = False
    supported_extensions: list[str]
    file_count: int = Field(ge=0)
    parsed_file_count: int = Field(ge=0)
    unsupported_file_count: int = Field(ge=0)
    error_file_count: int = Field(ge=0)
    table_count: int = Field(ge=0)
    pdf_table_count: int = Field(default=0, ge=0)
    ocr_completed_file_count: int = Field(default=0, ge=0)
    duplicate_group_count: int = Field(ge=0)
    probable_version_group_count: int = Field(ge=0)
    pii_finding_count: int = Field(ge=0)
    ocr_required_count: int = Field(ge=0)
    issues: list[LocalDatasetIssue]
    files: list[LocalDatasetFile]


class LocalDatasetScanResult(StrictProductModel):
    schema_version: Literal["ax-local-dataset-scan-result-v1"] = (
        "ax-local-dataset-scan-result-v1"
    )
    dataset: DatasetOption
    audit: LocalDatasetAudit
    readiness: ReadinessResponse


class LocalDatasetDeleteResult(StrictProductModel):
    schema_version: Literal["ax-local-dataset-delete-result-v1"] = (
        "ax-local-dataset-delete-result-v1"
    )
    profile: str
    operation_id: str = Field(pattern=r"^del_[a-f0-9]{32}$")
    deletion_status: Literal["PARTIAL_FAILURE", "COMPLETED"]
    completed_stages: list[str]
    remaining_stages: list[str]
    remaining_records: list[str]
    attempt_count: int = Field(ge=1)
    failure_code: str | None = None
    failure_detail: str | None = None
    completed_at: datetime | None = None
    deleted: bool
    source_files_deleted: Literal[False] = False
    managed_copy_deleted: bool = False
    task_records_deleted: int = Field(default=0, ge=0)
    run_records_deleted: int = Field(default=0, ge=0)
    batch_records_deleted: int = Field(default=0, ge=0)


class ProductCapabilities(StrictProductModel):
    schema_version: Literal["ax-product-capabilities-v2"] = (
        "ax-product-capabilities-v2"
    )
    mode: Literal["STATIC_DEMO", "API", "LOCAL_REVIEW", "LIVE"]
    local_dataset_scan: bool
    local_file_upload: bool
    local_path_scan: bool
    ai_task_execution: bool
    bundled_demo: bool
    source_files_stay_local: Literal[True] = True
    supported_extensions: list[str]
    max_upload_files: int = Field(ge=1)
    max_upload_bytes: int = Field(ge=1)
    max_upload_file_bytes: int = Field(ge=1)
    pdf_table_extraction: bool = True
    ocr_available: bool
    ocr_engine: str | None = None
    ocr_languages: list[str] = Field(default_factory=list)
    ocr_install_hint: str | None = None


def _positive_limit(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def _allowed_scan_roots() -> tuple[Path, ...]:
    raw = os.environ.get(ALLOWED_SCAN_ROOTS_ENV, "").strip()
    if not raw:
        return ()
    if raw.startswith("["):
        try:
            values = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{ALLOWED_SCAN_ROOTS_ENV} must be a JSON array or an OS-separated path list"
            ) from exc
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise RuntimeError(f"{ALLOWED_SCAN_ROOTS_ENV} JSON value must be a string array")
    else:
        values = raw.split(os.pathsep)
    roots: list[Path] = []
    for value in values:
        if not value.strip():
            continue
        try:
            root = Path(os.path.expandvars(os.path.expanduser(value.strip()))).resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError(
                f"{ALLOWED_SCAN_ROOTS_ENV} contains an unavailable path: {value}"
            ) from exc
        if not root.is_dir():
            raise RuntimeError(f"{ALLOWED_SCAN_ROOTS_ENV} entries must be directories: {value}")
        roots.append(root)
    return tuple(dict.fromkeys(roots))


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _absolute_runtime_entry(entry: dict, base: Path) -> dict:
    def resolved(value: str | None) -> str | None:
        if value is None:
            return None
        candidate = Path(value)
        return str((candidate if candidate.is_absolute() else base / candidate).resolve())

    return {
        "dataset_name": str(entry["dataset_name"]),
        "source_root": resolved(entry["source_root"]),
        "scan_report": resolved(entry["scan_report"]),
        "dataset_manifest": resolved(entry["dataset_manifest"]),
    }


class LocalDatasetStore:
    """Own generated local reports and a merged runtime routing registry."""

    def __init__(
        self,
        *,
        base_config: Path,
        root: Path,
        allowed_scan_roots: Iterable[Path] | None = None,
    ):
        self.base_config = Path(base_config).resolve()
        self.root = Path(root).resolve()
        self.registry_path = self.root / "registry.json"
        self.config_path = self.root / "runtime_datasets.json"
        self.upload_root = self.root / "uploads"
        self._lock = RLock()
        self.max_files = _positive_limit(LOCAL_SCAN_MAX_FILES_ENV, DEFAULT_MAX_FILES)
        self.max_bytes = _positive_limit(LOCAL_SCAN_MAX_BYTES_ENV, DEFAULT_MAX_BYTES)
        self.max_file_bytes = _positive_limit(
            LOCAL_SCAN_MAX_FILE_BYTES_ENV, DEFAULT_MAX_FILE_BYTES
        )
        if self.max_file_bytes > self.max_bytes:
            self.max_file_bytes = self.max_bytes
        configured_roots = (
            _allowed_scan_roots()
            if allowed_scan_roots is None
            else tuple(Path(path).resolve(strict=True) for path in allowed_scan_roots)
        )
        self.allowed_scan_roots = tuple(dict.fromkeys(configured_roots))
        if any(not path.is_dir() for path in self.allowed_scan_roots):
            raise RuntimeError("allowed scan roots must be directories")
        self._protected_roots: set[Path] = {self.root}
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._sync_runtime_config(self._registry())

    @property
    def path_scan_enabled(self) -> bool:
        return bool(self.allowed_scan_roots)

    def protect_paths(self, paths: Iterable[Path | None]) -> None:
        for path in paths:
            if path is not None:
                self._protected_roots.add(Path(path).resolve())

    def _base_profiles(self) -> dict[str, dict]:
        try:
            payload = json.loads(self.base_config.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid base runtime dataset config: {self.base_config}") from exc
        if payload.get("schema_version") != "ax-runtime-datasets-v1":
            raise RuntimeError("unsupported base runtime dataset config schema")
        profiles = payload.get("profiles")
        if not isinstance(profiles, dict):
            raise RuntimeError("base runtime dataset config has no profiles")
        return {
            profile: _absolute_runtime_entry(entry, self.base_config.parent)
            for profile, entry in profiles.items()
        }

    def _registry(self) -> dict:
        if not self.registry_path.exists():
            return {"schema_version": REGISTRY_SCHEMA, "datasets": {}}
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid local dataset registry: {self.registry_path}") from exc
        if payload.get("schema_version") != REGISTRY_SCHEMA:
            raise RuntimeError("unsupported local dataset registry schema")
        if not isinstance(payload.get("datasets"), dict):
            raise RuntimeError("local dataset registry has no datasets mapping")
        return payload

    def _sync_runtime_config(self, registry: dict) -> None:
        profiles = self._base_profiles()
        for profile, entry in registry["datasets"].items():
            profiles[profile] = {
                "dataset_name": entry["dataset_name"],
                "source_root": entry["source_root"],
                "scan_report": entry["scan_report"],
                "dataset_manifest": None,
            }
        _atomic_json(self.config_path, {
            "schema_version": "ax-runtime-datasets-v1",
            "profiles": profiles,
        })

    def _normalize_source(self, source_text: str) -> Path:
        if not self.path_scan_enabled:
            raise LocalDatasetError(
                "PATH_SCAN_UNAVAILABLE",
                f"서버 경로 점검은 {ALLOWED_SCAN_ROOTS_ENV} 허용 루트를 설정한 경우에만 사용할 수 있습니다.",
            )
        unquoted = source_text.strip().strip('"').strip("'")
        expanded = os.path.expandvars(os.path.expanduser(unquoted))
        try:
            source = Path(expanded).resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise LocalDatasetError(
                "SOURCE_NOT_FOUND", "폴더를 찾을 수 없습니다. 전체 경로를 확인하세요."
            ) from exc
        if not source.is_dir():
            raise LocalDatasetError("SOURCE_NOT_DIRECTORY", "선택한 경로가 폴더가 아닙니다.")
        if source == Path(source.anchor):
            raise LocalDatasetError(
                "SOURCE_TOO_BROAD", "드라이브 전체 대신 점검할 문서 폴더를 선택하세요."
            )
        if not any(source.is_relative_to(root) for root in self.allowed_scan_roots):
            raise LocalDatasetError(
                "SOURCE_OUTSIDE_ALLOWED_ROOTS",
                "입력 경로가 서버에서 명시적으로 허용한 읽기 전용 루트 밖에 있습니다.",
            )
        if any(
            source.is_relative_to(root) or root.is_relative_to(source)
            for root in self._protected_roots
        ):
            raise LocalDatasetError(
                "SOURCE_OVERLAPS_OUTPUT",
                "점검 폴더가 AX Preflight 상태·실행·접근 제어 경로와 겹칩니다. 별도 문서 폴더를 선택하세요.",
            )
        return source

    def _preflight_files(self, source: Path) -> tuple[int, int]:
        count = 0
        total_bytes = 0
        try:
            for path in source.rglob("*"):
                if path.is_symlink() or (
                    hasattr(path, "is_junction") and path.is_junction()
                ):
                    raise LocalDatasetError(
                        "SYMLINK_NOT_ALLOWED",
                        f"심볼릭 링크는 점검 범위에서 허용하지 않습니다: {path.name}",
                    )
                if not path.is_file():
                    continue
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(source):
                    raise LocalDatasetError(
                        "SOURCE_PATH_ESCAPE", "점검 폴더 밖을 가리키는 파일이 있습니다."
                    )
                count += 1
                file_bytes = path.stat().st_size
                if file_bytes > self.max_file_bytes:
                    raise LocalDatasetError(
                        "FILE_SIZE_LIMIT_EXCEEDED",
                        f"개별 파일 {path.name}이 {self.max_file_bytes / 1_048_576:.1f} MiB를 초과합니다.",
                    )
                total_bytes += file_bytes
                if count > self.max_files:
                    raise LocalDatasetError(
                        "FILE_LIMIT_EXCEEDED",
                        f"파일이 {self.max_files:,}개를 초과합니다. 점검 범위를 나눠 주세요.",
                    )
                if total_bytes > self.max_bytes:
                    raise LocalDatasetError(
                        "SIZE_LIMIT_EXCEEDED",
                        f"전체 파일 크기가 {self.max_bytes / 1_073_741_824:.1f} GiB를 초과합니다.",
                    )
        except PermissionError as exc:
            raise LocalDatasetError(
                "SOURCE_PERMISSION_DENIED",
                f"읽을 수 없는 경로가 있습니다: {exc.filename or source}",
            ) from exc
        return count, total_bytes

    @staticmethod
    def _profile(source: Path, project_id: str | None) -> str:
        identity = f"{project_id or 'unassigned'}\0{os.path.normcase(str(source))}".encode("utf-8")
        digest = hashlib.sha256(identity).hexdigest()[:10]
        slug = re.sub(r"[^a-z0-9]+", "-", source.name.casefold()).strip("-")
        return f"local-{(slug or 'dataset')[:28]}-{digest}"

    def _scan_source(
        self,
        source: Path,
        *,
        display_name: str,
        source_root_name: str,
        source_mode: Literal["PATH", "UPLOAD"],
        project_id: str | None,
    ) -> str:
        self._preflight_files(source)
        profile = self._profile(source, project_id)
        scanned_at = datetime.now().astimezone()
        report = scan_folder(source, live_llm=detect_live_llm_status())
        target_dir = self.root / profile
        target_dir.mkdir(parents=True, exist_ok=True)
        report_path = target_dir / "scan-report.json"
        temporary = target_dir / ".scan-report.tmp"
        write_report(report, temporary)
        temporary.replace(report_path)
        entry = {
            "dataset_name": f"{source.name}-local-{profile[-10:]}",
            "display_label": f"내 자료 · {display_name}",
            "revision_fingerprint": _dataset_revision_fingerprint(report),
            "source_root": str(source),
            "source_root_name": source_root_name,
            "source_mode": source_mode,
            "scan_report": str(report_path),
            "scanned_at": scanned_at.isoformat(),
            "as_of_date": scanned_at.date().isoformat(),
            "project_id": project_id,
        }
        with self._lock:
            registry = self._registry()
            registry["datasets"][profile] = entry
            _atomic_json(self.registry_path, registry)
            self._sync_runtime_config(registry)
        return profile

    def scan(self, request: LocalDatasetRequest) -> str:
        source = self._normalize_source(request.source_path)
        with self._lock:
            for entry in self._registry()["datasets"].values():
                if entry.get("source_mode") != "PATH":
                    continue
                try:
                    registered_source = Path(entry["source_root"]).resolve(strict=True)
                except (KeyError, FileNotFoundError, OSError):
                    continue
                if (
                    registered_source == source
                    and entry.get("project_id") != request.project_id
                ):
                    raise LocalDatasetError(
                        "SOURCE_ASSIGNED_TO_OTHER_PROJECT",
                        "이 원본 경로는 다른 프로젝트가 사용 중이므로 현재 프로젝트에서 점검할 수 없습니다.",
                    )
        return self._scan_source(
            source,
            display_name=request.display_name or source.name,
            source_root_name=source.name,
            source_mode="PATH",
            project_id=request.project_id,
        )

    @staticmethod
    def _upload_path(value: str) -> PurePosixPath:
        normalized = unicodedata.normalize("NFC", value.strip())
        path = PurePosixPath(normalized)
        if (
            not normalized
            or "\\" in normalized
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(":" in part or "\0" in part for part in path.parts)
        ):
            raise LocalDatasetError(
                "INVALID_UPLOAD_PATH", "선택한 파일 중 안전하지 않은 상대 경로가 있습니다."
            )
        return path

    def prepare_upload(self, relative_paths: list[str]) -> tuple[Path, list[Path]]:
        if not relative_paths:
            raise LocalDatasetError("EMPTY_UPLOAD", "점검할 파일을 하나 이상 선택하세요.")
        if len(relative_paths) > self.max_files:
            raise LocalDatasetError(
                "FILE_LIMIT_EXCEEDED",
                f"파일이 {self.max_files:,}개를 초과합니다. 점검 범위를 나눠 주세요.",
            )
        parsed = [self._upload_path(value) for value in relative_paths]
        folded = [path.as_posix().casefold() for path in parsed]
        if len(set(folded)) != len(folded):
            raise LocalDatasetError(
                "DUPLICATE_UPLOAD_PATH", "같은 상대 경로의 파일이 두 번 선택되었습니다."
            )
        upload_root = (self.upload_root / f"upload-{uuid4().hex}").resolve()
        if not upload_root.is_relative_to(self.upload_root.resolve()):
            raise RuntimeError("refusing to allocate an upload outside the managed root")
        upload_root.mkdir(parents=True, exist_ok=False)
        destinations = []
        for relative in parsed:
            destination = (upload_root / Path(*relative.parts)).resolve()
            if not destination.is_relative_to(upload_root):
                self.discard_upload(upload_root)
                raise LocalDatasetError(
                    "INVALID_UPLOAD_PATH", "선택한 파일 경로가 허용 범위를 벗어납니다."
                )
            destinations.append(destination)
        return upload_root, destinations

    def discard_upload(self, upload_root: Path) -> None:
        candidate = Path(upload_root).resolve()
        managed_root = self.upload_root.resolve()
        if candidate == managed_root or not candidate.is_relative_to(managed_root):
            raise RuntimeError("refusing to delete an unmanaged upload path")
        if candidate.exists():
            shutil.rmtree(candidate)

    def scan_upload(
        self,
        upload_root: Path,
        *,
        display_name: str | None,
        source_root_name: str | None,
        project_id: str | None = None,
    ) -> str:
        source = Path(upload_root).resolve()
        if not source.is_relative_to(self.upload_root.resolve()):
            raise LocalDatasetError("INVALID_UPLOAD_ROOT", "관리되지 않는 업로드 경로입니다.")
        root_label = (source_root_name or "선택한 파일").strip()[:120] or "선택한 파일"
        return self._scan_source(
            source,
            display_name=(display_name or root_label).strip()[:80] or root_label,
            source_root_name=root_label,
            source_mode="UPLOAD",
            project_id=project_id,
        )

    def contains(self, profile: str) -> bool:
        with self._lock:
            return profile in self._registry()["datasets"]

    def _entry(self, profile: str) -> dict:
        with self._lock:
            entry = self._registry()["datasets"].get(profile)
        if entry is None:
            raise LocalDatasetError("LOCAL_DATASET_NOT_FOUND", "로컬 점검 결과를 찾을 수 없습니다.")
        return entry

    def project_id(self, profile: str) -> str | None:
        return self._entry(profile).get("project_id")

    def managed_copy(self, profile: str) -> bool:
        return self._entry(profile).get("source_mode") == "UPLOAD"

    def revision_fingerprint(self, profile: str) -> str:
        entry = self._entry(profile)
        fingerprint = entry.get("revision_fingerprint")
        if isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            return fingerprint
        # Registries created before revision binding are upgraded deterministically
        # from their persisted scan report. Presentation labels and scan timestamps
        # are deliberately excluded from this boundary identity.
        fingerprint = _dataset_revision_fingerprint(self.report(profile))
        with self._lock:
            registry = self._registry()
            current = registry["datasets"].get(profile)
            if current is None:
                raise LocalDatasetError(
                    "LOCAL_DATASET_NOT_FOUND", "로컬 점검 결과를 찾을 수 없습니다."
                )
            current["revision_fingerprint"] = fingerprint
            _atomic_json(self.registry_path, registry)
        return fingerprint

    def project_records(self, project_id: str) -> list[tuple[str, bool]]:
        """Return profile and managed-copy ownership without exposing source paths."""
        with self._lock:
            entries = list(self._registry()["datasets"].items())
        return [
            (profile, entry.get("source_mode") == "UPLOAD")
            for profile, entry in entries
            if entry.get("project_id") == project_id
        ]

    def options(self, project_ids: set[str] | None = None) -> list[DatasetOption]:
        with self._lock:
            entries = list(self._registry()["datasets"].items())
        if project_ids is not None:
            entries = [item for item in entries if item[1].get("project_id") in project_ids]
        entries.sort(key=lambda item: item[1]["scanned_at"], reverse=True)
        return [DatasetOption(
            profile=profile,
            dataset_name=entry["dataset_name"],
            display_label=entry["display_label"],
            origin="LOCAL",
            scanned_at=entry["scanned_at"],
            source_root_name=entry["source_root_name"],
            project_id=entry.get("project_id"),
        ) for profile, entry in entries]

    def option(self, profile: str) -> DatasetOption:
        entry = self._entry(profile)
        return DatasetOption(
            profile=profile,
            dataset_name=entry["dataset_name"],
            display_label=entry["display_label"],
            origin="LOCAL",
            scanned_at=entry["scanned_at"],
            source_root_name=entry["source_root_name"],
            project_id=entry.get("project_id"),
        )

    def as_of_date(self, profile: str) -> date | None:
        if not self.contains(profile):
            return None
        return date.fromisoformat(self._entry(profile)["as_of_date"])

    def report(self, profile: str) -> ScanReport:
        entry = self._entry(profile)
        try:
            return ScanReport.model_validate_json(
                Path(entry["scan_report"]).read_text(encoding="utf-8")
            )
        except (FileNotFoundError, ValueError) as exc:
            raise LocalDatasetError(
                "LOCAL_REPORT_UNAVAILABLE", "저장된 로컬 점검 보고서를 읽을 수 없습니다. 다시 점검하세요."
            ) from exc

    def readiness(self, profile: str) -> ReadinessResponse:
        report = self.report(profile)
        entry = self._entry(profile)
        observations = [UnscoredObservation(
            code="PROBABLE_VERSION_GROUP",
            severity="warning",
            message=f"Probable version group {group.normalized_name}: {len(group.candidates)} candidates",
            file_ids=[candidate.file_id for candidate in group.candidates],
        ) for group in report.probable_version_groups]
        return ReadinessResponse(
            dataset=profile,
            dataset_name=entry["dataset_name"],
            readiness=calculate_readiness_score(
                report, as_of_date=date.fromisoformat(entry["as_of_date"])
            ),
            unscored_observations=observations,
        )

    def audit(self, profile: str) -> LocalDatasetAudit:
        entry = self._entry(profile)
        report = self.report(profile)
        readiness = self.readiness(profile).readiness
        ocr_ids = {item.file_id for item in report.unreadable_sources if item.requires_ocr}
        pii_ids = {item.file_id for item in report.pii_findings}
        paths_by_id = {item.file_id: item.relative_path for item in report.files}

        def paths(file_ids: set[str]) -> list[str]:
            return sorted(paths_by_id[item] for item in file_ids if item in paths_by_id)

        issues: list[LocalDatasetIssue] = []
        parse_errors = [
            item.relative_path
            for item in report.files
            if item.parse_status == ParseStatus.ERROR
        ]
        unsupported = [
            item.relative_path
            for item in report.files
            if item.parse_status == ParseStatus.UNSUPPORTED
        ]
        if parse_errors:
            issues.append(LocalDatasetIssue(
                code="PARSE_ERROR", severity="error", count=len(parse_errors),
                title="읽지 못한 파일",
                action="손상 여부와 파일 권한을 확인한 뒤 다시 점검하세요.",
                relative_paths=parse_errors,
            ))
        if unsupported:
            issues.append(LocalDatasetIssue(
                code="UNSUPPORTED_FORMAT", severity="warning", count=len(unsupported),
                title="지원하지 않는 형식",
                action="PDF·DOCX·XLSX·CSV·TXT 중 하나로 변환하거나 점검 범위에서 분리하세요.",
                relative_paths=unsupported,
            ))
        if ocr_ids:
            ocr_statuses = {
                str(item.parser_metadata.get("ocr_status", "UNAVAILABLE"))
                for item in report.files if item.file_id in ocr_ids
            }
            issues.append(LocalDatasetIssue(
                code="OCR_REQUIRED", severity="warning", count=len(ocr_ids),
                title="OCR이 필요한 PDF",
                action=(
                    "Docker 실행을 사용하거나 Tesseract OCR과 kor·eng 언어팩을 설치한 뒤 다시 점검하세요."
                    if "UNAVAILABLE" in ocr_statuses
                    else "OCR 페이지 한도와 파일 품질을 확인한 뒤 다시 점검하세요."
                ),
                relative_paths=paths(ocr_ids),
            ))
        pdf_table_errors = [
            item.relative_path
            for item in report.files
            if item.extension == ".pdf"
            and item.parser_metadata.get("pdf_table_extraction_status") == "ERROR"
        ]
        if pdf_table_errors:
            issues.append(LocalDatasetIssue(
                code="PDF_TABLE_EXTRACTION_FAILED", severity="warning",
                count=len(pdf_table_errors), title="PDF 표 구조를 읽지 못한 파일",
                action="표가 이미지이거나 선이 없는 복잡한 배치인지 확인하고 XLSX·CSV 원본이 있으면 함께 점검하세요.",
                relative_paths=pdf_table_errors,
            ))
        if report.duplicates:
            duplicate_paths = sorted({path for group in report.duplicates for path in group.relative_paths})
            issues.append(LocalDatasetIssue(
                code="EXACT_DUPLICATE", severity="warning", count=len(report.duplicates),
                title="완전히 같은 파일 묶음",
                action="대표 파일 하나를 정하고 나머지는 보관·폐기 상태를 표시하세요.",
                relative_paths=duplicate_paths,
            ))
        if report.probable_version_groups:
            version_paths = sorted({
                candidate.relative_path
                for group in report.probable_version_groups
                for candidate in group.candidates
            })
            issues.append(LocalDatasetIssue(
                code="PROBABLE_VERSION_GROUP", severity="warning",
                count=len(report.probable_version_groups), title="여러 버전으로 보이는 파일",
                action="현행본을 지정하고 이전 버전에 폐기·대체 표시를 추가하세요.",
                relative_paths=version_paths,
            ))
        if pii_ids:
            issues.append(LocalDatasetIssue(
                code="PII_PATTERN", severity="warning", count=len(report.pii_findings),
                title="개인정보 가능 패턴",
                action="실제 개인정보인지 확인하고 마스킹·접근 권한·보존 범위를 검토하세요.",
                relative_paths=paths(pii_ids),
            ))
        stale_count = readiness.counts.timeliness.stale_files
        if stale_count:
            as_of = date.fromisoformat(entry["as_of_date"])
            stale_ids = {
                item.file_id
                for item in report.files
                if (as_of - item.modified_at.date()).days
                > readiness.stale_threshold_days
            }
            issues.append(LocalDatasetIssue(
                code="STALE_FILE", severity="info", count=stale_count,
                title="최신성 확인이 필요한 파일",
                action="현행 기준인지 담당자와 확인하고 수정일 또는 유효기간을 갱신하세요.",
                relative_paths=paths(stale_ids),
            ))

        files = [LocalDatasetFile(
            relative_path=item.relative_path,
            extension=item.extension,
            size_bytes=item.size,
            modified_at=item.modified_at,
            parse_status=item.parse_status.value,
            parser=item.parser,
            text_char_count=item.text_char_count,
            pii_finding_count=item.pii_finding_count,
            requires_ocr=item.file_id in ocr_ids,
            ocr_status=(
                str(item.parser_metadata.get("ocr_status", "NOT_REQUIRED"))
                if item.extension == ".pdf" else "NOT_APPLICABLE"
            ),
            ocr_page_count=len(item.parser_metadata.get("ocr_processed_page_numbers", [])),
            ocr_mean_confidence=item.parser_metadata.get("ocr_mean_confidence"),
            pdf_table_count=int(item.parser_metadata.get("pdf_table_count", 0)),
            pdf_table_status=(
                str(item.parser_metadata.get("pdf_table_extraction_status", "COMPLETED"))
                if item.extension == ".pdf" else "NOT_APPLICABLE"
            ),
            issue=item.parse_error,
        ) for item in report.files]
        pdf_table_count = sum(file.pdf_table_count for file in files)
        return LocalDatasetAudit(
            profile=profile,
            revision_fingerprint=self.revision_fingerprint(profile),
            dataset_name=entry["dataset_name"],
            display_label=entry["display_label"],
            source_root_name=entry["source_root_name"],
            scanned_at=datetime.fromisoformat(entry["scanned_at"]),
            as_of_date=date.fromisoformat(entry["as_of_date"]),
            source_mode=entry.get("source_mode", "PATH"),
            source_files_copied=entry.get("source_mode", "PATH") == "UPLOAD",
            managed_copy_deleted_with_record=entry.get("source_mode", "PATH") == "UPLOAD",
            supported_extensions=list(report.scan_metadata.supported_extensions),
            file_count=report.scan_metadata.file_count,
            parsed_file_count=report.scan_metadata.parsed_file_count,
            unsupported_file_count=report.scan_metadata.unsupported_file_count,
            error_file_count=report.scan_metadata.error_file_count,
            table_count=len(report.tables),
            pdf_table_count=pdf_table_count,
            ocr_completed_file_count=sum(file.ocr_status == "COMPLETED" for file in files),
            duplicate_group_count=len(report.duplicates),
            probable_version_group_count=len(report.probable_version_groups),
            pii_finding_count=len(report.pii_findings),
            ocr_required_count=len(ocr_ids),
            issues=issues,
            files=files,
        )

    def delete(self, profile: str, *, missing_ok: bool = False) -> bool:
        with self._lock:
            registry = self._registry()
            entry = registry["datasets"].get(profile)
            if entry is None:
                if missing_ok:
                    return False
                raise LocalDatasetError(
                    "LOCAL_DATASET_NOT_FOUND", "로컬 점검 결과를 찾을 수 없습니다."
                )
            generated = (self.root / profile).resolve()
            if not generated.is_relative_to(self.root) or generated == self.root:
                raise RuntimeError(
                    "refusing to delete a path outside the local dataset store"
                )
            # Remove managed data before hiding its registry record. If an I/O
            # error occurs, the visible record remains so the reviewer can retry
            # deletion instead of leaving an undiscoverable local copy behind.
            if generated.exists():
                shutil.rmtree(generated)
            if entry.get("source_mode") == "UPLOAD":
                self.discard_upload(Path(entry["source_root"]))
            del registry["datasets"][profile]
            _atomic_json(self.registry_path, registry)
            self._sync_runtime_config(registry)
        return entry.get("source_mode") == "UPLOAD"
