from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParseStatus(str, Enum):
    PARSED = "PARSED"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"


class DataType(str, Enum):
    EMPTY = "empty"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    STRING = "string"
    MIXED = "mixed"


class PIIType(str, Enum):
    RESIDENT_REGISTRATION_NUMBER = "resident_registration_number"
    PHONE = "phone"
    EMAIL = "email"
    ACCOUNT_NUMBER_CANDIDATE = "account_number_candidate"


class ColumnProfile(StrictModel):
    name: str
    inferred_type: DataType
    null_ratio: float = Field(ge=0.0, le=1.0)
    sample_values: list[Any] = Field(default_factory=list)


class TableProfile(StrictModel):
    table_id: str
    file_id: str
    sheet_name: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    column_names: list[str]
    columns: list[ColumnProfile]
    merged_cell_present: bool = False
    merged_ranges: list[str] = Field(default_factory=list)


class FileRecord(StrictModel):
    file_id: str = Field(pattern=r"^FILE_[0-9a-f]{16}$")
    relative_path: str
    filename: str
    extension: str
    size: int = Field(ge=0)
    modified_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parse_status: ParseStatus
    parser: str | None = None
    text: str = ""
    text_char_count: int = Field(ge=0)
    text_is_masked: bool = True
    pii_finding_count: int = Field(ge=0, default=0)
    parse_error: str | None = None
    parser_metadata: dict[str, Any] = Field(default_factory=dict)


class DuplicateGroup(StrictModel):
    duplicate_group_id: str
    sha256: str
    file_ids: list[str]
    relative_paths: list[str]
    copy_count: int = Field(ge=2)


class VersionCandidate(StrictModel):
    file_id: str
    relative_path: str
    signals: list[str]


class ProbableVersionGroup(StrictModel):
    version_group_id: str
    normalized_name: str
    candidates: list[VersionCandidate]


class PIIFinding(StrictModel):
    file_id: str
    pii_type: PIIType
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    match_length: int = Field(gt=0)
    masked_token: str


class UnreadableSource(StrictModel):
    file_id: str
    relative_path: str
    reason: str
    extracted_char_count: int = Field(ge=0)
    requires_ocr: bool


class LLMTaskTelemetry(StrictModel):
    task_id: str
    category: str
    provider: str
    model: str
    llm_call_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    errors: list[str] = Field(default_factory=list)


class LiveLLMStatus(StrictModel):
    status: Literal["LIVE_LLM_PENDING", "LIVE_LLM_AVAILABLE_NOT_RUN", "LIVE_LLM_COMPLETED", "LIVE_LLM_FAILED"]
    provider: str | None = None
    model: str | None = None
    reason: str
    tasks: list[LLMTaskTelemetry] = Field(default_factory=list)


class ScanMetadata(StrictModel):
    schema_version: str
    scanner_version: str
    source_root_name: str
    supported_extensions: list[str]
    ocr_min_chars_per_page: int = Field(ge=1)
    file_count: int = Field(ge=0)
    parsed_file_count: int = Field(ge=0)
    unsupported_file_count: int = Field(ge=0)
    error_file_count: int = Field(ge=0)
    local_only: bool = True
    llm_dependency_required: bool = False


class ScanReport(StrictModel):
    scan_metadata: ScanMetadata
    files: list[FileRecord]
    duplicates: list[DuplicateGroup]
    probable_version_groups: list[ProbableVersionGroup]
    pii_findings: list[PIIFinding]
    unreadable_sources: list[UnreadableSource]
    tables: list[TableProfile]
    live_llm: LiveLLMStatus
