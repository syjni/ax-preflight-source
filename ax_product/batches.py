"""Persistent, bounded orchestration for repeated AX product runs."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from .models import DeliveryEnvelope, StrictProductModel


BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
DEFAULT_BATCH_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "product_batches"
ACTIVE_BATCH_STATES = {
    "QUEUED", "RUNNING", "PAUSE_REQUESTED", "CANCEL_REQUESTED",
}
TERMINAL_BATCH_STATES = {"COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED"}

BatchState = Literal[
    "QUEUED", "RUNNING", "PAUSE_REQUESTED", "PAUSED",
    "CANCEL_REQUESTED", "CANCELLED", "COMPLETED", "COMPLETED_WITH_ERRORS",
]
BatchControl = Literal["RUN", "PAUSE", "CANCEL"]
BatchItemState = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class BatchTaskInput(StrictProductModel):
    task_id: str = Field(min_length=1)
    request_type: Literal["VERIFIED_BUSINESS_TASK", "TASK_CANDIDATE"]
    question: str | None = None

    @model_validator(mode="after")
    def validate_request_shape(self) -> "BatchTaskInput":
        if not self.task_id.strip() or self.task_id != self.task_id.strip():
            raise ValueError("task_id must be nonblank and unpadded")
        if self.request_type == "VERIFIED_BUSINESS_TASK":
            if self.question is not None:
                raise ValueError("verified batch tasks forbid question")
        elif self.question is None or not self.question.strip():
            raise ValueError("candidate batch tasks require question")
        elif self.question != self.question.strip():
            raise ValueError("question must be unpadded")
        return self


class BatchCreateRequest(StrictProductModel):
    dataset: str = Field(min_length=1)
    tasks: list[BatchTaskInput] = Field(min_length=1, max_length=10)
    repetitions: int = Field(default=3, ge=1, le=5)
    max_attempts: int = Field(default=2, ge=1, le=3)
    model: str = Field(default="claude-sonnet-5", min_length=1)
    batch_id: str | None = None

    @model_validator(mode="after")
    def validate_batch(self) -> "BatchCreateRequest":
        for name in ("dataset", "model"):
            value = getattr(self, name)
            if not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be nonblank and unpadded")
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("batch tasks must have unique task_id values")
        if self.batch_id is not None and not BATCH_ID_PATTERN.fullmatch(self.batch_id):
            raise ValueError(
                "batch_id must be 1-64 ASCII letters, digits, _ or -, "
                "starting with a letter or digit"
            )
        return self


class BatchItem(StrictProductModel):
    item_id: str = Field(pattern=r"^t\d{2}-r\d{2}$")
    task_id: str = Field(min_length=1)
    task_label: str = Field(min_length=1)
    request_type: Literal["VERIFIED_BUSINESS_TASK", "TASK_CANDIDATE"]
    repetition: int = Field(ge=1, le=5)
    attempt: int = Field(ge=1, le=3)
    status: BatchItemState
    run_id: str | None = None
    error_code: str | None = None
    delivery_status: Literal["DELIVERED", "REJECTED"] | None = None


class BatchStatus(StrictProductModel):
    schema_version: Literal["ax-batch-status-v1"] = "ax-batch-status-v1"
    batch_id: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    model: str = Field(min_length=1)
    project_id: str | None = None
    requested_by_user_id: str | None = None
    state: BatchState
    requested_control: BatchControl
    repetitions: int = Field(ge=1, le=5)
    max_attempts: int = Field(ge=1, le=3)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    total_items: int = Field(ge=1, le=50)
    completed_items: int = Field(ge=0)
    succeeded_items: int = Field(ge=0)
    failed_items: int = Field(ge=0)
    cancelled_items: int = Field(ge=0)
    running_items: int = Field(ge=0)
    queued_items: int = Field(ge=0)
    progress_percent: int = Field(ge=0, le=100)
    items: list[BatchItem] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_summary(self) -> "BatchStatus":
        if (self.project_id is None) != (self.requested_by_user_id is None):
            raise ValueError("project_id and requested_by_user_id must be set together")
        counts = {
            "succeeded_items": sum(item.status == "SUCCEEDED" for item in self.items),
            "failed_items": sum(item.status == "FAILED" for item in self.items),
            "cancelled_items": sum(item.status == "CANCELLED" for item in self.items),
            "running_items": sum(item.status == "RUNNING" for item in self.items),
            "queued_items": sum(item.status == "QUEUED" for item in self.items),
        }
        counts["completed_items"] = (
            counts["succeeded_items"] + counts["failed_items"]
            + counts["cancelled_items"]
        )
        if self.total_items != len(self.items):
            raise ValueError("total_items must equal item count")
        for name, expected in counts.items():
            if getattr(self, name) != expected:
                raise ValueError(f"{name} does not match item states")
        expected_progress = counts["completed_items"] * 100 // self.total_items
        if self.progress_percent != expected_progress:
            raise ValueError("progress_percent does not match completed items")
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("batch item_id values must be unique")
        return self


def _summarized(batch: BatchStatus, **updates: object) -> BatchStatus:
    data = batch.model_dump(mode="python")
    data.update(updates)
    items = data["items"]
    assert isinstance(items, list)
    statuses = [item.status if isinstance(item, BatchItem) else item["status"] for item in items]
    succeeded = statuses.count("SUCCEEDED")
    failed = statuses.count("FAILED")
    cancelled = statuses.count("CANCELLED")
    completed = succeeded + failed + cancelled
    data.update({
        "updated_at": _now(),
        "total_items": len(items),
        "completed_items": completed,
        "succeeded_items": succeeded,
        "failed_items": failed,
        "cancelled_items": cancelled,
        "running_items": statuses.count("RUNNING"),
        "queued_items": statuses.count("QUEUED"),
        "progress_percent": completed * 100 // len(items),
    })
    return BatchStatus.model_validate(data)


def _terminal_state(batch: BatchStatus) -> BatchState:
    if batch.failed_items:
        return "COMPLETED_WITH_ERRORS"
    if batch.cancelled_items:
        return "CANCELLED"
    return "COMPLETED"


class DuplicateBatchError(ValueError):
    pass


class BatchStateError(ValueError):
    pass


class BatchStore:
    def __init__(self, root: str | Path = DEFAULT_BATCH_ROOT) -> None:
        self.root = Path(root).resolve()

    def path(self, batch_id: str) -> Path:
        if not BATCH_ID_PATTERN.fullmatch(batch_id):
            raise ValueError("invalid batch_id")
        return self.root / batch_id / "batch.json"

    def create(self, batch: BatchStatus) -> None:
        path = self.path(batch.batch_id)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary_dir = self.root / f".{uuid4().hex}.tmp"
        temporary_dir.mkdir()
        try:
            self._write_json(temporary_dir / "batch.json", batch, replace=False)
            try:
                temporary_dir.rename(path.parent)
            except OSError as exc:
                if path.parent.exists():
                    raise DuplicateBatchError(batch.batch_id) from exc
                raise
        finally:
            if temporary_dir.exists():
                (temporary_dir / "batch.json").unlink(missing_ok=True)
                temporary_dir.rmdir()

    def read(self, batch_id: str) -> BatchStatus:
        return BatchStatus.model_validate_json(
            self.path(batch_id).read_text(encoding="utf-8")
        )

    def write(self, batch: BatchStatus) -> None:
        path = self.path(batch.batch_id)
        if not path.parent.is_dir():
            raise FileNotFoundError(batch.batch_id)
        self._write_json(path, batch, replace=True)

    def records(self) -> list[BatchStatus]:
        if not self.root.is_dir():
            return []
        records = []
        for directory in sorted(self.root.iterdir()):
            if directory.is_dir() and not directory.name.startswith("."):
                records.append(self.read(directory.name))
        return records

    def inventory_for_datasets(self, datasets: set[str]) -> tuple[int, int]:
        selected = [record for record in self.records() if record.dataset in datasets]
        active = sum(record.state not in TERMINAL_BATCH_STATES for record in selected)
        return len(selected), active

    def delete_for_datasets(self, datasets: set[str]) -> int:
        selected = [record for record in self.records() if record.dataset in datasets]
        active = next(
            (record for record in selected if record.state not in TERMINAL_BATCH_STATES),
            None,
        )
        if active is not None:
            raise BatchStateError(
                f"batch {active.batch_id} must reach a terminal state before deletion"
            )
        deleted = 0
        for record in selected:
            directory = self.path(record.batch_id).parent.resolve()
            if not directory.is_relative_to(self.root) or directory == self.root:
                raise RuntimeError("refusing to delete a batch outside the batch store")
            shutil.rmtree(directory)
            deleted += 1
        return deleted

    @staticmethod
    def _write_json(path: Path, batch: BatchStatus, *, replace: bool) -> None:
        temporary = path.parent / f".{uuid4().hex}.tmp"
        target = temporary if replace else path
        try:
            with target.open("x", encoding="utf-8", newline="\n") as output:
                json.dump(
                    batch.model_dump(mode="json"), output,
                    ensure_ascii=False, sort_keys=True,
                )
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            if replace:
                os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


BatchExecutor = Callable[[BatchStatus, BatchItem, str], DeliveryEnvelope]


class BatchManager:
    """Single-process scheduler with durable state and safe control points."""

    def __init__(
        self, store: BatchStore, executor: BatchExecutor, *, recover: bool = True
    ) -> None:
        self.store = store
        self.executor = executor
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._workers: dict[str, threading.Thread] = {}
        if recover:
            self._recover_interrupted()

    def create(
        self,
        request: BatchCreateRequest,
        resolved_questions: dict[str, str],
        *,
        project_id: str | None = None,
        requested_by_user_id: str | None = None,
    ) -> BatchStatus:
        batch_id = request.batch_id or f"batch-{uuid4().hex[:16]}"
        items = []
        for task_index, task in enumerate(request.tasks, start=1):
            for repetition in range(1, request.repetitions + 1):
                items.append(BatchItem(
                    item_id=f"t{task_index:02d}-r{repetition:02d}",
                    task_id=task.task_id,
                    task_label=resolved_questions[task.task_id],
                    request_type=task.request_type,
                    repetition=repetition,
                    attempt=1,
                    status="QUEUED",
                ))
        created_at = _now()
        batch = BatchStatus(
            batch_id=batch_id,
            dataset=request.dataset,
            model=request.model,
            project_id=project_id,
            requested_by_user_id=requested_by_user_id,
            state="QUEUED",
            requested_control="RUN",
            repetitions=request.repetitions,
            max_attempts=request.max_attempts,
            created_at=created_at,
            updated_at=created_at,
            total_items=len(items),
            completed_items=0,
            succeeded_items=0,
            failed_items=0,
            cancelled_items=0,
            running_items=0,
            queued_items=len(items),
            progress_percent=0,
            items=items,
        )
        self.store.create(batch)
        with self._condition:
            self._start_worker_locked(batch_id)
        return self.store.read(batch_id)

    def read(self, batch_id: str) -> BatchStatus:
        with self._lock:
            return self.store.read(batch_id)

    def pause(self, batch_id: str) -> BatchStatus:
        with self._condition:
            batch = self.store.read(batch_id)
            if batch.state not in {"QUEUED", "RUNNING"}:
                raise BatchStateError("BATCH_NOT_PAUSABLE")
            batch = _summarized(
                batch, state="PAUSE_REQUESTED", requested_control="PAUSE"
            )
            self.store.write(batch)
            self._condition.notify_all()
            return batch

    def resume(self, batch_id: str) -> BatchStatus:
        with self._condition:
            batch = self.store.read(batch_id)
            if batch.state not in {"PAUSED", "PAUSE_REQUESTED"}:
                raise BatchStateError("BATCH_NOT_RESUMABLE")
            batch = _summarized(
                batch, state="QUEUED", requested_control="RUN"
            )
            self.store.write(batch)
            self._start_worker_locked(batch_id)
            self._condition.notify_all()
            return batch

    def cancel(self, batch_id: str) -> BatchStatus:
        with self._condition:
            batch = self.store.read(batch_id)
            if batch.state in TERMINAL_BATCH_STATES:
                raise BatchStateError("BATCH_ALREADY_TERMINAL")
            batch = _summarized(
                batch, state="CANCEL_REQUESTED", requested_control="CANCEL"
            )
            self.store.write(batch)
            self._start_worker_locked(batch_id)
            self._condition.notify_all()
            return batch

    def retry_failed(self, batch_id: str) -> BatchStatus:
        with self._condition:
            batch = self.store.read(batch_id)
            if batch.state not in TERMINAL_BATCH_STATES | {"PAUSED"}:
                raise BatchStateError("BATCH_NOT_RETRYABLE")
            retryable = {
                item.item_id for item in batch.items
                if item.status == "FAILED" and item.attempt < batch.max_attempts
            }
            if not retryable:
                raise BatchStateError("NO_RETRYABLE_ITEMS")
            items = [
                item.model_copy(update={
                    "status": "QUEUED",
                    "attempt": item.attempt + 1,
                    "run_id": None,
                    "error_code": None,
                    "delivery_status": None,
                }) if item.item_id in retryable else item
                for item in batch.items
            ]
            batch = _summarized(
                batch, items=items, state="QUEUED", requested_control="RUN"
            )
            self.store.write(batch)
            self._start_worker_locked(batch_id)
            self._condition.notify_all()
            return batch

    def _start_worker_locked(self, batch_id: str) -> None:
        existing = self._workers.get(batch_id)
        if existing is not None and existing.is_alive():
            return
        worker = threading.Thread(
            target=self._work,
            args=(batch_id,),
            name=f"ax-batch-{batch_id}",
            daemon=True,
        )
        self._workers[batch_id] = worker
        worker.start()

    def _work(self, batch_id: str) -> None:
        try:
            while True:
                with self._condition:
                    batch = self.store.read(batch_id)
                    if not any(
                        item.status in {"QUEUED", "RUNNING"}
                        for item in batch.items
                    ):
                        batch = _summarized(
                            batch, state=_terminal_state(batch)
                        )
                        self.store.write(batch)
                        self._workers.pop(batch_id, None)
                        return
                    while batch.requested_control == "PAUSE":
                        if batch.state != "PAUSED":
                            batch = _summarized(batch, state="PAUSED")
                            self.store.write(batch)
                        self._condition.wait()
                        batch = self.store.read(batch_id)
                    if batch.requested_control == "CANCEL":
                        items = [
                            item.model_copy(update={"status": "CANCELLED"})
                            if item.status == "QUEUED" else item
                            for item in batch.items
                        ]
                        batch = _summarized(
                            batch, items=items, state="CANCELLED"
                        )
                        self.store.write(batch)
                        self._workers.pop(batch_id, None)
                        return
                    next_item = next(
                        (item for item in batch.items if item.status == "QUEUED"),
                        None,
                    )
                    if next_item is None:
                        batch = _summarized(
                            batch, state=_terminal_state(batch)
                        )
                        self.store.write(batch)
                        self._workers.pop(batch_id, None)
                        return
                    run_id = (
                        f"{batch.batch_id}-{next_item.item_id}-a{next_item.attempt}"
                    )
                    items = [
                        item.model_copy(update={
                            "status": "RUNNING", "run_id": run_id,
                        }) if item.item_id == next_item.item_id else item
                        for item in batch.items
                    ]
                    batch = _summarized(batch, items=items, state="RUNNING")
                    self.store.write(batch)
                    running_item = next(
                        item for item in batch.items
                        if item.item_id == next_item.item_id
                    )

                status: BatchItemState
                error_code: str | None = None
                delivery_status: Literal["DELIVERED", "REJECTED"] | None = None
                try:
                    delivery = self.executor(batch, running_item, run_id)
                    delivery_status = delivery.delivery_status
                    if delivery.delivery_status == "DELIVERED":
                        status = "SUCCEEDED"
                    else:
                        status = "FAILED"
                        error_code = delivery.reject_reason or "RUN_REJECTED"
                except Exception as exc:  # the scheduler must persist every failure
                    status = "FAILED"
                    detail = getattr(exc, "detail", None)
                    error_code = detail if isinstance(detail, str) else "BATCH_EXECUTION_ERROR"

                with self._condition:
                    batch = self.store.read(batch_id)
                    items = [
                        item.model_copy(update={
                            "status": status,
                            "error_code": error_code,
                            "delivery_status": delivery_status,
                        }) if item.item_id == running_item.item_id else item
                        for item in batch.items
                    ]
                    batch = _summarized(batch, items=items)
                    self.store.write(batch)
                    self._condition.notify_all()
        finally:
            with self._lock:
                self._workers.pop(batch_id, None)

    def _recover_interrupted(self) -> None:
        with self._lock:
            for batch in self.store.records():
                if batch.state not in ACTIVE_BATCH_STATES:
                    continue
                if batch.requested_control == "CANCEL":
                    items = [
                        item.model_copy(update={"status": "CANCELLED"})
                        if item.status in {"QUEUED", "RUNNING"} else item
                        for item in batch.items
                    ]
                    self.store.write(_summarized(
                        batch, items=items, state="CANCELLED"
                    ))
                    continue
                items = [
                    item.model_copy(update={
                        "status": "FAILED",
                        "error_code": "INTERRUPTED_BY_RESTART",
                    }) if item.status == "RUNNING" else item
                    for item in batch.items
                ]
                recovered = _summarized(
                    batch,
                    items=items,
                    state="PAUSED",
                    requested_control="PAUSE",
                )
                self.store.write(recovered)
