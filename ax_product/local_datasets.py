"""Persistent, local-only dataset onboarding for the reviewer console.

The browser sends a directory path to the FastAPI process running on the same
computer.  Source files are never copied.  A masked scanner report and a small
registry are stored under the configured local-audit root so the review can be
reopened after a restart.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from threading import RLock
from typing import Literal

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
DEFAULT_MAX_FILES = 5_000
DEFAULT_MAX_BYTES = 1_073_741_824  # 1 GiB
REGISTRY_SCHEMA = "ax-local-dataset-registry-v1"


class LocalDatasetError(ValueError):
    """A user-actionable local dataset registration error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LocalDatasetRequest(StrictProductModel):
    source_path: str = Field(min_length=1, max_length=2_048)
    display_name: str | None = Field(default=None, max_length=80)

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
    issue: str | None = None


class LocalDatasetIssue(StrictProductModel):
    code: Literal[
        "PARSE_ERROR",
        "UNSUPPORTED_FORMAT",
        "OCR_REQUIRED",
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
    dataset_name: str
    display_label: str
    source_root_name: str
    scanned_at: datetime
    as_of_date: date
    local_only: Literal[True] = True
    supported_extensions: list[str]
    file_count: int = Field(ge=0)
    parsed_file_count: int = Field(ge=0)
    unsupported_file_count: int = Field(ge=0)
    error_file_count: int = Field(ge=0)
    table_count: int = Field(ge=0)
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
    deleted: Literal[True] = True
    source_files_deleted: Literal[False] = False


class ProductCapabilities(StrictProductModel):
    schema_version: Literal["ax-product-capabilities-v1"] = (
        "ax-product-capabilities-v1"
    )
    mode: Literal["STATIC_DEMO", "API", "LOCAL_REVIEW", "LIVE"]
    local_dataset_scan: bool
    ai_task_execution: bool
    bundled_demo: bool
    source_files_stay_local: Literal[True] = True
    supported_extensions: list[str]


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

    def __init__(self, *, base_config: Path, root: Path):
        self.base_config = Path(base_config).resolve()
        self.root = Path(root).resolve()
        self.registry_path = self.root / "registry.json"
        self.config_path = self.root / "runtime_datasets.json"
        self._lock = RLock()
        self.max_files = _positive_limit(LOCAL_SCAN_MAX_FILES_ENV, DEFAULT_MAX_FILES)
        self.max_bytes = _positive_limit(LOCAL_SCAN_MAX_BYTES_ENV, DEFAULT_MAX_BYTES)
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._sync_runtime_config(self._registry())

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
        if source.is_relative_to(self.root) or self.root.is_relative_to(source):
            raise LocalDatasetError(
                "SOURCE_OVERLAPS_OUTPUT",
                "점검 폴더와 AX Preflight 결과 저장 폴더가 겹칩니다. 별도 문서 폴더를 선택하세요.",
            )
        return source

    def _preflight_files(self, source: Path) -> tuple[int, int]:
        count = 0
        total_bytes = 0
        try:
            for path in source.rglob("*"):
                if path.is_symlink():
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
                total_bytes += path.stat().st_size
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
    def _profile(source: Path) -> str:
        identity = os.path.normcase(str(source)).encode("utf-8")
        digest = hashlib.sha256(identity).hexdigest()[:10]
        slug = re.sub(r"[^a-z0-9]+", "-", source.name.casefold()).strip("-")
        return f"local-{(slug or 'dataset')[:28]}-{digest}"

    def scan(self, request: LocalDatasetRequest) -> str:
        source = self._normalize_source(request.source_path)
        self._preflight_files(source)
        profile = self._profile(source)
        display_name = request.display_name or source.name
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
            "source_root": str(source),
            "source_root_name": source.name,
            "scan_report": str(report_path),
            "scanned_at": scanned_at.isoformat(),
            "as_of_date": scanned_at.date().isoformat(),
        }
        with self._lock:
            registry = self._registry()
            registry["datasets"][profile] = entry
            _atomic_json(self.registry_path, registry)
            self._sync_runtime_config(registry)
        return profile

    def contains(self, profile: str) -> bool:
        with self._lock:
            return profile in self._registry()["datasets"]

    def _entry(self, profile: str) -> dict:
        with self._lock:
            entry = self._registry()["datasets"].get(profile)
        if entry is None:
            raise LocalDatasetError("LOCAL_DATASET_NOT_FOUND", "로컬 점검 결과를 찾을 수 없습니다.")
        return entry

    def options(self) -> list[DatasetOption]:
        with self._lock:
            entries = list(self._registry()["datasets"].items())
        entries.sort(key=lambda item: item[1]["scanned_at"], reverse=True)
        return [DatasetOption(
            profile=profile,
            dataset_name=entry["dataset_name"],
            display_label=entry["display_label"],
            origin="LOCAL",
            scanned_at=entry["scanned_at"],
            source_root_name=entry["source_root_name"],
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
            issues.append(LocalDatasetIssue(
                code="OCR_REQUIRED", severity="warning", count=len(ocr_ids),
                title="OCR이 필요한 PDF",
                action="텍스트 인식이 가능한 PDF로 변환하거나 OCR을 적용한 뒤 다시 점검하세요.",
                relative_paths=paths(ocr_ids),
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
            issue=item.parse_error,
        ) for item in report.files]
        return LocalDatasetAudit(
            profile=profile,
            dataset_name=entry["dataset_name"],
            display_label=entry["display_label"],
            source_root_name=entry["source_root_name"],
            scanned_at=datetime.fromisoformat(entry["scanned_at"]),
            as_of_date=date.fromisoformat(entry["as_of_date"]),
            supported_extensions=list(report.scan_metadata.supported_extensions),
            file_count=report.scan_metadata.file_count,
            parsed_file_count=report.scan_metadata.parsed_file_count,
            unsupported_file_count=report.scan_metadata.unsupported_file_count,
            error_file_count=report.scan_metadata.error_file_count,
            table_count=len(report.tables),
            duplicate_group_count=len(report.duplicates),
            probable_version_group_count=len(report.probable_version_groups),
            pii_finding_count=len(report.pii_findings),
            ocr_required_count=len(ocr_ids),
            issues=issues,
            files=files,
        )

    def delete(self, profile: str) -> LocalDatasetDeleteResult:
        with self._lock:
            registry = self._registry()
            if profile not in registry["datasets"]:
                raise LocalDatasetError(
                    "LOCAL_DATASET_NOT_FOUND", "로컬 점검 결과를 찾을 수 없습니다."
                )
            del registry["datasets"][profile]
            _atomic_json(self.registry_path, registry)
            self._sync_runtime_config(registry)
        generated = (self.root / profile).resolve()
        if not generated.is_relative_to(self.root) or generated == self.root:
            raise RuntimeError("refusing to delete a path outside the local dataset store")
        if generated.exists():
            shutil.rmtree(generated)
        return LocalDatasetDeleteResult(profile=profile)
