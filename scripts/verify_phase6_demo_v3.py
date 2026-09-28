"""Create or verify the frozen 30-file, 10-task product demo snapshot.

Frozen v3 adds a broad exploratory portfolio to the six-run v2 sanity demo.
The v1 and v2 trees remain unchanged.  Creation is write-once and consumes the
locally reviewed pilot only as an input; verification depends solely on tracked
runtime data and the published v3 tree.
"""

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
from ax_product.evidence import EvidenceCheckResult, check_run
from ax_product.findings import FindingType, aggregate_findings
from ax_product.models import DeliveryEnvelope
from ax_product.results import CompositeResultStore
from ax_scanner.models import ScanReport
from portable_path_order import frozen_sorted_files
from readiness_score import score_scan_report_file
from scripts.verify_phase6_demo_v2 import verify_phase6_demo_v2


ROOT = Path(__file__).resolve().parents[1]
V2_RELATIVE = Path("artifacts/phase6_product_demo_v2")
V3_RELATIVE = Path("artifacts/phase6_product_demo_v3")
V2_MANIFEST_RELATIVE = V2_RELATIVE / "FROZEN_MANIFEST.v2.json"
V3_MANIFEST_NAME = "FROZEN_MANIFEST.v3.json"
PILOT_RELATIVE = Path("_review_v2/portfolio_pilot_2026-09-25")
TRACKED_BEFORE_RELATIVE = Path("sample_data/product_demo/hanbit_portfolio_before")
BEFORE_PROFILE = "portfolio-hidden-conflict-before"
AFTER_PROFILE = "portfolio-ceiling-after"
PORTFOLIO_PROFILES = (BEFORE_PROFILE, AFTER_PROFILE)
EXPECTED_TOP_LEVEL = {
    V3_MANIFEST_NAME,
    "README.md",
    "STATIC_COMPARISON.json",
    "SUMMARY.json",
    "before-scan-report.json",
    "runs",
}


