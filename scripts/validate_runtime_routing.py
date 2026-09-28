"""Static ax-exp-v2 routing validation with zero Kiro or held-out calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity, validate_runtime_resource_leakage
from scripts.runtime_binding import resolve_runtime_binding


ROOT = Path(__file__).resolve().parents[1]
DEV_TASK_IDS = {
    "O01_CUSTOMER_COUNT", "O05_HIGHEST_AVAILABLE_STOCK", "C01_HANBIT_AUGUST_TOTAL",
    "C04_YUNSEONG_LAST_ORDER", "C07_DAON_TOP_ORDER_PRODUCT",
}
EXPECTED_TOOLS = [
    "@ax-tools/search_documents", "@ax-tools/read_document",
    "@ax-tools/lookup_value", "@ax-tools/query_table",
]
EXPECTED_PROMPT_HASH = "dc783a41a5b06eb871ada33be7dd21aec2e4106757a40921ddf59fcf81176fc8"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _held_out_execution_count(root: Path, held_out: set[str]) -> int:
    count = 0
    for path in (root / "artifacts").rglob("metadata.json"):
        metadata = _read(path)
        if metadata.get("task_id") in held_out and metadata.get("run_status") not in {None, "NOT_RUN", "PREPARED"}:
            count += 1
    blind = _read(root / "blind_gate_results.json")
    count += sum(
        run.get("task_id") in held_out and run.get("run_status") == "RECORDED"
        for run in blind.get("runs", [])
    )
    return count


def validate_routing(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    benchmark = _read(root / "benchmark_tasks.json")
    held_out = [task["task_id"] for task in benchmark["tasks"] if task["task_id"] not in DEV_TASK_IDS]
    bindings_payload = _read(root / "task_runtime_bindings.json")
    binding_entries = {entry["task_id"]: entry for entry in bindings_payload["bindings"]}
    spec = _read(root / "DEFECT_INJECTION_SPEC_V2.json")
    variant_by_id = {item["variant_id"]: item for item in spec["variants"]}
    defects = _read(root / "task_to_defect_manifest.json")
    frozen_defects = {entry["task_id"]: entry for entry in defects["task_defects"]}
    controls = set(_read(root / "control_sources.json")["control_task_ids"]) & set(held_out)
    ceiling = runtime_identity(resolve_runtime_dataset("ceiling", root / "runtime_datasets.json"))
    frozen_ceiling = _read(root / "experiment/frozen/ax-exp-v1-manifest.json")["ceiling_runtime_identity"]

    rows = []
    mismatches: list[dict[str, str]] = []
    leakage_violations = []
    identities: dict[str, dict[str, Any]] = {}
    for task_id in held_out:
        for condition in ("Before", "Ceiling"):
            binding = resolve_runtime_binding(task_id, condition, root / "task_runtime_bindings.json")
            dataset = resolve_runtime_dataset(binding.runtime_profile, root / "runtime_datasets.json")
            identity = runtime_identity(dataset)
            identities.setdefault(binding.runtime_profile, identity)
            leakage = validate_runtime_resource_leakage(dataset)
            leakage_violations.extend(
                {"task_id": task_id, "condition": condition, **violation}
                for violation in leakage["violations"]
            )
            if identity["dataset_profile"] != binding.runtime_profile:
                mismatches.append({"task_id": task_id, "condition": condition, "reason": "profile_identity_mismatch"})
            rows.append({
                "task_id": task_id,
                "task_group": binding.task_group,
                "condition": condition,
                "expected_runtime_profile": binding.runtime_profile,
                "actual_runtime_profile": identity["dataset_profile"],
                "runtime_identity_sha256": hashlib.sha256(
                    json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "leakage_passed": leakage["passed"],
            })

    treated = set(held_out) - controls
    for task_id in treated:
        entry = binding_entries[task_id]
        variant = variant_by_id.get(entry["defect_variant_id"])
        frozen = frozen_defects.get(task_id)
        if not variant or not frozen:
            mismatches.append({"task_id": task_id, "condition": "Before", "reason": "missing_frozen_or_v2_defect_mapping"})
            continue
        if sorted(variant["affected_sources"]) != sorted(frozen["affected_sources"]):
            mismatches.append({"task_id": task_id, "condition": "Before", "reason": "affected_source_mapping_mismatch"})
        if entry["runtime_profiles"]["Before"] == "ceiling":
            mismatches.append({"task_id": task_id, "condition": "Before", "reason": "treated_before_is_ceiling"})
    for task_id in controls:
        entry = binding_entries[task_id]
        before = identities[entry["runtime_profiles"]["Before"]]
        after = identities[entry["runtime_profiles"]["Ceiling"]]
        if entry["defect_variant_id"] is not None or before != after:
            mismatches.append({"task_id": task_id, "condition": "Before", "reason": "control_not_evidence_equivalent"})

    config = _read(root / ".kiro/agents/ax-evaluation.json")
    prompt_hash = hashlib.sha256(config["prompt"].encode("utf-8")).hexdigest()
    invariant_checks = {
        "held_out_task_count_16": len(held_out) == 16,
        "binding_coverage_16": set(binding_entries) == set(held_out),
        "treated_task_count_12": len(treated) == 12,
        "control_task_count_4": len(controls) == 4,
        "route_count_32": len(rows) == 32,
        "ceiling_identity_unchanged": ceiling == frozen_ceiling,
        "prompt_hash_unchanged": prompt_hash == EXPECTED_PROMPT_HASH,
        "model_unchanged": config.get("model") == "claude-sonnet-5",
        "four_tool_surface_unchanged": config.get("tools") == EXPECTED_TOOLS and config.get("allowedTools") == EXPECTED_TOOLS,
        "runtime_profile_mismatches_zero": not mismatches,
        "runtime_leakage_violations_zero": not leakage_violations,
        "held_out_execution_count_zero": _held_out_execution_count(root, set(held_out)) == 0,
    }
    held_out_execution_count = _held_out_execution_count(root, set(held_out))
    return {
        "schema_version": "ax-runtime-routing-validation-v2",
        "experiment_version": "ax-exp-v2",
        "passed": all(invariant_checks.values()),
        "held_out_execution_count": held_out_execution_count,
        "summary": {
            "held_out_tasks_checked": f"{len(held_out)}/16",
            "treated_tasks": len(treated),
            "control_tasks": len(controls),
            "before_bindings": sum(row["condition"] == "Before" for row in rows),
            "ceiling_bindings": sum(row["condition"] == "Ceiling" for row in rows),
            "unique_defect_variants": len(variant_by_id),
            "runtime_identity_mismatches": len(mismatches),
            "leakage_violations": len(leakage_violations),
        },
        "invariant_checks": invariant_checks,
        "mismatches": mismatches,
        "leakage_violations": leakage_violations,
        "routes": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_routing(args.root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
