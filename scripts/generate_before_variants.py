"""Generate deterministic ax-exp-v2 accessibility-defect runtime variants.

This is a static dataset operation. It never invokes Kiro, an MCP server, or a
benchmark task. The frozen v1 task-to-defect artifact supplies task/source
relevance; this v2 artifact defines the previously absent injection operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity, validate_runtime_resource_leakage
from ax_scanner.models import LiveLLMStatus
from ax_scanner.scanner import scan_folder
from readiness_score import calculate_readiness_score


ROOT = Path(__file__).resolve().parents[1]
CEILING_ROOT = Path("sample_data/ceiling_company")
VARIANT_ROOT = Path("sample_data/before_variants")
GENERATED_ROOT = Path("experiment/v2/runtime")
DEV_TASK_IDS = {
    "O01_CUSTOMER_COUNT", "O05_HIGHEST_AVAILABLE_STOCK", "C01_HANBIT_AUGUST_TOTAL",
    "C04_YUNSEONG_LAST_ORDER", "C07_DAON_TOP_ORDER_PRODUCT",
}
CORRUPTION_PREFIX = bytes.fromhex("fffefbff")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _corrupt_bytes(relative_path: str) -> bytes:
    return CORRUPTION_PREFIX + hashlib.sha256(relative_path.encode("utf-8")).digest()


def _held_out(root: Path) -> list[str]:
    tasks = _read(root / "benchmark_tasks.json")["tasks"]
    return [task["task_id"] for task in tasks if task["task_id"] not in DEV_TASK_IDS]


def _variant_definitions(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    held_out = set(_held_out(root))
    defects = _read(root / "task_to_defect_manifest.json")
    controls = _read(root / "control_sources.json")
    control_ids = sorted(held_out.intersection(controls["control_task_ids"]))
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for entry in defects["task_defects"]:
        if entry["task_id"] in held_out:
            grouped[tuple(sorted(entry["affected_sources"]))].append(entry)
    variants = []
    for sources, entries in sorted(grouped.items()):
        key = hashlib.sha256("\0".join(sources).encode("utf-8")).hexdigest()[:12]
        variants.append({
            "variant_id": f"AXV2_ACCESSIBILITY_{key.upper()}",
            "runtime_profile": f"before-accessibility-{key}",
            "affected_task_ids": sorted(entry["task_id"] for entry in entries),
            "frozen_defect_ids": sorted(entry["primary_defect_id"] for entry in entries),
            "affected_sources": list(sources),
        })
    treated = sorted(task for variant in variants for task in variant["affected_task_ids"])
    if len(treated) != 12 or len(control_ids) != 4 or set(treated) & set(control_ids):
        raise ValueError(f"unexpected v2 treated/control split: treated={treated}, controls={control_ids}")
    if set(treated) | set(control_ids) != held_out:
        raise ValueError("v2 treated/control split does not cover all held-out tasks")
    return variants, control_ids


def _manifest(
    dataset_id: str,
    profile: str,
    source_root: Path,
    source_root_relative: Path,
) -> dict[str, Any]:
    files = []
    for path in sorted(p for p in source_root.rglob("*") if p.is_file()):
        files.append({
            "relative_path": path.relative_to(source_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return {
        "schema_version": "ax-before-dataset-manifest-v2",
        "experiment_version": "ax-exp-v2",
        "dataset_id": dataset_id,
        "condition": "Before",
        "runtime_profile": profile,
        "source_root": source_root_relative.as_posix(),
        "file_count": len(files),
        "files": files,
    }


def _scan(source_root: Path):
    previous = os.environ.get("AX_SCANNER_PDF_ENHANCEMENTS")
    os.environ["AX_SCANNER_PDF_ENHANCEMENTS"] = "off"
    try:
        return scan_folder(
            source_root,
            live_llm=LiveLLMStatus(
                status="LIVE_LLM_PENDING",
                reason="Static ax-exp-v2 variant generation; no live LLM is invoked.",
            ),
        )
    finally:
        if previous is None:
            os.environ.pop("AX_SCANNER_PDF_ENHANCEMENTS", None)
        else:
            os.environ["AX_SCANNER_PDF_ENHANCEMENTS"] = previous


def _portable_scan_report(report: Any, source_root: Path, source_root_relative: Path):
    """Replace parser-emitted source paths with repository-relative POSIX paths."""
    files = []
    for record in report.files:
        parse_error = record.parse_error
        if parse_error is not None:
            source_path = source_root / record.relative_path
            portable_path = (source_root_relative / record.relative_path).as_posix()
            candidates = {
                str(source_path),
                source_path.as_posix(),
                str(source_path.resolve()),
                source_path.resolve().as_posix(),
            }
            for candidate in sorted(candidates, key=len, reverse=True):
                parse_error = parse_error.replace(candidate, portable_path)
            root_tokens = {
                str(source_root),
                source_root.as_posix(),
                str(source_root.resolve()),
                source_root.resolve().as_posix(),
            }
            if any(token and token in parse_error for token in root_tokens):
                raise ValueError(
                    f"parser error retains an absolute source root: {record.relative_path}"
                )
        files.append(record.model_copy(update={"parse_error": parse_error}))
    return report.model_copy(update={"files": files})


def _frozen_modified_time_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"frozen modified_at must include a timezone: {value}")
    return int(parsed.timestamp() * 1_000_000_000)


def _copy_and_transform(
    ceiling_root: Path,
    target_root: Path,
    sources: list[str],
    ceiling_report: dict[str, Any],
) -> None:
    shutil.copytree(ceiling_root, target_root, copy_function=shutil.copy2)
    frozen_times = {
        record["relative_path"]: _frozen_modified_time_ns(record["modified_at"])
        for record in ceiling_report["files"]
    }
    copied_paths = {
        path.relative_to(target_root).as_posix()
        for path in target_root.rglob("*")
        if path.is_file()
    }
    if copied_paths != set(frozen_times):
        raise ValueError("ceiling files and frozen scan timestamps do not match")
    for relative, modified_ns in frozen_times.items():
        os.utime(target_root / relative, ns=(modified_ns, modified_ns))
    for relative in sources:
        target = target_root / relative
        target.write_bytes(_corrupt_bytes(relative))
        modified_ns = frozen_times[relative]
        os.utime(target, ns=(modified_ns, modified_ns))


def _validate_variant(
    root: Path,
    variant: dict[str, Any],
    source_root: Path,
    scan_path: Path,
    manifest_path: Path,
    ceiling_report: dict[str, Any],
    ceiling_readiness: dict[str, Any],
    protected: dict[str, str],
) -> dict[str, Any]:
    report = _read(scan_path)
    readiness = calculate_readiness_score(report)
    ceiling_files = {item["relative_path"]: item for item in ceiling_report["files"]}
    current_files = {item["relative_path"]: item for item in report["files"]}
    changed = sorted(path for path in ceiling_files if ceiling_files[path]["sha256"] != current_files[path]["sha256"])
    errors = sorted(path for path, item in current_files.items() if item["parse_status"] == "ERROR")
    expected = sorted(variant["affected_sources"])
    unchanged_dimensions = ["completeness", "redundancy", "timeliness", "safety"]
    dimension_diff = {
        name: {"ceiling": ceiling_readiness["dimensions"][name], "before": readiness["dimensions"][name]}
        for name in ceiling_readiness["dimensions"]
    }
    protected_mismatches = [path for path, digest in protected.items() if _sha256(source_root / path) != digest]
    checks = {
        "only_affected_source_bytes_changed": changed == expected,
        "affected_sources_are_parser_errors": errors == expected,
        "file_inventory_preserved": set(current_files) == set(ceiling_files),
        "accessibility_decreased": readiness["dimensions"]["accessibility"] < ceiling_readiness["dimensions"]["accessibility"],
        "other_readiness_dimensions_unchanged": all(
            readiness["dimensions"][name] == ceiling_readiness["dimensions"][name]
            for name in unchanged_dimensions
        ),
        "protected_sources_unchanged": not protected_mismatches,
    }
    config_path = root / "runtime_datasets.json"
    dataset = resolve_runtime_dataset(variant["runtime_profile"], config_path)
    identity = runtime_identity(dataset)
    leakage = validate_runtime_resource_leakage(dataset)
    checks["runtime_leakage_free"] = leakage["passed"]
    if not all(checks.values()):
        raise ValueError(f"variant validation failed for {variant['variant_id']}: {checks}")
    return {
        "schema_version": "ax-before-variant-diff-v2",
        "variant_id": variant["variant_id"],
        "runtime_profile": variant["runtime_profile"],
        "checks": checks,
        "changed_source_paths": changed,
        "parser_error_paths": errors,
        "protected_source_mismatches": protected_mismatches,
        "readiness": {
            "ceiling_score": ceiling_readiness["readiness_score"],
            "before_score": readiness["readiness_score"],
            "dimension_diff": dimension_diff,
        },
        "runtime_identity": identity,
        "runtime_identity_sha256": _canonical_hash(identity),
        "runtime_leakage": leakage,
        "dataset_manifest_sha256": _sha256(manifest_path),
        "scan_report_sha256": _sha256(scan_path),
    }


def generate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    ceiling_root = root / CEILING_ROOT
    ceiling_report = _read(root / "ceiling_scan_report.json")
    ceiling_readiness = calculate_readiness_score(ceiling_report)
    ceiling_identity_before = runtime_identity(resolve_runtime_dataset("ceiling", root / "runtime_datasets.json"))
    ceiling_manifest_hash = _sha256(root / "dataset_manifest.json")
    variants, control_ids = _variant_definitions(root)
    protected = _read(root / "control_sources.json")["protected_source_sha256"]

    config = _read(root / "runtime_datasets.json")
    config["profiles"] = {key: value for key, value in config["profiles"].items() if not key.startswith("before-")}

    generated = root / GENERATED_ROOT
    generated.mkdir(parents=True, exist_ok=True)
    specs = []
    for variant in variants:
        profile = variant["runtime_profile"]
        dataset_id = f"hanbit-distribution-{profile}-v2"
        source_rel = VARIANT_ROOT / profile
        scan_rel = GENERATED_ROOT / f"{profile}-scan-report.json"
        manifest_rel = GENERATED_ROOT / f"{profile}-dataset-manifest.json"
        diff_rel = GENERATED_ROOT / f"{profile}-diff.json"
        source_root = root / source_rel
        if source_root.exists():
            shutil.rmtree(source_root)
        _copy_and_transform(
            ceiling_root,
            source_root,
            variant["affected_sources"],
            ceiling_report,
        )
        report = _portable_scan_report(_scan(source_root), source_root, source_rel)
        _write(root / scan_rel, report.model_dump(mode="json"))
        manifest = _manifest(dataset_id, profile, source_root, source_rel)
        _write(root / manifest_rel, manifest)
        config["profiles"][profile] = {
            "dataset_name": dataset_id,
            "source_root": source_rel.as_posix(),
            "scan_report": scan_rel.as_posix(),
            "dataset_manifest": manifest_rel.as_posix(),
        }
        specs.append({
            **variant,
            "target_readiness_dimension": "accessibility",
            "defect_concept": "source remains inventoried but cannot be parsed by its declared-format parser",
            "transformation_operator": "replace_file_bytes_with_path_keyed_invalid_payload_v1",
            "transformation_parameters": {
                "payload_prefix_hex": CORRUPTION_PREFIX.hex(),
                "payload_suffix": "sha256(relative_path).digest()",
                "preserve_relative_path": True,
                "preserve_modified_timestamp": True,
            },
            "source_ceiling_sha256": {path: _sha256(ceiling_root / path) for path in variant["affected_sources"]},
            "generated_before_sha256": {path: _sha256(source_root / path) for path in variant["affected_sources"]},
            "expected_invariant": {
                "file_inventory_preserved": True,
                "target_parse_status": "ERROR",
                "accessibility_decreases": True,
                "completeness_redundancy_timeliness_safety_unchanged": True,
                "protected_control_sources_byte_identical": True,
            },
            "provenance": {
                "frozen_mapping": "task_to_defect_manifest.json",
                "ceiling_manifest": "dataset_manifest.json",
                "generator": "scripts/generate_before_variants.py",
            },
            "dataset_manifest": manifest_rel.as_posix(),
            "scan_report": scan_rel.as_posix(),
            "diff_receipt": diff_rel.as_posix(),
        })

    _write(root / "runtime_datasets.json", config)
    spec_payload = {
        "schema_version": "ax-defect-injection-spec-v2",
        "experiment_version": "ax-exp-v2",
        "source_manifest_schema": "ax-task-to-defect-v1",
        "design_status": "PRE_REGISTERED_BEFORE_HELD_OUT_EXECUTION",
        "operator_rationale": (
            "The frozen source_readiness label identifies relevant sources but not an operator. "
            "v2 operationalizes it as an accessibility defect: retain each source in inventory and "
            "make its declared-format parser fail. This avoids treating source_readiness as deletion."
        ),
        "variants": specs,
    }
    _write(root / "DEFECT_INJECTION_SPEC_V2.json", spec_payload)

    bindings = []
    variant_by_task = {task: variant for variant in specs for task in variant["affected_task_ids"]}
    for task_id in _held_out(root):
        if task_id in control_ids:
            bindings.append({
                "task_id": task_id,
                "task_group": "control",
                "defect_variant_id": None,
                "runtime_profiles": {"Before": "ceiling", "Ceiling": "ceiling"},
                "pre_registered_interpretation": "negative control with byte-identical evidence across condition labels",
            })
        else:
            variant = variant_by_task[task_id]
            bindings.append({
                "task_id": task_id,
                "task_group": "treated",
                "defect_variant_id": variant["variant_id"],
                "runtime_profiles": {"Before": variant["runtime_profile"], "Ceiling": "ceiling"},
                "pre_registered_interpretation": "task-relevant single-defect Before versus frozen Ceiling",
            })
    _write(root / "task_runtime_bindings.json", {
        "schema_version": "ax-task-runtime-bindings-v2",
        "experiment_version": "ax-exp-v2",
        "run_design": "16 tasks x 2 conditions x 2 repetitions = 64 runs",
        "treated_task_count": 12,
        "control_task_count": 4,
        "bindings": bindings,
    })

    receipts = []
    for variant in specs:
        receipt = _validate_variant(
            root, variant, root / VARIANT_ROOT / variant["runtime_profile"],
            root / variant["scan_report"], root / variant["dataset_manifest"],
            ceiling_report, ceiling_readiness, protected,
        )
        _write(root / variant["diff_receipt"], receipt)
        receipts.append(receipt)

    ceiling_identity_after = runtime_identity(resolve_runtime_dataset("ceiling", root / "runtime_datasets.json"))
    if ceiling_identity_after != ceiling_identity_before or _sha256(root / "dataset_manifest.json") != ceiling_manifest_hash:
        raise ValueError("Ceiling identity or manifest changed during Before generation")
    summary = {
        "schema_version": "ax-before-generation-summary-v2",
        "experiment_version": "ax-exp-v2",
        "passed": True,
        "treated_task_count": 12,
        "control_task_count": 4,
        "unique_defect_variant_count": len(specs),
        "deterministic_operator": True,
        "all_variant_checks_passed": all(all(r["checks"].values()) for r in receipts),
        "runtime_leakage_violations": sum(len(r["runtime_leakage"]["violations"]) for r in receipts),
        "ceiling_identity_unchanged": True,
        "ceiling_runtime_identity": ceiling_identity_after,
    }
    _write(root / GENERATED_ROOT / "generation-summary.json", summary)
    return summary


def verify_deterministic(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    config_path = root / "runtime_datasets.json"
    original_config = config_path.read_bytes()

    def v2_runtime_projection() -> dict[str, Any]:
        config = _read(config_path)
        return {
            "schema_version": config["schema_version"],
            "profiles": {
                key: value
                for key, value in config["profiles"].items()
                if key == "ceiling" or key.startswith("before-accessibility-")
            },
        }

    before_runtime = v2_runtime_projection()
    tracked = [root / "DEFECT_INJECTION_SPEC_V2.json", root / "task_runtime_bindings.json"]
    tracked += sorted((root / VARIANT_ROOT).rglob("*"))
    tracked += sorted((root / GENERATED_ROOT).rglob("*"))
    before = {path.relative_to(root).as_posix(): _sha256(path) for path in tracked if path.is_file()}
    try:
        generate(root)
        after_runtime = v2_runtime_projection()
    finally:
        # Product/demo profiles may legitimately be added after ax-exp-v2 was
        # frozen.  Determinism checks the experiment-owned projection and must
        # not rewrite the shared runtime registry as a test side effect.
        config_path.write_bytes(original_config)
    after_paths = [root / "DEFECT_INJECTION_SPEC_V2.json", root / "task_runtime_bindings.json"]
    after_paths += sorted((root / VARIANT_ROOT).rglob("*"))
    after_paths += sorted((root / GENERATED_ROOT).rglob("*"))
    after = {path.relative_to(root).as_posix(): _sha256(path) for path in after_paths if path.is_file()}
    mismatches = set(before) ^ set(after) | {
        path for path in before.keys() & after.keys() if before[path] != after[path]
    }
    if before_runtime != after_runtime:
        mismatches.add("runtime_datasets.json#ax-exp-v2-projection")
    return {
        "passed": not mismatches,
        "file_count": len(after) + 1,
        "mismatches": sorted(mismatches),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--verify-deterministic", action="store_true")
    args = parser.parse_args()
    result = verify_deterministic(args.root) if args.verify_deterministic else generate(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
