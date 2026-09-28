"""Read-only preflight for a future, independently prepared ax-exp-v4 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.v4_scoring import validate_task_spec


ROOT = Path(__file__).resolve().parents[1]
STRATA = {"ratio", "threshold", "set", "exact_or_abstain"}


def _within(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_manifest(
    manifest: dict[str, Any], *, root: Path = ROOT, require_ready: bool = True
) -> list[str]:
    """Return every detectable registration defect without writing any file."""
    root = root.resolve()
    errors: list[str] = []
    if manifest.get("schema_version") != "ax-exp-v4-preregistration-v1":
        errors.append("wrong schema_version")
    if manifest.get("experiment_id") != "ax-exp-v4":
        errors.append("wrong experiment_id")
    if require_ready and manifest.get("status") not in {"READY_FOR_FREEZE", "FROZEN"}:
        errors.append("manifest is not ready or frozen")
    elif not require_ready and manifest.get("status") not in {"DRAFT", "READY_FOR_FREEZE", "FROZEN"}:
        errors.append("unknown candidate status")
    if manifest.get("repetitions") != 2:
        errors.append("expected exactly two repetitions")
    if manifest.get("model") != "claude-sonnet-5":
        errors.append("model differs from registered v4 design")
    if manifest.get("kiro_cli_version") != "kiro-cli-chat 2.23.0":
        errors.append("Kiro CLI version differs from registered v4 design")
    if manifest.get("backend") != "AUTOMATED_FRESH_PROCESS_V2":
        errors.append("backend differs from registered v4 design")
    if manifest.get("runtime_profile") != "v4-candidate":
        errors.append("runtime profile differs from registered v4 design")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 16:
        errors.append("expected exactly 16 new tasks")
        tasks = tasks if isinstance(tasks, list) else []
    task_ids = [task.get("task_id") for task in tasks if isinstance(task, dict)]
    if any(not isinstance(value, str) for value in task_ids):
        errors.append("non-string v4 task ID")
        task_ids = [value for value in task_ids if isinstance(value, str)]
    if len(task_ids) != len(set(task_ids)):
        errors.append("duplicate v4 task ID")
    if any(not isinstance(value, str) or not value for value in task_ids):
        errors.append("missing v4 task ID")
    counts = Counter(task.get("stratum") for task in tasks if isinstance(task, dict))
    if set(counts) != STRATA or any(counts[name] != 4 for name in STRATA):
        errors.append("expected four tasks in each registered stratum")

    old_path = root / "benchmark_tasks.json"
    if not old_path.is_file():
        errors.append("missing v3 benchmark for overlap check")
        old_tasks: list[dict[str, Any]] = []
    else:
        old_tasks = json.loads(old_path.read_text(encoding="utf-8"))["tasks"]
    old_ids = {task["task_id"] for task in old_tasks}
    old_questions = {" ".join(task["question"].casefold().split()) for task in old_tasks}
    new_questions: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            errors.append("non-object task")
            continue
        identifier = task.get("task_id", "<missing>")
        if identifier in old_ids:
            errors.append(f"{identifier}: v3 task ID reused")
        question = task.get("question")
        if not isinstance(question, str) or not question.strip():
            errors.append(f"{identifier}: missing question")
        else:
            normalized = " ".join(question.casefold().split())
            if normalized in old_questions:
                errors.append(f"{identifier}: v3 question text reused")
            if normalized in new_questions:
                errors.append(f"{identifier}: duplicate v4 question")
            new_questions.add(normalized)
        if task.get("category") not in {"knowledge", "operations", "cross_file"}:
            errors.append(f"{identifier}: invalid category")
        expected_kind = {
            "ratio": "numeric_quantity", "threshold": "numeric_quantity",
            "set": "set_items", "exact_or_abstain": "exact_text",
        }.get(task.get("stratum"))
        if expected_kind is not None and task.get("scoring_method", {}).get("type") != expected_kind:
            errors.append(f"{identifier}: stratum and scoring type disagree")
        try:
            validate_task_spec(task)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{identifier}: invalid scoring specification: {exc}")

    dataset_files = manifest.get("dataset_files")
    if not isinstance(dataset_files, list) or not dataset_files:
        errors.append("missing dataset file inventory")
        dataset_files = []
    registered_sources: set[str] = set()
    dataset_root = (root / "experiment" / "v4" / "heldout").resolve()
    for entry in dataset_files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append("malformed dataset file entry")
            continue
        relative = entry["path"]
        path = (root / relative).resolve()
        if not _within(path, dataset_root):
            errors.append(f"dataset file escapes new heldout root: {relative}")
            continue
        if relative in registered_sources:
            errors.append(f"duplicate dataset file: {relative}")
        registered_sources.add(relative)
        if not path.is_file() or _digest(path) != entry.get("sha256"):
            errors.append(f"missing or changed dataset file: {relative}")
    for task in tasks:
        if not isinstance(task, dict):
            continue
        sources = task.get("required_sources")
        if not isinstance(sources, list) or any(source not in registered_sources for source in sources):
            errors.append(f"{task.get('task_id')}: source missing from inventory")

    frozen_files = manifest.get("frozen_files")
    if not isinstance(frozen_files, list) or not frozen_files:
        errors.append("missing frozen file inventory")
        frozen_files = []
    frozen_paths = set()
    for entry in frozen_files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append("malformed frozen file entry")
            continue
        relative = entry["path"]
        frozen_paths.add(relative)
        path = (root / relative).resolve()
        if not _within(path, root) or not path.is_file() or _digest(path) != entry.get("sha256"):
            errors.append(f"missing or changed frozen file: {relative}")
    required_frozen = {
        "scripts/v4_contract.py", "scripts/v4_scoring.py", "scripts/v4_prompt.py",
        "scripts/v4_evaluation.py",
        "scripts/v4_official_runner.py",
        "scripts/freeze_v4.py",
        "experiment/v4/AGENT_PROMPT.txt", "experiment/v4/PREREGISTRATION.md",
    }
    if not required_frozen.issubset(frozen_paths):
        errors.append("required v4 implementation or protocol absent from frozen inventory")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--allow-draft", action="store_true",
                        help="check a candidate without declaring it ready for official execution")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    errors = validate_manifest(manifest, require_ready=not args.allow_draft)
    print(json.dumps({"passed": not errors, "ready_for_official": not errors and not args.allow_draft,
                      "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
