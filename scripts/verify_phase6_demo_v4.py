"""Create or verify the write-once 60-run Phase 6 product demo v4."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity
from ax_product.evidence import EvidenceCheckResult
from ax_product.evidence import check_run
from ax_product.evidence_v2 import canonical_evidence_bytes, check_run_v2
from ax_product.findings import FindingType, aggregate_findings
from ax_product.models import DeliveryEnvelope
from ax_product.results import CompositeResultStore
from portable_path_order import frozen_sorted_files
from scripts.run_phase6_demo_v4 import (
    CATALOG,
    CONFIG,
    EXPECTED_RUN_COUNT,
    PILOT_ROOT,
    PROFILES,
    REPETITIONS,
    TASK_COUNT,
)
from scripts.verify_phase6_demo_v3 import verify_phase6_demo_v3


ROOT = Path(__file__).resolve().parents[1]
V3_ROOT = ROOT / "artifacts" / "phase6_product_demo_v3"
V3_MANIFEST = V3_ROOT / "FROZEN_MANIFEST.v3.json"
V4_ROOT = ROOT / "artifacts" / "phase6_product_demo_v4"
V4_MANIFEST_NAME = "FROZEN_MANIFEST.v4.json"
CHECKER_V2 = ROOT / "ax_product" / "evidence_v2.py"
EXPECTED_TOP_LEVEL = {V4_MANIFEST_NAME, "README.md", "SUMMARY.json", "runs"}


class Phase6V4VerificationError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase6V4VerificationError(message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_canonical_crlf_text(path: Path) -> str:
    """Hash text using the CRLF bytes recorded by the Windows v4 freeze."""
    canonical = path.read_text(encoding="utf-8").replace("\n", "\r\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Phase6V4VerificationError(f"cannot read JSON artifact: {path}") from exc
    _require(isinstance(value, dict), f"JSON artifact must be an object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )


def _pilot_evidence_reproducible(
    stored: EvidenceCheckResult,
    baseline: EvidenceCheckResult,
    current: EvidenceCheckResult,
) -> bool:
    if stored in (baseline, current):
        return True
    if stored.verdict != "DIRECT_MATCH" or current.verdict != "DIRECT_MATCH":
        return False
    return stored.model_copy(update={"limitations": current.limitations}) == current


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in frozen_sorted_files(path):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256(item)))
    return digest.hexdigest()


def _file_records(path: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": item.relative_to(path).as_posix(),
            "sha256": _sha256(item),
            "size_bytes": item.stat().st_size,
        }
        for item in frozen_sorted_files(path)
        if item.name != V4_MANIFEST_NAME
    ]


def _validate_pilot_summary(summary: dict[str, Any]) -> None:
    _require(summary.get("completed_at") is not None, "v4 pilot is incomplete")
    _require(summary.get("profiles") == PROFILES, "v4 pilot profiles changed")
    _require(summary.get("repetitions") == REPETITIONS, "v4 pilot must use three repetitions")
    _require(summary.get("run_namespace") == "phase6v4", "v4 run namespace changed")
    _require(len(summary.get("task_ids", [])) == TASK_COUNT, "v4 pilot must contain ten tasks")
    rows = summary.get("runs")
    _require(isinstance(rows, list) and len(rows) == EXPECTED_RUN_COUNT, "v4 pilot must contain 60 rows")
    keys = Counter(
        (row.get("dataset"), row.get("task_id"), row.get("repetition"))
        for row in rows if isinstance(row, dict)
    )
    expected_keys = {
        (profile, task_id, repetition)
        for profile in PROFILES
        for task_id in summary["task_ids"]
        for repetition in range(1, REPETITIONS + 1)
    }
    _require(set(keys) == expected_keys, "v4 pilot matrix changed")
    _require(all(count == 1 for count in keys.values()), "v4 pilot row multiplicity changed")
    _require(
        all(row.get("run_id", "").startswith("phase6v4-") for row in rows),
        "v4 run ID escaped its namespace",
    )


def _profile_snapshot(root: Path, runs_root: Path, profile: str) -> dict[str, Any]:
    deliveries = [
        DeliveryEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(runs_root.glob("*/delivery.json"))
    ]
    deliveries = [item for item in deliveries if item.dataset == profile]
    evidence = Counter(
        EvidenceCheckResult.model_validate_json(
            (runs_root / item.run_id / "evidence-check.json").read_text(encoding="utf-8")
        ).verdict
        for item in deliveries
    )
    outcomes = Counter(
        item.payload.status
        if item.delivery_status == "DELIVERED" and item.payload is not None
        else "REJECTED"
        for item in deliveries
    )
    abstentions = Counter(
        item.payload.abstention_reason
        for item in deliveries
        if item.payload is not None and item.payload.abstention_reason is not None
    )
    store = CompositeResultStore(
        root / "_review_v2" / "nonexistent-v4-verifier-writable",
        runs_root,
    )
    findings = aggregate_findings(store, profile)
    return {
        "run_count": len(deliveries),
        "outcomes": dict(sorted(outcomes.items())),
        "abstention_reasons": dict(sorted(abstentions.items())),
        "evidence_verdicts": dict(sorted(evidence.items())),
        "diagnostics": findings.diagnostics.model_dump(mode="json"),
        "finding_count": len(findings.findings),
        "finding_types": dict(sorted(Counter(
            item.finding_type.value for item in findings.findings
        ).items())),
    }


def _portable_summary(
    root: Path, pilot: dict[str, Any], runs_root: Path
) -> dict[str, Any]:
    allowed = (
        "dataset", "task_id", "category", "question", "repetition", "run_id",
        "reused_existing_final", "duration_seconds", "delivery_status",
        "reject_reason", "payload_status", "abstention_reason", "answer", "unit",
        "source_ids", "evidence_verdict",
    )
    portable_rows = []
    for row in pilot["runs"]:
        portable = {field: row.get(field) for field in allowed}
        portable["evidence_verdict"] = EvidenceCheckResult.model_validate_json(
            (runs_root / row["run_id"] / "evidence-check.json").read_text(
                encoding="utf-8"
            )
        ).verdict
        portable_rows.append(portable)
    return {
        "schema_version": "ax-phase6-product-demo-summary-v4",
        "claim_scope": "REPEATED_EXPLORATORY_PRODUCT_PILOT_NOT_CAUSAL_BENCHMARK",
        "started_at": pilot["started_at"],
        "completed_at": pilot["completed_at"],
        "model": pilot["model"],
        "kiro_cli_version": pilot["kiro_cli_version"],
        "fresh_process_per_new_run": pilot["fresh_process_per_new_run"],
        "profiles": pilot["profiles"],
        "task_ids": pilot["task_ids"],
        "repetitions": pilot["repetitions"],
        "run_namespace": pilot["run_namespace"],
        "profile_summaries": {
            profile: _profile_snapshot(root, runs_root, profile)
            for profile in PROFILES
        },
        "runs": portable_rows,
    }


def _readme(summary: dict[str, Any]) -> str:
    before = summary["profile_summaries"][PROFILES[0]]
    after = summary["profile_summaries"][PROFILES[1]]
    return "\n".join([
        "# Phase 6 Product Demo v4",
        "",
        "This write-once snapshot contains 10 tasks × 2 dataset states × 3 repetitions.",
        "It is an exploratory product pilot and does not by itself establish causal effect.",
        "Frozen v3 remains unchanged and is referenced by hash only.",
        "",
        f"- Before: {before['diagnostics']['processable_task_count']}/10 processable, "
        f"{before['diagnostics']['blocked_task_count']}/10 blocked, "
        f"{before['diagnostics']['inconclusive_task_count']}/10 inconclusive",
        f"- After: {after['diagnostics']['processable_task_count']}/10 processable, "
        f"{after['diagnostics']['blocked_task_count']}/10 blocked, "
        f"{after['diagnostics']['inconclusive_task_count']}/10 inconclusive",
        f"- Evidence: {sum(item['evidence_verdicts'].get('DIRECT_MATCH', 0) for item in (before, after))}/60 DIRECT_MATCH",
        "- Inconsistent answers or cited-source sets are first-class Findings.",
        "",
        "Verify with: `python -m scripts.verify_phase6_demo_v4`",
        "",
    ])


def create_phase6_demo_v4(
    *, root: str | Path = ROOT, pilot_root: str | Path = PILOT_ROOT
) -> dict[str, Any]:
    selected_root = Path(root).resolve()
    selected_pilot = Path(pilot_root).resolve()
    target = selected_root / "artifacts" / "phase6_product_demo_v4"
    if target.exists():
        raise FileExistsError(f"Phase 6 v4 snapshot already exists: {target}")
    verify_phase6_demo_v3(root=selected_root)
    pilot_summary = _load_json(selected_pilot / "summary.json")
    _validate_pilot_summary(pilot_summary)
    pilot_runs = selected_pilot / "runs"
    _require(pilot_runs.is_dir(), "v4 pilot runs are missing")
    _require(not list(pilot_runs.rglob("state.json")), "v4 pilot contains mutable run state")
    for row in pilot_summary["runs"]:
        run_id = row["run_id"]
        stored = EvidenceCheckResult.model_validate_json(
            (pilot_runs / run_id / "evidence-check.json").read_text(encoding="utf-8")
        )
        _require(
            _pilot_evidence_reproducible(
                stored,
                check_run(pilot_runs, run_id),
                check_run_v2(pilot_runs, run_id),
            ),
            f"pilot evidence is not reproducible by v1 or v2: {run_id}",
        )

    temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    try:
        temporary.mkdir(parents=True)
        shutil.copytree(pilot_runs, temporary / "runs")
        for row in pilot_summary["runs"]:
            run_id = row["run_id"]
            evidence_path = temporary / "runs" / run_id / "evidence-check.json"
            evidence_path.write_bytes(
                canonical_evidence_bytes(check_run_v2(temporary / "runs", run_id))
            )
        summary = _portable_summary(selected_root, pilot_summary, temporary / "runs")
        direct_count = sum(
            item["evidence_verdicts"].get("DIRECT_MATCH", 0)
            for item in summary["profile_summaries"].values()
        )
        _require(
            direct_count > EXPECTED_RUN_COUNT // 2,
            "v4 evidence direct matches are not a majority",
        )
        _write_json(temporary / "SUMMARY.json", summary)
        (temporary / "README.md").write_text(
            _readme(summary), encoding="utf-8", newline="\n"
        )
        identities = {
            profile: runtime_identity(resolve_runtime_dataset(
                profile, selected_root / "runtime_datasets.json"
            ))
            for profile in PROFILES
        }
        v3_root = selected_root / "artifacts" / "phase6_product_demo_v3"
        manifest = {
            "schema_version": "ax-phase6-product-demo-freeze-v4",
            "hash_algorithm": "SHA-256",
            "parent_manifest_path": "artifacts/phase6_product_demo_v3/FROZEN_MANIFEST.v3.json",
            "parent_manifest_sha256": _sha256(v3_root / "FROZEN_MANIFEST.v3.json"),
            "parent_tree_sha256": _tree_sha256(v3_root),
            "checker_v2_path": "ax_product/evidence_v2.py",
            "checker_v2_sha256": _sha256(selected_root / "ax_product/evidence_v2.py"),
            "task_catalog_sha256": _sha256(selected_root / "business_task_catalog.json"),
            "runtime_dataset_config_sha256": _sha256_canonical_crlf_text(
                selected_root / "runtime_datasets.json"
            ),
            "runtime_identities": identities,
            "policy": "NEW_60_RUN_SNAPSHOT_WITHOUT_OVERWRITING_V3",
            "run_count": EXPECTED_RUN_COUNT,
            "repetitions": REPETITIONS,
            "profile_summaries": summary["profile_summaries"],
            "verification": {
                "passed": True,
                "v3_preserved": True,
                "write_once": True,
                "pilot_evidence_reproducible_by_v1_or_v2": True,
                "evidence_v2_generated_in_new_snapshot": True,
                "evidence_v2_reproducible": True,
            },
            "artifacts": {"files": _file_records(temporary)},
        }
        _write_json(temporary / V4_MANIFEST_NAME, manifest)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return verify_phase6_demo_v4(root=selected_root)


def verify_phase6_demo_v4(*, root: str | Path = ROOT) -> dict[str, Any]:
    selected_root = Path(root).resolve()
    verify_phase6_demo_v3(root=selected_root)
    v3_root = selected_root / "artifacts" / "phase6_product_demo_v3"
    v4_root = selected_root / "artifacts" / "phase6_product_demo_v4"
    runs_root = v4_root / "runs"
    manifest = _load_json(v4_root / V4_MANIFEST_NAME)
    summary = _load_json(v4_root / "SUMMARY.json")
    _require(set(path.name for path in v4_root.iterdir()) == EXPECTED_TOP_LEVEL, "unexpected v4 top-level artifact")
    _require(manifest.get("schema_version") == "ax-phase6-product-demo-freeze-v4", "v4 schema changed")
    _require(manifest.get("parent_manifest_sha256") == _sha256(v3_root / "FROZEN_MANIFEST.v3.json"), "v3 manifest changed")
    _require(manifest.get("parent_tree_sha256") == _tree_sha256(v3_root), "v3 tree changed")
    _require(manifest.get("checker_v2_sha256") == _sha256(selected_root / "ax_product/evidence_v2.py"), "checker v2 changed")
    _require(manifest.get("task_catalog_sha256") == _sha256(selected_root / "business_task_catalog.json"), "task catalog changed")
    _require(
        manifest.get("runtime_dataset_config_sha256")
        == _sha256_canonical_crlf_text(selected_root / "runtime_datasets.json"),
        "runtime dataset config changed",
    )
    _require(manifest.get("artifacts", {}).get("files") == _file_records(v4_root), "v4 file inventory changed")
    _require(not list(v4_root.rglob("state.json")), "v4 contains mutable run state")
    _validate_pilot_summary(summary)

    run_ids = [row["run_id"] for row in summary["runs"]]
    actual_ids = sorted(path.name for path in runs_root.iterdir() if path.is_dir())
    _require(len(set(run_ids)) == EXPECTED_RUN_COUNT, "v4 run IDs are not unique")
    _require(actual_ids == sorted(run_ids), "v4 run directories changed")
    for run_id in run_ids:
        stored = EvidenceCheckResult.model_validate_json(
            (runs_root / run_id / "evidence-check.json").read_text(encoding="utf-8")
        )
        _require(stored == check_run_v2(runs_root, run_id), f"evidence v2 is not reproducible: {run_id}")

    identities = {
        profile: runtime_identity(resolve_runtime_dataset(
            profile, selected_root / "runtime_datasets.json"
        ))
        for profile in PROFILES
    }
    _require(manifest.get("runtime_identities") == identities, "runtime identity changed")
    observed_profiles = {
        profile: _profile_snapshot(selected_root, runs_root, profile)
        for profile in PROFILES
    }
    _require(summary.get("profile_summaries") == observed_profiles, "v4 summary counts changed")
    _require(manifest.get("profile_summaries") == observed_profiles, "v4 manifest counts changed")
    _require(all(item["run_count"] == 30 for item in observed_profiles.values()), "v4 profile run count changed")
    direct_count = sum(
        item["evidence_verdicts"].get("DIRECT_MATCH", 0)
        for item in observed_profiles.values()
    )
    _require(direct_count > EXPECTED_RUN_COUNT // 2, "v4 evidence direct matches are not a majority")

    store = CompositeResultStore(
        selected_root / "_review_v2" / "nonexistent-v4-verifier-writable",
        runs_root,
    )
    inconsistent_count = 0
    for profile in PROFILES:
        response = aggregate_findings(store, profile)
        for finding in response.findings:
            if finding.finding_type == FindingType.INCONSISTENT_ANSWERS:
                inconsistent_count += 1
                _require(finding.observed_run_count >= 2, "inconsistency finding lacks repeated runs")
                _require(len(finding.answer_variants) >= 2, "inconsistency finding lacks variants")
    return {
        "freeze_verified": True,
        "passed": True,
        "run_count": EXPECTED_RUN_COUNT,
        "direct_match_count": direct_count,
        "remaining_non_direct_count": EXPECTED_RUN_COUNT - direct_count,
        "inconsistent_finding_count": inconsistent_count,
        "frozen_file_count": len(manifest["artifacts"]["files"]),
        "parent_manifest_sha256": manifest["parent_manifest_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--pilot-root", type=Path, default=PILOT_ROOT)
    args = parser.parse_args()
    result = (
        create_phase6_demo_v4(pilot_root=args.pilot_root)
        if args.create else verify_phase6_demo_v4()
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
