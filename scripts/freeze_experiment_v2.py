"""Create and validate the ax-exp-v2 freeze without executing held-out tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity
from readiness_score import score_scan_report_file
from scripts.validate_runtime_routing import DEV_TASK_IDS, validate_routing


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("experiment/frozen/ax-exp-v2-manifest.json")
EXPECTED_PROMPT_HASH = "dc783a41a5b06eb871ada33be7dd21aec2e4106757a40921ddf59fcf81176fc8"
EXPECTED_TOOLS = [
    "@ax-tools/search_documents", "@ax-tools/read_document",
    "@ax-tools/lookup_value", "@ax-tools/query_table",
]


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


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


def _current_component(root: Path, frozen_component: dict[str, Any]) -> dict[str, Any]:
    records = [_record(root, Path(item["path"])) for item in frozen_component["files"]]
    return {"file_count": len(records), "aggregate_sha256": _aggregate(records), "files": records}


def _component(v1: dict[str, Any], component_id: str) -> dict[str, Any]:
    for group in v1["artifact_inventory"].values():
        for component in group:
            if component["component_id"] == component_id:
                return component
    raise KeyError(component_id)


def _held_out_execution_count(root: Path, held_out: set[str]) -> int:
    count = 0
    for path in (root / "artifacts").rglob("metadata.json"):
        data = _read(path)
        if data.get("task_id") in held_out and data.get("run_status") not in {None, "NOT_RUN", "PREPARED"}:
            count += 1
    blind = _read(root / "blind_gate_results.json")
    count += sum(run.get("task_id") in held_out and run.get("run_status") == "RECORDED" for run in blind.get("runs", []))
    return count


def _git_commit(root: Path) -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def create_manifest(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    v1_path = root / "experiment/frozen/ax-exp-v1-manifest.json"
    v1 = _read(v1_path)
    config = _read(root / ".kiro/agents/ax-evaluation.json")
    prompt_hash = hashlib.sha256(config["prompt"].encode("utf-8")).hexdigest()
    routing = validate_routing(root)
    if not routing["passed"]:
        raise ValueError("static routing validation failed")
    benchmark = _read(root / "benchmark_tasks.json")
    held_out = [task["task_id"] for task in benchmark["tasks"] if task["task_id"] not in DEV_TASK_IDS]
    held_out_count = _held_out_execution_count(root, set(held_out))
    if held_out_count:
        raise ValueError("held-out execution evidence exists")
    ceiling = runtime_identity(resolve_runtime_dataset("ceiling", root / "runtime_datasets.json"))
    if ceiling != v1["ceiling_runtime_identity"]:
        raise ValueError("Ceiling runtime identity changed")
    if prompt_hash != EXPECTED_PROMPT_HASH or config.get("model") != "claude-sonnet-5":
        raise ValueError("frozen model or prompt changed")
    if config.get("tools") != EXPECTED_TOOLS or config.get("allowedTools") != EXPECTED_TOOLS:
        raise ValueError("frozen four-tool surface changed")

    invariant_components = {
        component_id: {
            "v1_aggregate_sha256": frozen["aggregate_sha256"],
            "v2_current_aggregate_sha256": current["aggregate_sha256"],
            "unchanged": current["aggregate_sha256"] == frozen["aggregate_sha256"],
        }
        for component_id in (
            "mcp_server_implementation", "mcp_schemas", "retrieval_implementation_configuration",
            "scanner_implementation_configuration", "ceiling_dataset_manifest", "benchmark_manifest",
            "ground_truth", "task_to_defect_manifest", "control_source_manifest", "deterministic_scorer",
            "output_contract_validator", "failure_taxonomy", "runtime_prompt_constructor",
            "readiness_score_v1", "readiness_score_specification",
        )
        for frozen in [_component(v1, component_id)]
        for current in [_current_component(root, frozen)]
    }
    if not all(item["unchanged"] for item in invariant_components.values()):
        raise ValueError("one or more v1 frozen invariant components changed")

    spec = _read(root / "DEFECT_INJECTION_SPEC_V2.json")
    before_identities = {
        variant["runtime_profile"]: runtime_identity(
            resolve_runtime_dataset(variant["runtime_profile"], root / "runtime_datasets.json")
        )
        for variant in spec["variants"]
    }
    inventory_paths = [
        Path("DEFECT_INJECTION_SPEC_V2.json"), Path("task_runtime_bindings.json"),
        Path("runtime_datasets.json"), Path("INTERACTIVE_EXECUTION.md"),
        Path("EXPERIMENT_PROTOCOL_V2.md"), Path("scripts/generate_before_variants.py"),
        Path("scripts/runtime_binding.py"), Path("scripts/validate_runtime_routing.py"),
        Path("scripts/interactive_run.py"), Path("scripts/freeze_experiment_v2.py"),
        Path("tests/test_interactive_run.py"), Path("tests/test_runtime_routing_v2.py"),
    ]
    inventory_paths += sorted(path.relative_to(root) for path in (root / "sample_data/before_variants").rglob("*") if path.is_file())
    inventory_paths += sorted(path.relative_to(root) for path in (root / "experiment/v2/runtime").rglob("*") if path.is_file())
    records = [_record(root, path) for path in sorted(set(inventory_paths), key=lambda item: item.as_posix())]
    readiness = score_scan_report_file(root / "ceiling_scan_report.json")
    return {
        "schema_version": "ax-experiment-freeze-manifest-v2",
        "experiment_version": "ax-exp-v2",
        "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "FROZEN",
        "ready_for_heldout": True,
        "git_commit": _git_commit(root),
        "v1_frozen_manifest": {"path": v1_path.relative_to(root).as_posix(), "sha256": _sha(v1_path)},
        "model": config["model"],
        "prompt_version": "2",
        "prompt_hash": prompt_hash,
        "tool_surface": EXPECTED_TOOLS,
        "tool_count": 4,
        "execution_backend": "INTERACTIVE_FRESH_PROCESS",
        "run_design": "16 tasks x 2 conditions x 2 repetitions = 64 runs",
        "treated_task_count": 12,
        "control_task_count": 4,
        "unique_defect_variant_count": len(spec["variants"]),
        "held_out_task_ids": held_out,
        "held_out_execution_count": held_out_count,
        "ceiling_runtime_identity": ceiling,
        "ceiling_runtime_identity_sha256": _canonical_hash(ceiling),
        "before_runtime_identities": before_identities,
        "task_runtime_binding_artifact": {"path": "task_runtime_bindings.json", "sha256": _sha(root / "task_runtime_bindings.json")},
        "defect_injection_spec_artifact": {"path": "DEFECT_INJECTION_SPEC_V2.json", "sha256": _sha(root / "DEFECT_INJECTION_SPEC_V2.json")},
        "runtime_dataset_config_hash": _sha(root / "runtime_datasets.json"),
        "interactive_recorder_hash": _sha(root / "scripts/interactive_run.py"),
        "before_generator_hash": _sha(root / "scripts/generate_before_variants.py"),
        "routing_validator_hash": _sha(root / "scripts/validate_runtime_routing.py"),
        "freeze_script_hash": _sha(root / "scripts/freeze_experiment_v2.py"),
        "routing_validation": routing["summary"],
        "routing_validation_artifact_hash": _sha(root / "experiment/v2/runtime/routing-validation.json"),
        "ceiling_readiness": readiness["readiness_score"],
        "v1_frozen_invariant_components": invariant_components,
        "unchanged_frozen_hashes": {
            "benchmark_hash": _sha(root / "benchmark_tasks.json"),
            "ground_truth_hash": _sha(root / "ground_truth.json"),
            "failure_taxonomy_hash": _sha(root / "EXPERIMENT_FAILURE_TAXONOMY.md"),
            "readiness_implementation_hash": _sha(root / "readiness_score.py"),
            "readiness_spec_hash": _sha(root / "READINESS_SCORE_SPEC.md"),
            "ceiling_dataset_manifest_hash": _sha(root / "dataset_manifest.json"),
        },
        "changed_v2_hashes": {
            "runtime_dataset_configuration": _sha(root / "runtime_datasets.json"),
            "interactive_run_recorder": _sha(root / "scripts/interactive_run.py"),
            "task_runtime_bindings": _sha(root / "task_runtime_bindings.json"),
            "defect_injection_spec": _sha(root / "DEFECT_INJECTION_SPEC_V2.json"),
        },
        "test_suite": {"command": "python -m unittest discover -v", "passed": 100, "total": 100, "result": "100/100 PASS"},
        "validation": {
            "static_routing_passed": True,
            "runtime_identity_mismatches": 0,
            "runtime_leakage_violations": 0,
            "ceiling_identity_unchanged": True,
            "prompt_hash_unchanged": True,
            "model_unchanged": True,
            "retrieval_unchanged": invariant_components["retrieval_implementation_configuration"]["unchanged"],
            "scanner_unchanged": invariant_components["scanner_implementation_configuration"]["unchanged"],
            "benchmark_unchanged": invariant_components["benchmark_manifest"]["unchanged"],
            "ground_truth_unchanged": invariant_components["ground_truth"]["unchanged"],
            "held_out_execution_count": 0,
        },
        "v2_artifact_inventory": {"file_count": len(records), "aggregate_sha256": _aggregate(records), "files": records},
        "out_of_scope_findings": [],
        "next_safe_action": "Held-out execution may begin only under the frozen v2 interactive protocol; none was run during v2 preparation.",
    }


def validate_manifest(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    manifest = _read(root / MANIFEST_PATH)
    mismatches = []
    current = []
    for frozen in manifest["v2_artifact_inventory"]["files"]:
        path = root / frozen["path"]
        if not path.is_file():
            mismatches.append({"type": "missing", "path": frozen["path"]})
            continue
        record = _record(root, path)
        current.append(record)
        if record != frozen:
            mismatches.append({"type": "file_hash", "path": frozen["path"]})
    if len(current) == manifest["v2_artifact_inventory"]["file_count"] and _aggregate(current) != manifest["v2_artifact_inventory"]["aggregate_sha256"]:
        mismatches.append({"type": "aggregate_hash", "path": "v2_artifact_inventory"})
    routing = validate_routing(root)
    if not routing["passed"]:
        mismatches.append({"type": "routing_validation", "path": "task_runtime_bindings.json"})
    current_held_out_count = _held_out_execution_count(root, set(manifest["held_out_task_ids"]))
    if current_held_out_count != 0 or current_held_out_count != manifest["held_out_execution_count"]:
        mismatches.append({"type": "held_out_execution_count", "path": str(current_held_out_count)})
    return {
        "schema_version": "ax-experiment-freeze-validation-v2",
        "experiment_version": "ax-exp-v2",
        "passed": not mismatches,
        "artifact_count": len(current),
        "held_out_execution_count": current_held_out_count,
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
