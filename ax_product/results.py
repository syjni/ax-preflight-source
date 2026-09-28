"""Process-independent, run-scoped delivery envelopes."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal
from uuid import uuid4

from .models import DeliveryEnvelope


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
DEFAULT_RESULTS_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "product_runs"


class DuplicateRunError(ValueError):
    pass


class RunInProgressError(ValueError):
    def __init__(self, run_id: str, dataset: str = "UNKNOWN") -> None:
        super().__init__(run_id)
        self.dataset = dataset


class FinalResultExistsError(ValueError):
    pass


class ResultStoreConfigurationError(RuntimeError):
    """Raised when writable and frozen run stores cannot be used safely."""


RunStorageOrigin = Literal["writable", "frozen"]


class ResultStore:
    def __init__(self, root: str | Path = DEFAULT_RESULTS_ROOT):
        self.root = Path(root).resolve()

    def path(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("run_id must be 1-128 ASCII letters, digits, _ or -, starting with a letter or digit")
        return self.root / run_id / "delivery.json"

    def reserve(self, *, run_id: str, task_id: str | None, model: str,
                dataset: str, task_key: str | None = None,
                task_label: str | None = None,
                request_type: str | None = None) -> Path:
        """Atomically claim a run without publishing a final delivery result."""
        if not dataset or not dataset.strip() or dataset != dataset.strip():
            raise ValueError("dataset must be a nonblank, unpadded profile")
        path = self.path(run_id)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary_dir = self.root / f".{uuid4().hex}.tmp"
        temporary_dir.mkdir()
        try:
            state = temporary_dir / "state.json"
            with state.open("x", encoding="utf-8", newline="\n") as output:
                json.dump({"run_id": run_id, "run_status": "RUNNING", "dataset": dataset}, output)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            if task_key is not None:
                if not task_key.strip() or task_key != task_key.strip():
                    raise ValueError("task_key must be nonblank and unpadded")
                if task_label is None or not task_label.strip() or task_label != task_label.strip():
                    raise ValueError("task_label must be nonblank and unpadded")
                if request_type not in {"VERIFIED_BUSINESS_TASK", "TASK_CANDIDATE", "AD_HOC_QUESTION"}:
                    raise ValueError("request_type is invalid")
                context = temporary_dir / "run-context.json"
                with context.open("x", encoding="utf-8", newline="\n") as output:
                    json.dump({
                        "schema_version": "ax-run-context-v1",
                        "run_id": run_id,
                        "dataset": dataset,
                        "task_id": task_key,
                        "task_label": task_label,
                        "request_type": request_type,
                    }, output, ensure_ascii=False, sort_keys=True)
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())
            try:
                temporary_dir.rename(path.parent)
            except OSError as exc:
                if path.parent.exists():
                    raise DuplicateRunError(run_id) from exc
                raise
        finally:
            if temporary_dir.exists():
                (temporary_dir / "state.json").unlink(missing_ok=True)
                (temporary_dir / "run-context.json").unlink(missing_ok=True)
                temporary_dir.rmdir()
        return path

    def write(self, envelope: DeliveryEnvelope) -> Path:
        """Publish exactly one final envelope; never replace an existing one."""
        path = self.path(envelope.run_id)
        if not path.parent.is_dir():
            raise FileNotFoundError(f"run has not been reserved: {envelope.run_id}")
        # The API's atomic reservation owns provenance. A runner cannot replace it.
        dataset = self._reserved_dataset(path.parent / "state.json")
        stored = DeliveryEnvelope.model_validate({**envelope.model_dump(mode="python"),
                                                  "dataset": dataset})
        self._write_file_once(path, stored)
        (path.parent / "state.json").unlink(missing_ok=True)
        return path

    @staticmethod
    def _reserved_dataset(state_path: Path) -> str:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return "UNKNOWN"
        dataset = state.get("dataset", "UNKNOWN")
        if not isinstance(dataset, str) or not dataset.strip() or dataset != dataset.strip():
            raise ValueError("invalid reserved dataset")
        return dataset

    @staticmethod
    def _write_file_once(path: Path, envelope: DeliveryEnvelope) -> None:
        temporary = path.parent / f".{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as output:
                json.dump(envelope.model_dump(mode="json"), output, ensure_ascii=False, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            try:
                # Same-directory hard link is atomic and fails if the final name exists.
                os.link(temporary, path)
            except FileExistsError as exc:
                raise FinalResultExistsError(envelope.run_id) from exc
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, run_id: str) -> DeliveryEnvelope:
        path = self.path(run_id)
        try:
            return DeliveryEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            state_path = path.parent / "state.json"
            if state_path.is_file():
                raise RunInProgressError(run_id, self._reserved_dataset(state_path)) from None
            raise


class ReadOnlyResultStore:
    """Delivery lookup surface with no mutation methods."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ResultStoreConfigurationError(
                f"frozen results root is not a directory: {self.root}"
            )

    def path(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError(
                "run_id must be 1-128 ASCII letters, digits, _ or -, "
                "starting with a letter or digit"
            )
        return self.root / run_id / "delivery.json"

    def contains(self, run_id: str) -> bool:
        return self.path(run_id).parent.is_dir()

    def read(self, run_id: str) -> DeliveryEnvelope:
        return DeliveryEnvelope.model_validate_json(
            self.path(run_id).read_text(encoding="utf-8")
        )


def _contains_path(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_result_roots(writable_root: Path, frozen_root: Path) -> None:
    """Reject roots that alias or nest, before either store is activated."""
    if _contains_path(writable_root, frozen_root) or _contains_path(frozen_root, writable_root):
        raise ResultStoreConfigurationError(
            "writable and frozen results roots must be distinct and non-overlapping"
        )


def _run_directories(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {path.name for path in root.iterdir() if path.is_dir()}


class CompositeResultStore:
    """Write to one store and resolve reads across writable plus frozen stores."""

    def __init__(
        self,
        writable_root: str | Path = DEFAULT_RESULTS_ROOT,
        frozen_root: str | Path | None = None,
    ) -> None:
        self.writable = ResultStore(writable_root)
        self.frozen: ReadOnlyResultStore | None = None
        if frozen_root is None:
            return
        resolved_frozen = Path(frozen_root).resolve()
        validate_result_roots(self.writable.root, resolved_frozen)
        self.frozen = ReadOnlyResultStore(resolved_frozen)
        duplicates = sorted(
            _run_directories(self.writable.root).intersection(
                _run_directories(self.frozen.root)
            )
        )
        if duplicates:
            raise ResultStoreConfigurationError(
                "run_id exists in both writable and frozen results roots: "
                + ", ".join(duplicates)
            )

    @property
    def root(self) -> Path:
        """The only root that may be passed to writers and runners."""
        return self.writable.root

    def origin(self, run_id: str) -> RunStorageOrigin:
        writable_directory = self.writable.path(run_id).parent
        writable_exists = writable_directory.is_dir()
        frozen_exists = self.frozen is not None and self.frozen.contains(run_id)
        if writable_exists and frozen_exists:
            raise ResultStoreConfigurationError(
                f"run_id exists in both writable and frozen results roots: {run_id}"
            )
        return "frozen" if frozen_exists else "writable"

    def reserve(
        self, *, run_id: str, task_id: str | None, model: str, dataset: str,
        task_key: str | None = None, task_label: str | None = None,
        request_type: str | None = None,
    ) -> Path:
        if self.frozen is not None and self.frozen.contains(run_id):
            raise DuplicateRunError(run_id)
        return self.writable.reserve(
            run_id=run_id, task_id=task_id, model=model, dataset=dataset,
            task_key=task_key, task_label=task_label, request_type=request_type,
        )

    def write(self, envelope: DeliveryEnvelope) -> Path:
        return self.writable.write(envelope)

    def read(self, run_id: str) -> DeliveryEnvelope:
        if self.origin(run_id) == "frozen":
            assert self.frozen is not None
            return self.frozen.read(run_id)
        return self.writable.read(run_id)