class Phase6V3VerificationError(ValueError):
    """Raised when the frozen portfolio or its parent binding has changed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase6V3VerificationError(message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Phase6V3VerificationError(f"cannot read JSON artifact: {path}") from exc
    _require(isinstance(value, dict), f"JSON artifact must be an object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


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
        if item.name != V3_MANIFEST_NAME
    ]


def _profile_counts(runs_root: Path, profile: str) -> dict[str, Any]:
    deliveries = []
    for path in sorted(runs_root.glob("*/delivery.json")):
        delivery = DeliveryEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
        if delivery.dataset == profile:
            deliveries.append(delivery)
    outcomes = Counter(
        delivery.payload.status
        if delivery.delivery_status == "DELIVERED" and delivery.payload is not None
        else "REJECTED"
        for delivery in deliveries
    )
    abstentions = Counter(
        delivery.payload.abstention_reason
        for delivery in deliveries
        if delivery.payload is not None and delivery.payload.abstention_reason is not None
    )
    evidence = Counter(
        EvidenceCheckResult.model_validate_json(
            (runs_root / delivery.run_id / "evidence-check.json").read_text(encoding="utf-8")
        ).verdict
        for delivery in deliveries
    )
    return {
        "run_count": len(deliveries),
        "outcomes": dict(sorted(outcomes.items())),
        "abstention_reasons": dict(sorted(abstentions.items())),
        "evidence_verdicts": dict(sorted(evidence.items())),
    }


def _portable_summary(pilot: dict[str, Any]) -> dict[str, Any]:
    allowed_run_fields = (
        "dataset", "task_id", "category", "question", "repetition", "run_id",
        "duration_seconds", "delivery_status", "reject_reason", "payload_status",
        "abstention_reason", "answer", "source_ids", "evidence_verdict",
    )
    return {
        "schema_version": "ax-phase6-product-demo-summary-v3",
        "claim_scope": "EXPLORATORY_PRODUCT_PILOT_NOT_RESEARCH_BENCHMARK",
        "started_at": pilot["started_at"],
        "completed_at": pilot["completed_at"],
        "model": pilot["model"],
        "kiro_cli_version": pilot["kiro_cli_version"],
        "fresh_process_per_new_run": pilot["fresh_process_per_new_run"],
        "profiles": pilot["profiles"],
        "task_ids": pilot["task_ids"],
        "repetitions": pilot["repetitions"],
        "profile_summaries": pilot["profile_summaries"],
        "runs": [
            {field: row[field] for field in allowed_run_fields}
            for row in pilot["runs"]
        ],
    }


def _static_comparison(root: Path, scan_path: Path) -> dict[str, Any]:
    before = score_scan_report_file(scan_path)
    after = score_scan_report_file(root / "ceiling_scan_report.json")
    report = ScanReport.model_validate_json(scan_path.read_text(encoding="utf-8"))
    original = root / "sample_data/ceiling_company/06_고객지원/FAQ_2026.txt"
    changed = root / TRACKED_BEFORE_RELATIVE / "06_고객지원/FAQ_2026.txt"
    return {
        "schema_version": "ax-phase6-product-demo-static-comparison-v3",
        "claim_scope": "PRODUCT_DEMO_FIXTURE_NOT_CUSTOMER_DATA",
        "before_profile": BEFORE_PROFILE,
        "after_profile": AFTER_PROFILE,
        "file_count": report.scan_metadata.file_count,
        "parsed_file_count": report.scan_metadata.parsed_file_count,
        "before_readiness": before,
        "after_readiness": after,
        "same_readiness_total": before["readiness_score"] == after["readiness_score"],
        "same_readiness_dimensions": before["dimensions"] == after["dimensions"],
        "before_probable_version_group_count": len(report.probable_version_groups),
        "mutation": {
            "relative_path": "06_고객지원/FAQ_2026.txt",
            "after_sha256": _sha256(original),
            "before_sha256": _sha256(changed),
            "relationship_visible_in_filename": False,
            "before_statement": "온라인몰 고객 문의에는 상품 수령 후 14일 이내 반품 가능하다고 안내한다.",
            "conflicting_policy_statement": "반품 가능 기간은 구매일로부터 30일입니다.",
        },
    }


def _readme(summary: dict[str, Any]) -> str:
    before = summary["profile_summaries"][BEFORE_PROFILE]
    after = summary["profile_summaries"][AFTER_PROFILE]
    return "\n".join([
        "# Phase 6 Product Demo v3",
        "",
        "This write-once snapshot adds a 30-file, 10-task portfolio to the preserved v2 sanity demo.",
        "It is an exploratory product demonstration, not a research benchmark.",
        "",
        f"- Before: {before['diagnostics']['processable_task_count']}/10 processable, "
        f"{before['diagnostics']['blocked_task_count']}/10 blocked",
        f"- After: {after['diagnostics']['processable_task_count']}/10 processable, "
        f"{after['diagnostics']['blocked_task_count']}/10 blocked",
        "- Before blockers: one semantic conflict, one insufficient-evidence case, and two missing-information cases",
        "- The return-policy conflict is not reproduced After; the two genuinely missing fields remain open",
        "- Static Readiness is 100 in both states, with zero probable-version groups",
        "",
        "Verify with: `python -m scripts.verify_phase6_demo_v3`",
        "",
    ])


def create_phase6_demo_v3(*, root: str | Path = ROOT) -> dict[str, Any]:
    selected_root = Path(root).resolve()
    target = selected_root / V3_RELATIVE
    if target.exists():
        raise FileExistsError(f"Phase 6 v3 snapshot already exists: {target}")
    verify_phase6_demo_v2(root=selected_root)
    pilot_root = selected_root / PILOT_RELATIVE
    pilot_runs = pilot_root / "runs"
    pilot_summary = _load_json(pilot_root / "summary.json")
    staged_scan = pilot_root / "tracked-before-scan-report.json"
    _require(staged_scan.is_file(), "tracked Before scan is missing")
    _require(pilot_summary.get("completed_at") is not None, "portfolio pilot is incomplete")
    _require(len(pilot_summary.get("runs", [])) == 20, "portfolio pilot is not 20 runs")
    _require(
        _tree_sha256(selected_root / TRACKED_BEFORE_RELATIVE)
        == _tree_sha256(pilot_root / "dataset-before"),
        "tracked Before dataset differs from the reviewed pilot",
    )

    temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    try:
        temporary.mkdir(parents=True)
        shutil.copyfile(staged_scan, temporary / "before-scan-report.json")
        combined_runs = temporary / "runs"
        shutil.copytree(selected_root / V2_RELATIVE / "runs", combined_runs)
        for run_dir in sorted(path for path in pilot_runs.iterdir() if path.is_dir()):
            destination = combined_runs / run_dir.name
            _require(not destination.exists(), f"duplicate run ID across v2 and v3: {run_dir.name}")
            shutil.copytree(run_dir, destination)

        summary = _portable_summary(pilot_summary)
        static = _static_comparison(selected_root, temporary / "before-scan-report.json")
        _write_json(temporary / "SUMMARY.json", summary)
        _write_json(temporary / "STATIC_COMPARISON.json", static)
        (temporary / "README.md").write_text(_readme(summary), encoding="utf-8", newline="\n")

        parent_root = selected_root / V2_RELATIVE
        portfolio_run_ids = [row["run_id"] for row in summary["runs"]]
        parent_run_ids = sorted(path.name for path in (parent_root / "runs").iterdir() if path.is_dir())
        manifest = {
            "schema_version": "ax-phase6-product-demo-freeze-v3",
            "hash_algorithm": "SHA-256",
            "parent_manifest_path": V2_MANIFEST_RELATIVE.as_posix(),
            "parent_manifest_sha256": _sha256(selected_root / V2_MANIFEST_RELATIVE),
            "parent_tree_sha256": _tree_sha256(parent_root),
            "policy": "COPY_V2_AND_REVIEWED_PORTFOLIO_RUNS_WITHOUT_OVERWRITING_V1_OR_V2",
            "tracked_before_dataset_path": TRACKED_BEFORE_RELATIVE.as_posix(),
            "tracked_before_dataset_tree_sha256": _tree_sha256(selected_root / TRACKED_BEFORE_RELATIVE),
            "parent_run_ids": parent_run_ids,
            "portfolio_run_ids": portfolio_run_ids,
            "combined_run_count": len(parent_run_ids) + len(portfolio_run_ids),
            "portfolio_summary": {
                profile: _profile_counts(combined_runs, profile)
                for profile in PORTFOLIO_PROFILES
            },
            "verification": {
                "passed": True,
                "v1_v2_preserved": True,
                "write_once": True,
            },
            "artifacts": {"files": _file_records(temporary)},
        }
        _write_json(temporary / V3_MANIFEST_NAME, manifest)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return verify_phase6_demo_v3(root=selected_root)


def verify_phase6_demo_v3(*, root: str | Path = ROOT) -> dict[str, Any]:
    selected_root = Path(root).resolve()
    verify_phase6_demo_v2(root=selected_root)
    v2_root = selected_root / V2_RELATIVE
    v3_root = selected_root / V3_RELATIVE
    runs_root = v3_root / "runs"
    manifest = _load_json(v3_root / V3_MANIFEST_NAME)
    _require(set(path.name for path in v3_root.iterdir()) == EXPECTED_TOP_LEVEL, "unexpected v3 top-level artifact")
    _require(manifest.get("schema_version") == "ax-phase6-product-demo-freeze-v3", "v3 schema changed")
    _require(manifest.get("hash_algorithm") == "SHA-256", "v3 hash algorithm changed")
    _require(manifest.get("parent_manifest_sha256") == _sha256(selected_root / V2_MANIFEST_RELATIVE), "v2 parent manifest changed")
    _require(manifest.get("parent_tree_sha256") == _tree_sha256(v2_root), "v2 parent tree changed")
    before_tree = _tree_sha256(selected_root / TRACKED_BEFORE_RELATIVE)
    _require(manifest.get("tracked_before_dataset_tree_sha256") == before_tree, "tracked Before dataset changed")
    _require(manifest.get("artifacts", {}).get("files") == _file_records(v3_root), "v3 file inventory changed")
    _require(not list(v3_root.rglob("state.json")), "v3 contains mutable run state")

    parent_ids = manifest.get("parent_run_ids")
    portfolio_ids = manifest.get("portfolio_run_ids")
    _require(isinstance(parent_ids, list) and len(parent_ids) == 6, "v3 parent run count changed")
    _require(isinstance(portfolio_ids, list) and len(portfolio_ids) == 20, "v3 portfolio run count changed")
    _require(len(set(parent_ids + portfolio_ids)) == 26, "v3 run IDs are not unique")
    actual_ids = sorted(path.name for path in runs_root.iterdir() if path.is_dir())
    _require(actual_ids == sorted(parent_ids + portfolio_ids), "v3 run directories changed")
    for run_id in parent_ids:
        parent_files = frozen_sorted_files(v2_root / "runs" / run_id)
        copied_files = frozen_sorted_files(runs_root / run_id)
        _require(
            [path.relative_to(v2_root / "runs" / run_id).as_posix() for path in parent_files]
            == [path.relative_to(runs_root / run_id).as_posix() for path in copied_files],
            f"v2 copied file list changed: {run_id}",
        )
        _require([path.read_bytes() for path in parent_files] == [path.read_bytes() for path in copied_files], f"v2 copied bytes changed: {run_id}")
    for run_id in parent_ids + portfolio_ids:
        stored = EvidenceCheckResult.model_validate_json(
            (runs_root / run_id / "evidence-check.json").read_text(encoding="utf-8")
        )
        _require(stored == check_run(runs_root, run_id), f"evidence check is not reproducible: {run_id}")

    config = selected_root / "runtime_datasets.json"
    before_dataset = resolve_runtime_dataset(BEFORE_PROFILE, config)
    after_dataset = resolve_runtime_dataset(AFTER_PROFILE, config)
    before_identity = runtime_identity(before_dataset)
    after_identity = runtime_identity(after_dataset)
    _require(before_identity["file_count"] == after_identity["file_count"] == 30, "portfolio is not 30 files")
    before_readiness = score_scan_report_file(before_dataset.scan_report)
    after_readiness = score_scan_report_file(after_dataset.scan_report)
    _require(before_readiness["readiness_score"] == after_readiness["readiness_score"] == 100.0, "portfolio Readiness is not 100/100")
    _require(before_readiness["dimensions"] == after_readiness["dimensions"], "portfolio readiness dimensions differ")
    before_report = ScanReport.model_validate_json(before_dataset.scan_report.read_text(encoding="utf-8"))
    _require(len(before_report.probable_version_groups) == 0, "Before exposes a probable version group")

    expected_counts = {
        BEFORE_PROFILE: {
            "run_count": 10,
            "outcomes": {"ABSTAINED": 4, "ANSWERED": 6},
            "abstention_reasons": {"CONFLICTING_EVIDENCE": 1, "INSUFFICIENT_EVIDENCE": 1, "NOT_FOUND": 2},
            "evidence_verdicts": {"UNCONFIRMED": 10},
        },
        AFTER_PROFILE: {
            "run_count": 10,
            "outcomes": {"ABSTAINED": 2, "ANSWERED": 8},
            "abstention_reasons": {"NOT_FOUND": 2},
            "evidence_verdicts": {"DIRECT_MATCH": 1, "UNCONFIRMED": 9},
        },
    }
    observed_counts = {profile: _profile_counts(runs_root, profile) for profile in PORTFOLIO_PROFILES}
    _require(observed_counts == expected_counts, "v3 portfolio outcomes changed")
    _require(manifest.get("portfolio_summary") == expected_counts, "v3 manifest outcome summary changed")

    store = CompositeResultStore(
        selected_root / "_review_v2/nonexistent-v3-verifier-writable", runs_root
    )
    before_findings = aggregate_findings(store, BEFORE_PROFILE)
    after_findings = aggregate_findings(store, AFTER_PROFILE)
    _require(before_findings.diagnostics.processable_task_count == 6, "Before processable count changed")
    _require(before_findings.diagnostics.blocked_task_count == 4, "Before blocked count changed")
    before_types = Counter(item.finding_type for item in before_findings.findings)
    _require(before_types == Counter({
        FindingType.CONFLICTING_SOURCES: 1,
        FindingType.INSUFFICIENT_EVIDENCE: 1,
        FindingType.MISSING_INFORMATION: 2,
    }), "Before finding types changed")
    _require(after_findings.diagnostics.processable_task_count == 8, "After processable count changed")
    _require(after_findings.diagnostics.blocked_task_count == 2, "After blocked count changed")
    return {
        "freeze_verified": True,
        "passed": True,
        "combined_run_count": 26,
        "portfolio_run_count": 20,
        "before_processable_task_count": 6,
        "before_blocked_task_count": 4,
        "after_processable_task_count": 8,
        "after_blocked_task_count": 2,
        "frozen_file_count": len(manifest["artifacts"]["files"]),
        "parent_manifest_sha256": manifest["parent_manifest_sha256"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()
    result = create_phase6_demo_v3() if args.create else verify_phase6_demo_v3()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
