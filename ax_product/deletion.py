"""Durable, resumable deletion operations and retained receipts."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import Field

from .governance import DeletionOperationView
from .models import StrictProductModel


DeletionScope = Literal["PROJECT", "DATASET"]
FailureInjector = Callable[[str, str, str], None]
DELETION_ID = re.compile(r"^del_[a-f0-9]{32}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DeletionOperation(StrictProductModel):
    schema_version: Literal["ax-deletion-operation-record-v1"] = (
        "ax-deletion-operation-record-v1"
    )
    operation_id: str = Field(pattern=r"^del_[a-f0-9]{32}$")
    scope: DeletionScope
    requested_by: str
    project_id: str | None = None
    dataset_profile: str | None = None
    dataset_profiles: list[str] = Field(default_factory=list)
    project_name_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    purge_receipt_id: str | None = None
    status: Literal["REQUESTED", "PARTIAL_FAILURE", "COMPLETED"] = "REQUESTED"
    stages: list[str]
    completed_stages: list[str] = Field(default_factory=list)
    attempt_count: int = Field(default=0, ge=0)
    failure_code: str | None = None
    failure_detail: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @property
    def remaining_stages(self) -> list[str]:
        return [stage for stage in self.stages if stage not in self.completed_stages]


class DeletionOperationStore:
    """One atomic JSON receipt per operation, outside deletable project records."""

    def __init__(
        self, root: Path, *, failure_injector: FailureInjector | None = None
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.failure_injector = failure_injector
        self._lock = RLock()

    def _path(self, operation_id: str) -> Path:
        if not DELETION_ID.fullmatch(operation_id):
            raise ValueError("invalid deletion operation ID")
        return self.root / f"{operation_id}.json"

    def _write(self, operation: DeletionOperation) -> None:
        path = self._path(operation.operation_id)
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(
                operation.model_dump(mode="json"),
                stream,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)

    def create(
        self,
        *,
        scope: DeletionScope,
        requested_by: str,
        stages: Sequence[str],
        project_id: str | None,
        dataset_profile: str | None = None,
        dataset_profiles: Sequence[str] = (),
        project_name_digest: str | None = None,
        purge_receipt_id: str | None = None,
        counts: Mapping[str, int] | None = None,
    ) -> DeletionOperation:
        now = _now()
        operation = DeletionOperation(
            operation_id=f"del_{uuid4().hex}",
            scope=scope,
            requested_by=requested_by,
            project_id=project_id,
            dataset_profile=dataset_profile,
            dataset_profiles=list(dataset_profiles),
            project_name_digest=project_name_digest,
            purge_receipt_id=purge_receipt_id,
            stages=list(stages),
            counts=dict(counts or {}),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._write(operation)
        return operation

    def get(self, operation_id: str) -> DeletionOperation:
        with self._lock:
            try:
                return DeletionOperation.model_validate_json(
                    self._path(operation_id).read_text(encoding="utf-8")
                )
            except FileNotFoundError:
                raise KeyError(operation_id) from None

    def run(
        self,
        operation_id: str,
        callbacks: Mapping[str, Callable[[], None]],
    ) -> DeletionOperation:
        with self._lock:
            operation = self.get(operation_id)
            if operation.status == "COMPLETED":
                return operation
            operation.attempt_count += 1
            operation.status = "REQUESTED"
            operation.failure_code = None
            operation.failure_detail = None
            operation.updated_at = _now()
            self._write(operation)
            for stage in operation.remaining_stages:
                try:
                    if self.failure_injector is not None:
                        self.failure_injector(operation.operation_id, stage, "before")
                    callbacks[stage]()
                    if self.failure_injector is not None:
                        self.failure_injector(operation.operation_id, stage, "after")
                except Exception:
                    operation.status = "PARTIAL_FAILURE"
                    operation.failure_code = "DELETION_STAGE_FAILED"
                    operation.failure_detail = (
                        f"{stage} 단계를 완료하지 못했습니다. 같은 operation ID로 재시도하세요."
                    )
                    operation.updated_at = _now()
                    self._write(operation)
                    return operation
                operation.completed_stages.append(stage)
                operation.updated_at = _now()
                self._write(operation)
            operation.status = "COMPLETED"
            operation.completed_at = _now()
            operation.updated_at = operation.completed_at
            operation.failure_code = None
            operation.failure_detail = None
            self._write(operation)
            return operation

    @staticmethod
    def view(operation: DeletionOperation) -> DeletionOperationView:
        record_labels = {
            "AUDIT_REQUEST_RECORDED": "AUDIT_REQUEST_EVENT",
            "VALIDATED": "PRECONDITION_VALIDATION",
            "RUN_RESULTS_REMOVED": "WRITABLE_RUN_RESULTS",
            "BATCH_RESULTS_REMOVED": "BATCH_RESULTS",
            "MANAGED_DATA_REMOVED": "LOCAL_SCAN_AND_MANAGED_COPY",
            "ACCESS_RECORDS_REMOVED": "PROJECT_ACCESS_AND_CONTROL_RECORDS",
            "VERIFIED": "POST_DELETE_VERIFICATION",
        }
        return DeletionOperationView(
            operation_id=operation.operation_id,
            scope=operation.scope,
            project_id=operation.project_id,
            dataset_profile=operation.dataset_profile,
            deletion_status=(
                "COMPLETED" if operation.status == "COMPLETED" else "PARTIAL_FAILURE"
            ),
            completed_stages=operation.completed_stages,
            remaining_stages=operation.remaining_stages,
            remaining_records=[
                record_labels.get(stage, stage) for stage in operation.remaining_stages
            ],
            attempt_count=operation.attempt_count,
            failure_code=operation.failure_code,
            failure_detail=operation.failure_detail,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
            completed_at=operation.completed_at,
        )
