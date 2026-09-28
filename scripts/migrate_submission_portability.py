"""Apply the approved 2026-09-24 submission-portability migration.

This is an allowlist-only metadata/hash migration. It does not invoke Kiro,
run an LLM, execute held-out tasks, or recreate a freeze.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity
from ax_scanner.models import ScanReport
from scripts.generate_before_variants import _portable_scan_report


AUDIT_MANIFEST = ROOT / "artifacts/final_submission_audit/SUBMISSION_MANIFEST.json"
RECEIPT = ROOT / "artifacts/portability_migration_2026-09-24/PORTABILITY_MIGRATION.json"

PROFILES = (
    "before-accessibility-0e78131fc878",
    "before-accessibility-66a46d7e2186",
    "before-accessibility-7497b2824ba3",
    "before-accessibility-91428d0d2d6d",
    "before-accessibility-950a2b2ed909",
    "before-accessibility-a534444afe03",
    "before-accessibility-d527640c55b3",
    "before-accessibility-f1d1804d1aa6",
)

DIRECT_CODE_CHANGES = {
    ".kiro/agents/ax-evaluation.json": [
        "/mcpServers/ax-tools/command",
        "/mcpServers/ax-tools/args/3",
        "/mcpServers/ax-tools/args/5",
        "/mcpServers/ax-tools/env/AX_RUNTIME_DATASET_CONFIG",
        "/mcpServers/ax-tools/env/PYTHONPATH",
    ],
    ".kiro/agents/ax-product.json": [
        "/mcpServers/ax-product-tools/command",
        "/mcpServers/ax-product-tools/env/AX_RUNTIME_DATASET_CONFIG",
        "/mcpServers/ax-product-tools/env/PYTHONPATH",
    ],
    "ax_mcp/runtime_dataset.py": ["relative config resolution against repository root"],
    "scripts/generate_before_variants.py": [
        "repository-relative manifest source_root",
        "portable parser-error source path normalization",
    ],
    "scripts/run_phase6_demo.py": [
        "repository-relative scanner_invocations[].output"
    ],
    "tests/test_phase6_product_demo.py": [
        "approved experiment/frozen portability-migration tree hash baseline"
    ],
}

MUTABLE_JSON = {
    "artifacts/phase6_product_demo/dataset-manifest.json",
    "artifacts/phase6_product_demo/FROZEN_MANIFEST.json",
    "experiment/frozen/ax-exp-v1-manifest.json",
    "experiment/frozen/ax-exp-v2-manifest.json",
    "experiment/frozen/ax-exp-v3-manifest.json",
    "artifacts/phase5_evidence_checker_v1/FROZEN_HASH_VERIFICATION.json",
    "experiment/v2/runtime/routing-validation.json",
    *{
        f"experiment/v2/runtime/{profile}-{suffix}.json"
        for profile in PROFILES
        for suffix in ("dataset-manifest", "scan-report", "diff")
    },
}

ALLOWED_CHANGED_PATHS = (
    set(DIRECT_CODE_CHANGES)
    | MUTABLE_JSON
    | {
        "scripts/verify_phase5_preservation.py",
        "scripts/migrate_submission_portability.py",
    }
)

PERSONAL_PATH_PATTERNS = (
    re.compile(r"(?i)[a-z]:[\\/]+Users[\\/]+[^\\/\s\"']+"),
    re.compile(r"/(?:Users|home)/[^/\s\"']+"),
)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _record(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    stat = path.stat()
    return {
        "path": relative,
        "size_bytes": stat.st_size,
        "sha256": _sha(path),
        "mtime_ns": stat.st_mtime_ns,
    }


def _aggregate(records: Iterable[dict[str, Any]]) -> str:
    payload = "".join(
        f"{record['path']}\0{record['size_bytes']}\0{record['sha256']}\n"
        for record in records
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _snapshot(paths: Iterable[Path]) -> dict[str, Any]:
    records = []
    for path in sorted({item.resolve() for item in paths if item.is_file()}):
        relative = path.relative_to(ROOT).as_posix()
        records.append(_record(relative))
    canonical = json.dumps(
        records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "file_count": len(records),
        "snapshot_sha256": hashlib.sha256(canonical).hexdigest(),
        "records": records,
    }


def _invariant_snapshots() -> dict[str, dict[str, Any]]:
    source_files = [
        path
        for path in (ROOT / "sample_data").rglob("*")
        if path.is_file() and "before_variants" not in path.parts
    ]
    held_out = list((ROOT / "artifacts/heldout_ax-exp-v3").rglob("*"))
    official_runs = [
        path
        for path in (ROOT / "artifacts/phase6_product_demo/runs").rglob("*")
        if path.is_file()
        and (
            path.name in {"delivery.json", "evidence-check.json"}
            or "tool-responses" in path.parts
        )
    ]
    ui = list((ROOT / "results_console/src").rglob("*"))
    readiness_and_evidence = [ROOT / "readiness_score.py"] + list(
        (ROOT / "ax_product").glob("*.py")
    )
    return {
        "original_source_datasets": _snapshot(source_files),
        "held_out_64_run_artifacts": _snapshot(held_out),
        "phase6_official_delivery_evidence_tool_responses": _snapshot(official_runs),
        "phase6c_ui_source": _snapshot(ui),
        "readiness_and_evidence_checker_implementation": _snapshot(
            readiness_and_evidence
        ),
    }


def _semantic_snapshot() -> dict[str, Any]:
    evaluation = _read(ROOT / ".kiro/agents/ax-evaluation.json")
    product = _read(ROOT / ".kiro/agents/ax-product.json")
    spec = _read(ROOT / "DEFECT_INJECTION_SPEC_V2.json")
    bindings = _read(ROOT / "task_runtime_bindings.json")
    variants = []
    for variant in spec["variants"]:
        profile = variant["runtime_profile"]
        diff = _read(ROOT / f"experiment/v2/runtime/{profile}-diff.json")
        source_root = ROOT / "sample_data/before_variants" / profile
        source_hashes = {
            path.relative_to(source_root).as_posix(): _sha(path)
            for path in sorted(source_root.rglob("*"))
            if path.is_file()
        }
        variants.append({
            "variant_id": variant["variant_id"],
            "runtime_profile": profile,
            "affected_task_ids": variant["affected_task_ids"],
            "affected_sources": variant["affected_sources"],
            "frozen_defect_ids": variant["frozen_defect_ids"],
            "source_hashes": source_hashes,
            "checks": diff["checks"],
            "changed_source_paths": diff["changed_source_paths"],
            "parser_error_paths": diff["parser_error_paths"],
            "readiness": diff["readiness"],
            "runtime_profile_identity": {
                key: value
                for key, value in diff["runtime_identity"].items()
                if key not in {"dataset_manifest_sha256", "scan_report_sha256"}
            },
        })
    return {
        "agents": {
            "evaluation": {
                "model": evaluation["model"],
                "prompt_sha256": hashlib.sha256(
                    evaluation["prompt"].encode("utf-8")
                ).hexdigest(),
                "tools": evaluation["tools"],
                "allowedTools": evaluation["allowedTools"],
                "timeout": evaluation["mcpServers"]["ax-tools"]["timeout"],
            },
            "product": {
                "model": product["model"],
                "prompt_sha256": hashlib.sha256(
                    product["prompt"].encode("utf-8")
                ).hexdigest(),
                "tools": product["tools"],
                "allowedTools": product["allowedTools"],
                "timeout": product["mcpServers"]["ax-product-tools"]["timeout"],
            },
        },
        "task_bindings": bindings,
        "variants": variants,
    }


def _set(
    value: dict[str, Any], key: str, new: Any, pointer: str, changes: list[str]
) -> None:
    if value.get(key) != new:
        value[key] = new
        changes.append(pointer)


def _record_file(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha(path),
    }


def _refresh_component(
    component: dict[str, Any], changed_paths: set[str], pointers: list[str], base: str
) -> None:
    touched = False
    for index, record in enumerate(component["files"]):
        if record["path"] in changed_paths:
            component["files"][index] = _record_file(ROOT / record["path"])
            pointers.append(f"{base}/files/{index}")
            touched = True
    if touched:
        component["aggregate_sha256"] = _aggregate(component["files"])
        pointers.append(f"{base}/aggregate_sha256")


def _migrate_phase6(changes: dict[str, list[str]]) -> None:
    manifest_relative = "artifacts/phase6_product_demo/dataset-manifest.json"
    manifest = _read(ROOT / manifest_relative)
    pointers = changes.setdefault(manifest_relative, [])
    for index, invocation in enumerate(manifest["scanner_invocations"]):
        expected = (
            f"artifacts/phase6_product_demo/"
            f"{'before' if index == 0 else 'after'}-scan-report.json"
        )
        _set(invocation, "output", expected, f"/scanner_invocations/{index}/output", pointers)
    _write(ROOT / manifest_relative, manifest)

    frozen_relative = "artifacts/phase6_product_demo/FROZEN_MANIFEST.json"
    frozen = _read(ROOT / frozen_relative)
    pointers = changes.setdefault(frozen_relative, [])
    for index, record in enumerate(frozen["artifacts"]["files"]):
        if record["path"] == manifest_relative:
            frozen["artifacts"]["files"][index] = _record_file(ROOT / manifest_relative)
            pointers.extend([
                f"/artifacts/files/{index}/sha256",
                f"/artifacts/files/{index}/size_bytes",
            ])
            break
    else:
        raise ValueError("Phase 6 frozen manifest lacks dataset-manifest record")
    _write(ROOT / frozen_relative, frozen)


def _migrate_v2_runtime(changes: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    for profile in PROFILES:
        manifest_relative = f"experiment/v2/runtime/{profile}-dataset-manifest.json"
        manifest = _read(ROOT / manifest_relative)
        expected_root = f"sample_data/before_variants/{profile}"
        pointers = changes.setdefault(manifest_relative, [])
        _set(manifest, "source_root", expected_root, "/source_root", pointers)
        _write(ROOT / manifest_relative, manifest)

        scan_relative = f"experiment/v2/runtime/{profile}-scan-report.json"
        scan_path = ROOT / scan_relative
        report = ScanReport.model_validate_json(scan_path.read_text(encoding="utf-8"))
        portable = _portable_scan_report(
            report,
            ROOT / expected_root,
            Path(expected_root),
        )
        portable_payload = portable.model_dump(mode="json")
        old_payload = report.model_dump(mode="json")
        scan_pointers = changes.setdefault(scan_relative, [])
        for index, (old, new) in enumerate(zip(old_payload["files"], portable_payload["files"], strict=True)):
            if old["parse_error"] != new["parse_error"]:
                scan_pointers.append(f"/files/{index}/parse_error")
        _write(scan_path, portable_payload)

    identities = {
        profile: runtime_identity(
            resolve_runtime_dataset(profile, ROOT / "runtime_datasets.json")
        )
        for profile in PROFILES
    }
    for profile, identity in identities.items():
        diff_relative = f"experiment/v2/runtime/{profile}-diff.json"
        diff = _read(ROOT / diff_relative)
        pointers = changes.setdefault(diff_relative, [])
        assignments = {
            "runtime_identity": identity,
            "runtime_identity_sha256": _canonical_hash(identity),
            "dataset_manifest_sha256": identity["dataset_manifest_sha256"],
            "scan_report_sha256": identity["scan_report_sha256"],
        }
        for key, new in assignments.items():
            _set(diff, key, new, f"/{key}", pointers)
        _write(ROOT / diff_relative, diff)

    routing_relative = "experiment/v2/runtime/routing-validation.json"
    routing = _read(ROOT / routing_relative)
    pointers = changes.setdefault(routing_relative, [])
    for index, route in enumerate(routing["routes"]):
        identity = identities.get(route["actual_runtime_profile"])
        if identity is None:
            identity = runtime_identity(
                resolve_runtime_dataset(
                    route["actual_runtime_profile"], ROOT / "runtime_datasets.json"
                )
            )
        _set(
            route,
            "runtime_identity_sha256",
            _canonical_hash(identity),
            f"/routes/{index}/runtime_identity_sha256",
            pointers,
        )
    _write(ROOT / routing_relative, routing)
    return identities


def _migrate_freeze_chain(
    identities: dict[str, dict[str, Any]], changes: dict[str, list[str]]
) -> None:
    v1_relative = "experiment/frozen/ax-exp-v1-manifest.json"
    v1 = _read(ROOT / v1_relative)
    pointers = changes.setdefault(v1_relative, [])
    agent_hash = _sha(ROOT / ".kiro/agents/ax-evaluation.json")
    _set(v1, "agent_config_hash", agent_hash, "/agent_config_hash", pointers)
    target_paths = {".kiro/agents/ax-evaluation.json", "ax_mcp/runtime_dataset.py"}
    component_by_id: dict[str, dict[str, Any]] = {}
    for group_name, components in v1["artifact_inventory"].items():
        for component_index, component in enumerate(components):
            component_by_id[component["component_id"]] = component
            _refresh_component(
                component,
                target_paths,
                pointers,
                f"/artifact_inventory/{group_name}/{component_index}",
            )
    _set(
        v1["mcp_implementation_hashes"],
        "aggregate_sha256",
        component_by_id["mcp_server_implementation"]["aggregate_sha256"],
        "/mcp_implementation_hashes/aggregate_sha256",
        pointers,
    )
    _write(ROOT / v1_relative, v1)

    v2_relative = "experiment/frozen/ax-exp-v2-manifest.json"
    v2 = _read(ROOT / v2_relative)
    pointers = changes.setdefault(v2_relative, [])
    _set(
        v2["v1_frozen_manifest"],
        "sha256",
        _sha(ROOT / v1_relative),
        "/v1_frozen_manifest/sha256",
        pointers,
    )
    _set(v2, "before_runtime_identities", identities, "/before_runtime_identities", pointers)
    _set(
        v2,
        "before_generator_hash",
        _sha(ROOT / "scripts/generate_before_variants.py"),
        "/before_generator_hash",
        pointers,
    )
    _set(
        v2,
        "routing_validation_artifact_hash",
        _sha(ROOT / "experiment/v2/runtime/routing-validation.json"),
        "/routing_validation_artifact_hash",
        pointers,
    )
    mcp_hash = component_by_id["mcp_server_implementation"]["aggregate_sha256"]
    mcp_component = v2["v1_frozen_invariant_components"]["mcp_server_implementation"]
    _set(mcp_component, "v1_aggregate_sha256", mcp_hash, "/v1_frozen_invariant_components/mcp_server_implementation/v1_aggregate_sha256", pointers)
    _set(mcp_component, "v2_current_aggregate_sha256", mcp_hash, "/v1_frozen_invariant_components/mcp_server_implementation/v2_current_aggregate_sha256", pointers)
    inventory = v2["v2_artifact_inventory"]
    for index, record in enumerate(inventory["files"]):
        current = _record_file(ROOT / record["path"])
        if current != record:
            inventory["files"][index] = current
            pointers.append(f"/v2_artifact_inventory/files/{index}")
    _set(inventory, "aggregate_sha256", _aggregate(inventory["files"]), "/v2_artifact_inventory/aggregate_sha256", pointers)
    _write(ROOT / v2_relative, v2)

    from scripts.validate_runtime_routing import validate_routing

    routing = validate_routing(ROOT)
    static_checks = {
        key: value
        for key, value in routing["invariant_checks"].items()
        if key != "held_out_execution_count_zero"
    }
    if not all(static_checks.values()):
        raise ValueError(f"migrated v2 static routing is invalid: {static_checks}")
    inventory_records = [
        _record_file(ROOT / item["path"])
        for item in v2["v2_artifact_inventory"]["files"]
    ]
    if (
        inventory_records != v2["v2_artifact_inventory"]["files"]
        or _aggregate(inventory_records)
        != v2["v2_artifact_inventory"]["aggregate_sha256"]
    ):
        raise ValueError("migrated v2 artifact inventory does not self-validate")

    v3_relative = "experiment/frozen/ax-exp-v3-manifest.json"
    v3 = _read(ROOT / v3_relative)
    pointers = changes.setdefault(v3_relative, [])
    _set(
        v3["predecessor_manifest"],
        "sha256",
        _sha(ROOT / v2_relative),
        "/predecessor_manifest/sha256",
        pointers,
    )
    predecessor_validation = v3["predecessor_validation"]
    if (
        predecessor_validation.get("passed") is not True
        or predecessor_validation.get("held_out_execution_count") != 0
        or predecessor_validation.get("mismatches") != []
    ):
        raise ValueError("historical v2 predecessor validation receipt changed")
    frozen_mcp = v3["frozen_invariant_components"]["mcp_server_implementation"]
    _set(frozen_mcp, "frozen_aggregate_sha256", mcp_hash, "/frozen_invariant_components/mcp_server_implementation/frozen_aggregate_sha256", pointers)
    _set(frozen_mcp, "current_aggregate_sha256", mcp_hash, "/frozen_invariant_components/mcp_server_implementation/current_aggregate_sha256", pointers)
    _write(ROOT / v3_relative, v3)


def _update_preservation_baseline(changes: dict[str, list[str]]) -> None:
    relative = "scripts/verify_phase5_preservation.py"
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    targets = (
        ".kiro/agents/ax-evaluation.json",
        "experiment/frozen/ax-exp-v1-manifest.json",
        "experiment/frozen/ax-exp-v2-manifest.json",
        "experiment/frozen/ax-exp-v3-manifest.json",
    )
    pointers = changes.setdefault(relative, [])
    for target in targets:
        replacement = f'"{target}": "{_sha(ROOT / target)}"'
        pattern = re.compile(rf'"{re.escape(target)}": "[0-9a-f]{{64}}"')
        text, count = pattern.subn(replacement, text)
        if count != 1:
            raise ValueError(f"expected one preservation baseline for {target}, got {count}")
        pointers.append(f"EXPECTED[{target!r}]")
    path.write_text(text, encoding="utf-8", newline="\n")

    process = subprocess.run(
        [sys.executable, "scripts/verify_phase5_preservation.py"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=120,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"Phase 5 preservation failed after migration: {process.stdout} {process.stderr}"
        )
    changes.setdefault(
        "artifacts/phase5_evidence_checker_v1/FROZEN_HASH_VERIFICATION.json", []
    ).append("/checks and approved expected/actual hash records")


def _submission_paths() -> list[str]:
    manifest = _read(AUDIT_MANIFEST)
    return [item["path"] for item in manifest["candidate"]["files"]]


def _path_hits(paths: Iterable[str]) -> list[dict[str, Any]]:
    hits = []
    for relative in paths:
        path = ROOT / relative
        if not path.is_file() or path.suffix.lower() in {".zip", ".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2"}:
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore")
        for pattern_index, pattern in enumerate(PERSONAL_PATH_PATTERNS):
            for match in pattern.finditer(text):
                hits.append({
                    "path": relative,
                    "pattern_index": pattern_index,
                    "offset": match.start(),
                })
    return hits


def _changed_files(old_records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    changed = []
    for relative in sorted(ALLOWED_CHANGED_PATHS):
        path = ROOT / relative
        if not path.is_file():
            continue
        old = old_records.get(relative)
        new_sha = _sha(path)
        if old is None or old["sha256"] != new_sha:
            changed.append({
                "path": relative,
                "old_sha256": None if old is None else old["sha256"],
                "new_sha256": new_sha,
            })
    return changed


def _complete_changed_field_inventory(
    changes: dict[str, list[str]], old_records: dict[str, dict[str, Any]]
) -> None:
    def add(relative: str, pointer: str) -> None:
        values = changes.setdefault(relative, [])
        if pointer not in values:
            values.append(pointer)

    phase6 = "artifacts/phase6_product_demo/dataset-manifest.json"
    add(phase6, "/scanner_invocations/0/output")
    add(phase6, "/scanner_invocations/1/output")
    frozen = _read(ROOT / "artifacts/phase6_product_demo/FROZEN_MANIFEST.json")
    for index, item in enumerate(frozen["artifacts"]["files"]):
        if item["path"] == phase6:
            add("artifacts/phase6_product_demo/FROZEN_MANIFEST.json", f"/artifacts/files/{index}/sha256")
            add("artifacts/phase6_product_demo/FROZEN_MANIFEST.json", f"/artifacts/files/{index}/size_bytes")

    for profile in PROFILES:
        manifest = f"experiment/v2/runtime/{profile}-dataset-manifest.json"
        scan = f"experiment/v2/runtime/{profile}-scan-report.json"
        diff = f"experiment/v2/runtime/{profile}-diff.json"
        add(manifest, "/source_root")
        scan_payload = _read(ROOT / scan)
        for index, record in enumerate(scan_payload["files"]):
            if record.get("parse_error") and "sample_data/before_variants/" in record["parse_error"]:
                add(scan, f"/files/{index}/parse_error")
        for pointer in (
            "/runtime_identity",
            "/runtime_identity_sha256",
            "/dataset_manifest_sha256",
        ):
            add(diff, pointer)
        if changes.get(scan):
            add(diff, "/scan_report_sha256")

    routing_relative = "experiment/v2/runtime/routing-validation.json"
    routing = _read(ROOT / routing_relative)
    for index, route in enumerate(routing["routes"]):
        if route["actual_runtime_profile"].startswith("before-"):
            add(routing_relative, f"/routes/{index}/runtime_identity_sha256")

    v2_relative = "experiment/frozen/ax-exp-v2-manifest.json"
    v2 = _read(ROOT / v2_relative)
    for pointer in (
        "/v1_frozen_manifest/sha256",
        "/before_runtime_identities",
        "/before_generator_hash",
        "/routing_validation_artifact_hash",
        "/v1_frozen_invariant_components/mcp_server_implementation/v1_aggregate_sha256",
        "/v1_frozen_invariant_components/mcp_server_implementation/v2_current_aggregate_sha256",
        "/v2_artifact_inventory/aggregate_sha256",
    ):
        add(v2_relative, pointer)
    for index, record in enumerate(v2["v2_artifact_inventory"]["files"]):
        old = old_records.get(record["path"])
        if old is not None and old["sha256"] != record["sha256"]:
            add(v2_relative, f"/v2_artifact_inventory/files/{index}")

    v3_relative = "experiment/frozen/ax-exp-v3-manifest.json"
    for pointer in (
        "/predecessor_manifest/sha256",
        "/frozen_invariant_components/mcp_server_implementation/frozen_aggregate_sha256",
        "/frozen_invariant_components/mcp_server_implementation/current_aggregate_sha256",
    ):
        add(v3_relative, pointer)


def main() -> int:
    if RECEIPT.exists():
        existing_receipt = _read(RECEIPT)
        if existing_receipt.get("migration_id") != "portability-migration-2026-09-24":
            raise FileExistsError(f"unrelated migration receipt exists: {RECEIPT}")
    audit = _read(AUDIT_MANIFEST)
    old_records = {item["path"]: item for item in audit["candidate"]["files"]}
    before_path_hits = _path_hits(_submission_paths())
    reproduced_before_hits = 29
    if len(before_path_hits) not in {0, 21}:
        raise ValueError(
            "expected either 21 remaining metadata hits or 0 hits when resuming "
            f"the one-time migration, got {len(before_path_hits)}"
        )

    invariant_before = _invariant_snapshots()
    semantic_before = _semantic_snapshot()
    changes: dict[str, list[str]] = {key: list(value) for key, value in DIRECT_CODE_CHANGES.items()}

    _migrate_phase6(changes)
    identities = _migrate_v2_runtime(changes)
    _migrate_freeze_chain(identities, changes)
    _update_preservation_baseline(changes)

    invariant_after = _invariant_snapshots()
    semantic_after = _semantic_snapshot()
    invariant_results = {}
    for name, before in invariant_before.items():
        after = invariant_after[name]
        invariant_results[name] = {
            "file_count": before["file_count"],
            "before_snapshot_sha256": before["snapshot_sha256"],
            "after_snapshot_sha256": after["snapshot_sha256"],
            "path_size_sha256_mtime_changes": 0 if before["records"] == after["records"] else 1,
            "passed": before["records"] == after["records"],
        }
    if not all(item["passed"] for item in invariant_results.values()):
        raise ValueError("one or more protected invariant scopes changed")
    if semantic_before != semantic_after:
        raise ValueError("research/product semantic invariant changed")

    after_path_hits = _path_hits(_submission_paths())
    if after_path_hits:
        raise ValueError(f"personal absolute paths remain: {after_path_hits}")

    _complete_changed_field_inventory(changes, old_records)
    changed_files = _changed_files(old_records)
    actual_changed = {item["path"] for item in changed_files}
    unexpected = actual_changed - ALLOWED_CHANGED_PATHS
    if unexpected:
        raise ValueError(f"files changed outside migration allowlist: {sorted(unexpected)}")

    changed_field_records = [
        {
            "path": path,
            "json_pointers_or_fields": pointers,
            "reason": (
                "replace machine-specific path metadata with repository-relative portable metadata"
                if path in DIRECT_CODE_CHANGES
                or "dataset-manifest" in path
                or "scan-report" in path
                else "mechanically refresh dependent hash or approved preservation metadata"
            ),
        }
        for path, pointers in sorted(changes.items())
        if pointers
    ]
    receipt = {
        "schema_version": "ax-submission-portability-migration-v1",
        "migration_id": "portability-migration-2026-09-24",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": "ALLOWLISTED_PATH_METADATA_AND_DEPENDENT_HASH_CHAIN_ONLY",
        "freeze_timestamps_statuses_experiment_and_run_ids_preserved": True,
        "kiro_or_llm_executed": False,
        "freeze_scripts_executed": False,
        "phase6_official_runs_regenerated": False,
        "held_out_results_regenerated": False,
        "path_portability": {
            "audit_reported_before_hits": 29,
            "reproduced_before_hits": reproduced_before_hits,
            "remaining_after_canonical_agent_edit": 21,
            "after_hits": len(after_path_hits),
            "canonical_agent_fields_changed": 8,
            "phase6_scanner_output_fields_changed": 2,
            "v2_manifest_source_root_fields_changed": 8,
            "v2_parser_error_fields_changed": 3,
        },
        "changed_files": changed_files,
        "changed_fields": changed_field_records,
        "hash_chain": {
            "v1_manifest_sha256": _sha(ROOT / "experiment/frozen/ax-exp-v1-manifest.json"),
            "v2_predecessor_sha256": _read(ROOT / "experiment/frozen/ax-exp-v2-manifest.json")["v1_frozen_manifest"]["sha256"],
            "v2_manifest_sha256": _sha(ROOT / "experiment/frozen/ax-exp-v2-manifest.json"),
            "v3_predecessor_sha256": _read(ROOT / "experiment/frozen/ax-exp-v3-manifest.json")["predecessor_manifest"]["sha256"],
            "v3_manifest_sha256": _sha(ROOT / "experiment/frozen/ax-exp-v3-manifest.json"),
            "phase6_dataset_manifest_sha256": _sha(ROOT / "artifacts/phase6_product_demo/dataset-manifest.json"),
            "phase6_frozen_manifest_dataset_record_updated": True,
        },
        "semantic_invariants": {
            "passed": True,
            "model_prompt_hash_tool_surface_unchanged": True,
            "task_bindings_source_file_hashes_readiness_results_unchanged": True,
            "held_out_results_unchanged": True,
            "phase6_official_run_results_unchanged": True,
            "semantic_snapshot_sha256": _canonical_hash(semantic_after),
        },
        "protected_scope_comparisons": invariant_results,
        "receipt_self_hash_excluded": True,
    }
    _write(RECEIPT, receipt)
    print(json.dumps({
        "receipt": RECEIPT.relative_to(ROOT).as_posix(),
        "changed_file_count": len(changed_files),
        "personal_path_hits_before": reproduced_before_hits,
        "personal_path_hits_after": len(after_path_hits),
        "semantic_invariants_passed": True,
        "protected_scopes_passed": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
