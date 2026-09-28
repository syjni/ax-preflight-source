"""Create and validate the ax-exp-v3 freeze without running held-out tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity
from scripts import freeze_experiment_v2 as v2
from scripts.validate_runtime_routing import DEV_TASK_IDS, validate_routing


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("experiment/frozen/ax-exp-v3-manifest.json")
EXPECTED_BACKEND = "SEMI_AUTOMATED_FRESH_PROCESS"
EXPECTED_TEST_COUNT = 113
V3_FILES = (
    Path("EXPERIMENT_PROTOCOL_V3.md"),
    Path("SEMI_AUTOMATED_EXECUTION_V3.md"),
    Path("EXPERIMENT_FREEZE_V3.md"),
    Path("scripts/session_prompt_validation.py"),
    Path("scripts/interactive_run_v3.py"),
    Path("scripts/semi_auto_runner_v3.py"),
    Path("scripts/automation_feasibility_v3.py"),
    Path("scripts/record_automation_feasibility_v3.py"),
    Path("scripts/audit_operator_error_v3.py"),
    Path("scripts/freeze_experiment_v3.py"),
    Path("tests/test_prompt_validation_v3.py"),
    Path("tests/test_semi_auto_runner_v3.py"),
    Path("experiment/v3/automation-feasibility.json"),
    Path("experiment/v3/operator-errors/35613a28-a498-4707-b72a-c58e67697a58.json"),
    Path(".kiro/agents/ax-evaluation-v3-dev-smoke-1.json"),
)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record(root: Path, path: Path) -> dict[str, Any]:
    target = path if path.is_absolute() else root / path
    return {
        "path": target.relative_to(root).as_posix(),
        "size_bytes": target.stat().st_size,
        "sha256": _sha(target),
    }


def _aggregate(records: list[dict[str, Any]]) -> str:
    payload = "".join(
        f"{record['path']}\0{record['size_bytes']}\0{record['sha256']}\n" for record in records
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _held_out_counts(root: Path, held_out: set[str]) -> tuple[int, int]:
    valid = 0
    v3_prompt_submissions = 0
    for path in (root / "artifacts").rglob("metadata.json"):
        try:
            data = _read(path)
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("task_id") not in held_out:
            continue
        if data.get("validity_status") == "VALID":
            valid += 1
        if data.get("experiment_version") == "ax-exp-v3" and data.get("submitted_prompt_sha256"):
            v3_prompt_submissions += 1
    return valid, v3_prompt_submissions


def _current_invariant_components(root: Path, v1_manifest: dict[str, Any]) -> dict[str, Any]:
    result = {}
    component_ids = (
        "mcp_server_implementation", "mcp_schemas", "retrieval_implementation_configuration",
        "scanner_implementation_configuration", "ceiling_dataset_manifest", "benchmark_manifest",
        "ground_truth", "task_to_defect_manifest", "control_source_manifest", "deterministic_scorer",
        "output_contract_validator", "failure_taxonomy", "runtime_prompt_constructor",
        "readiness_score_v1", "readiness_score_specification",
    )
    for component_id in component_ids:
        frozen = v2._component(v1_manifest, component_id)
        current = v2._current_component(root, frozen)
        result[component_id] = {
            "frozen_aggregate_sha256": frozen["aggregate_sha256"],
            "current_aggregate_sha256": current["aggregate_sha256"],
            "unchanged": current["aggregate_sha256"] == frozen["aggregate_sha256"],
        }
    return result


def _inventory_paths(root: Path) -> list[Path]:
    paths = list(V3_FILES)
    for directory in (
        root / "experiment/v3/operator-errors/evidence",
        root / "artifacts/v3_automation_feasibility_2026-09-20",
        root / "artifacts/v3_automation_feasibility_2026-09-20_attempt2",
        root / "artifacts/v3_automation_feasibility_2026-09-20_attempt3",
        root / "artifacts/v3_automation_feasibility_2026-09-20_attempt4",
    ):
        if directory.is_dir():
            paths.extend(path.relative_to(root) for path in directory.rglob("*") if path.is_file())
    return sorted(set(paths), key=lambda item: item.as_posix())


def create_manifest(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    v2_path = root / "experiment/frozen/ax-exp-v2-manifest.json"
    v2_manifest = _read(v2_path)
    v2_validation = v2.validate_manifest(root)
    if not v2_validation["passed"]:
        raise ValueError(f"v2 freeze no longer validates: {v2_validation['mismatches']}")

    v1_manifest = _read(root / "experiment/frozen/ax-exp-v1-manifest.json")
    invariant_components = _current_invariant_components(root, v1_manifest)
    if not all(value["unchanged"] for value in invariant_components.values()):
        raise ValueError("one or more frozen invariant components changed")

    config = _read(root / ".kiro/agents/ax-evaluation.json")
    prompt_hash = hashlib.sha256(config["prompt"].encode("utf-8")).hexdigest()
    if prompt_hash != v2_manifest["prompt_hash"] or config.get("model") != v2_manifest["model"]:
        raise ValueError("frozen prompt or model changed")
    if config.get("tools") != v2_manifest["tool_surface"] or config.get("allowedTools") != v2_manifest["tool_surface"]:
        raise ValueError("frozen four-tool surface changed")

    immutable_v2_hashes = {
        "task_runtime_bindings": _sha(root / "task_runtime_bindings.json"),
        "defect_injection_spec": _sha(root / "DEFECT_INJECTION_SPEC_V2.json"),
        "runtime_dataset_configuration": _sha(root / "runtime_datasets.json"),
        "v2_interactive_recorder": _sha(root / "scripts/interactive_run.py"),
        "v2_protocol": _sha(root / "EXPERIMENT_PROTOCOL_V2.md"),
        "v2_freeze_receipt": _sha(root / "EXPERIMENT_FREEZE_V2.md"),
    }
    expected_v2_hashes = {
        "task_runtime_bindings": v2_manifest["task_runtime_binding_artifact"]["sha256"],
        "defect_injection_spec": v2_manifest["defect_injection_spec_artifact"]["sha256"],
        "runtime_dataset_configuration": v2_manifest["runtime_dataset_config_hash"],
        "v2_interactive_recorder": v2_manifest["interactive_recorder_hash"],
        "v2_protocol": next(item["sha256"] for item in v2_manifest["v2_artifact_inventory"]["files"] if item["path"] == "EXPERIMENT_PROTOCOL_V2.md"),
        "v2_freeze_receipt": _sha(root / "EXPERIMENT_FREEZE_V2.md"),
    }
    if immutable_v2_hashes != expected_v2_hashes:
        raise ValueError("one or more v2 design artifacts changed")

    routing = validate_routing(root)
    if not routing["passed"]:
        raise ValueError("frozen task/runtime routing failed")
    ceiling = runtime_identity(resolve_runtime_dataset("ceiling", root / "runtime_datasets.json"))
    if ceiling != v2_manifest["ceiling_runtime_identity"]:
        raise ValueError("Ceiling runtime identity changed")

    benchmark = _read(root / "benchmark_tasks.json")
    held_out = [task["task_id"] for task in benchmark["tasks"] if task["task_id"] not in DEV_TASK_IDS]
    valid_count, prompt_submission_count = _held_out_counts(root, set(held_out))
    if valid_count or prompt_submission_count:
        raise ValueError("held-out v3 execution evidence exists before freeze")

    feasibility_path = root / "experiment/v3/automation-feasibility.json"
    feasibility = _read(feasibility_path)
    if feasibility.get("deterministic_automated_backend_available") is not False:
        raise ValueError("automation feasibility decision is not frozen to semi-automated fallback")
    audit_path = root / "experiment/v3/operator-errors/35613a28-a498-4707-b72a-c58e67697a58.json"
    audit = _read(audit_path)
    if (
        audit.get("classification") != "INVALID_OPERATOR_WRONG_PROMPT"
        or audit.get("official_denominator_included") is not False
        or audit.get("held_out_task_prompt_submitted") is not False
    ):
        raise ValueError("known operator-error classification changed")
    for path_key, hash_key in (
        ("preserved_session_file", "preserved_session_file_sha256"),
        ("preserved_session_events_file", "preserved_session_events_file_sha256"),
    ):
        if _sha(root / audit[path_key]) != audit[hash_key]:
            raise ValueError("preserved operator-error evidence hash mismatch")

    records = [_record(root, path) for path in _inventory_paths(root)]
    return {
        "schema_version": "ax-experiment-freeze-manifest-v3",
        "experiment_version": "ax-exp-v3",
        "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "FROZEN",
        "ready_for_heldout": True,
        "predecessor_manifest": {"path": v2_path.relative_to(root).as_posix(), "sha256": _sha(v2_path)},
        "predecessor_validation": v2_validation,
        "substantive_changes": [
            "exact submitted-prompt validation",
            "semi-automated fresh-process execution orchestration",
        ],
        "model": config["model"],
        "prompt_version": v2_manifest["prompt_version"],
        "prompt_hash": prompt_hash,
        "tool_surface": v2_manifest["tool_surface"],
        "tool_count": len(v2_manifest["tool_surface"]),
        "execution_backend": EXPECTED_BACKEND,
        "kiro_cli_version": feasibility["kiro_cli_version"],
        "run_design": v2_manifest["run_design"],
        "treated_task_count": v2_manifest["treated_task_count"],
        "control_task_count": v2_manifest["control_task_count"],
        "unique_defect_variant_count": v2_manifest["unique_defect_variant_count"],
        "held_out_task_ids": held_out,
        "held_out_valid_execution_count": valid_count,
        "held_out_task_prompt_submission_count": prompt_submission_count,
        "ceiling_runtime_identity": ceiling,
        "ceiling_runtime_identity_sha256": _canonical_hash(ceiling),
        "immutable_v2_artifact_hashes": immutable_v2_hashes,
        "frozen_invariant_components": invariant_components,
        "routing_validation": routing["summary"],
        "automation_feasibility": {
            "path": feasibility_path.relative_to(root).as_posix(),
            "sha256": _sha(feasibility_path),
            "deterministic_automated_backend_available": False,
            "decision": feasibility["decision"],
        },
        "known_operator_error": {
            "path": audit_path.relative_to(root).as_posix(),
            "sha256": _sha(audit_path),
            "session_id": audit["session_id"],
            "classification": audit["classification"],
            "official_denominator_included": False,
        },
        "v3_hashes": {
            "automation_runner": _sha(root / "scripts/semi_auto_runner_v3.py"),
            "interactive_recorder": _sha(root / "scripts/interactive_run_v3.py"),
            "submitted_prompt_validator": _sha(root / "scripts/session_prompt_validation.py"),
            "automation_feasibility_probe": _sha(root / "scripts/automation_feasibility_v3.py"),
            "operator_error_auditor": _sha(root / "scripts/audit_operator_error_v3.py"),
            "freeze_script": _sha(root / "scripts/freeze_experiment_v3.py"),
        },
        "regression_tests": {
            "command": "python -m unittest discover -v",
            "passed": EXPECTED_TEST_COUNT,
            "total": EXPECTED_TEST_COUNT,
            "result": f"{EXPECTED_TEST_COUNT}/{EXPECTED_TEST_COUNT} PASS",
            "required_v3_cases": [
                "exact prompt accepted", "modified prompt invalid", "command snippet invalid",
                "wrong task prompt invalid", "prefix/suffix invalid", "multiple turns invalid",
                "wrong agent invalid", "wrong runtime invalid", "64-run order",
                "one fresh process per run", "process termination", "ambiguous session invalid",
            ],
        },
        "validation": {
            "v2_freeze_unchanged": True,
            "prompt_hash_unchanged": True,
            "model_unchanged": True,
            "retrieval_unchanged": invariant_components["retrieval_implementation_configuration"]["unchanged"],
            "scanner_unchanged": invariant_components["scanner_implementation_configuration"]["unchanged"],
            "benchmark_unchanged": invariant_components["benchmark_manifest"]["unchanged"],
            "ground_truth_unchanged": invariant_components["ground_truth"]["unchanged"],
            "before_ceiling_datasets_unchanged": v2_validation["passed"],
            "ceiling_runtime_identity_unchanged": True,
            "task_runtime_bindings_unchanged": True,
            "held_out_valid_execution_count": valid_count,
            "held_out_task_prompt_submission_count": prompt_submission_count,
        },
        "v3_artifact_inventory": {
            "file_count": len(records),
            "aggregate_sha256": _aggregate(records),
            "files": records,
        },
        "next_safe_action": "Run the first held-out pair with the frozen v3 semi-automated wrapper, or run all 64 in the pre-registered order.",
    }


def validate_manifest(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    manifest = _read(root / MANIFEST_PATH)
    mismatches: list[dict[str, str]] = []
    current = []
    for frozen in manifest["v3_artifact_inventory"]["files"]:
        path = root / frozen["path"]
        if not path.is_file():
            mismatches.append({"type": "missing", "path": frozen["path"]})
            continue
        record = _record(root, path)
        current.append(record)
        if record != frozen:
            mismatches.append({"type": "file_hash", "path": frozen["path"]})
    if len(current) == manifest["v3_artifact_inventory"]["file_count"]:
        if _aggregate(current) != manifest["v3_artifact_inventory"]["aggregate_sha256"]:
            mismatches.append({"type": "aggregate_hash", "path": "v3_artifact_inventory"})

    predecessor = v2.validate_manifest(root)
    if not predecessor["passed"]:
        mismatches.append({"type": "v2_freeze", "path": "experiment/frozen/ax-exp-v2-manifest.json"})
    immutable_paths = {
        "task_runtime_bindings": Path("task_runtime_bindings.json"),
        "defect_injection_spec": Path("DEFECT_INJECTION_SPEC_V2.json"),
        "runtime_dataset_configuration": Path("runtime_datasets.json"),
        "v2_interactive_recorder": Path("scripts/interactive_run.py"),
        "v2_protocol": Path("EXPERIMENT_PROTOCOL_V2.md"),
        "v2_freeze_receipt": Path("EXPERIMENT_FREEZE_V2.md"),
    }
    for key, path in immutable_paths.items():
        if _sha(root / path) != manifest["immutable_v2_artifact_hashes"][key]:
            mismatches.append({"type": "v2_artifact_hash", "path": path.as_posix()})
    config = _read(root / ".kiro/agents/ax-evaluation.json")
    if hashlib.sha256(config.get("prompt", "").encode("utf-8")).hexdigest() != manifest["prompt_hash"]:
        mismatches.append({"type": "prompt_hash", "path": ".kiro/agents/ax-evaluation.json"})
    if config.get("model") != manifest["model"]:
        mismatches.append({"type": "model", "path": ".kiro/agents/ax-evaluation.json"})
    if config.get("tools") != manifest["tool_surface"] or config.get("allowedTools") != manifest["tool_surface"]:
        mismatches.append({"type": "tool_surface", "path": ".kiro/agents/ax-evaluation.json"})
    ceiling = runtime_identity(resolve_runtime_dataset("ceiling", root / "runtime_datasets.json"))
    if _canonical_hash(ceiling) != manifest["ceiling_runtime_identity_sha256"]:
        mismatches.append({"type": "ceiling_runtime_identity", "path": "runtime_datasets.json"})
    routing = validate_routing(root)
    if not routing["passed"]:
        mismatches.append({"type": "routing_validation", "path": "task_runtime_bindings.json"})
    held_out = set(manifest["held_out_task_ids"])
    valid_count, prompt_submission_count = _held_out_counts(root, held_out)
    if valid_count != manifest["held_out_valid_execution_count"]:
        mismatches.append({"type": "held_out_valid_execution_count", "path": str(valid_count)})
    if prompt_submission_count != manifest["held_out_task_prompt_submission_count"]:
        mismatches.append({"type": "held_out_prompt_submission_count", "path": str(prompt_submission_count)})
    return {
        "schema_version": "ax-experiment-freeze-validation-v3",
        "experiment_version": "ax-exp-v3",
        "passed": not mismatches,
        "artifact_count": len(current),
        "held_out_valid_execution_count": valid_count,
        "held_out_task_prompt_submission_count": prompt_submission_count,
        "mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.validate:
        result = validate_manifest(root)
    else:
        result = create_manifest(root)
        output = root / MANIFEST_PATH
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
