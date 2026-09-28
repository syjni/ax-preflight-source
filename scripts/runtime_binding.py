"""Resolve the pre-registered ax-exp-v2 task/condition runtime binding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINDINGS = ROOT / "task_runtime_bindings.json"
VALID_CONDITIONS = {"before": "Before", "ceiling": "Ceiling"}


class RuntimeBindingError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeBinding:
    task_id: str
    task_group: str
    condition: str
    runtime_profile: str
    defect_variant_id: str | None


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeBindingError(f"task runtime binding artifact not found: {path}") from exc


def normalize_condition(condition: str) -> str:
    try:
        return VALID_CONDITIONS[condition.strip().casefold()]
    except (AttributeError, KeyError) as exc:
        raise RuntimeBindingError(
            f"unknown condition {condition!r}; expected Before or Ceiling"
        ) from exc


def resolve_runtime_binding(
    task_id: str,
    condition: str,
    binding_path: str | Path | None = None,
) -> RuntimeBinding:
    path = Path(binding_path or DEFAULT_BINDINGS).resolve()
    payload = _read(path)
    if payload.get("schema_version") != "ax-task-runtime-bindings-v2":
        raise RuntimeBindingError(f"unsupported task runtime binding schema: {payload.get('schema_version')}")
    if payload.get("experiment_version") != "ax-exp-v2":
        raise RuntimeBindingError("task runtime bindings are not for ax-exp-v2")
    entries = payload.get("bindings", [])
    matches = [entry for entry in entries if entry.get("task_id") == task_id]
    if len(matches) != 1:
        known = sorted(entry.get("task_id") for entry in entries)
        raise RuntimeBindingError(f"unknown task {task_id!r}; known held-out tasks={known}")
    entry = matches[0]
    canonical = normalize_condition(condition)
    profiles = entry.get("runtime_profiles", {})
    if set(profiles) != {"Before", "Ceiling"}:
        raise RuntimeBindingError(f"task {task_id!r} must bind exactly Before and Ceiling")
    group = entry.get("task_group")
    variant = entry.get("defect_variant_id")
    if group not in {"treated", "control"}:
        raise RuntimeBindingError(f"task {task_id!r} has invalid task_group {group!r}")
    if group == "treated" and not variant:
        raise RuntimeBindingError(f"treated task {task_id!r} has no defect variant")
    if group == "control" and variant is not None:
        raise RuntimeBindingError(f"control task {task_id!r} must not have a defect variant")
    return RuntimeBinding(
        task_id=task_id,
        task_group=group,
        condition=canonical,
        runtime_profile=profiles[canonical],
        defect_variant_id=variant,
    )
