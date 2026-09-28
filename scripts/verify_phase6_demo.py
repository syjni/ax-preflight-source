"""Verify and freeze the Phase 6 product-sanity demo artifacts.

The verifier is intentionally read-only unless ``--create-freeze`` is passed.
The freeze receipt itself is published write-once and never hashes itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from readiness_score import score_scan_report_file
from portable_path_order import frozen_sorted_files


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_RELATIVE = Path("artifacts/phase6_product_demo")
FREEZE_RELATIVE = ARTIFACT_RELATIVE / "FROZEN_MANIFEST.json"
DIAGNOSTIC_RECEIPT_RELATIVE = ARTIFACT_RELATIVE / "DIAGNOSTIC_CLOSURE.json"
CLAIM_SCOPE = "PRODUCT_SANITY_DEMO_NOT_RESEARCH_BENCHMARK"
PROFILES = ("demo-return-before", "demo-return-after")
DIAGNOSTIC_RUNS = {
    "phase6demo-diagnostic-after-001": "diagnostic-001",
    "phase6demo-diagnostic-after-002": "diagnostic-002",
}
TOP_LEVEL_FROZEN_FILES = (
    "before-scan-report.json",
    "after-scan-report.json",
    "dataset-manifest.json",
    "remediation-receipt.json",
    "run-manifest.json",
    "summary.json",
    "RESULTS.md",
)


class Phase6VerificationError(ValueError):
    """Raised when a frozen or semantic Phase 6 invariant is violated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase6VerificationError(message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Phase6VerificationError(f"cannot read JSON artifact: {path}") from exc
    _require(isinstance(value, dict), f"JSON artifact must be an object: {path}")
    return value


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise Phase6VerificationError(f"artifact escapes project root: {path}") from exc


def _resolve_relative(root: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and relative, "artifact path must be nonblank")
    candidate = (root / Path(relative)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise Phase6VerificationError(
            f"freeze receipt path escapes project root: {relative}"
        ) from exc
    return candidate


def _tree_record(root: Path, tree_root: Path) -> dict[str, Any]:
    _require(tree_root.is_dir(), f"missing frozen tree: {tree_root}")
    files = frozen_sorted_files(tree_root)
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(tree_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
    return {
        "path": _relative(root, tree_root),
        "sha256": digest.hexdigest(),
        "file_count": len(files),
    }


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"missing frozen file: {path}")
    return {
        "path": _relative(root, path),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _verify_static_artifacts(
    root: Path, artifact_root: Path, dataset: dict[str, Any], remediation: dict[str, Any]
) -> list[Path]:
    _require(dataset.get("claim_scope") == CLAIM_SCOPE, "dataset claim scope changed")
    _require(
        remediation.get("claim_scope") == CLAIM_SCOPE,
        "remediation claim scope changed",
    )
    profiles = dataset.get("profiles")
    _require(isinstance(profiles, dict), "dataset profiles missing")
    _require(set(profiles) == set(PROFILES), "dataset profile set changed")

    readiness: dict[str, dict[str, Any]] = {}
    warning_counts: dict[str, int] = {}
    source_roots: list[Path] = []
    expected_scan_names = {
        PROFILES[0]: "before-scan-report.json",
        PROFILES[1]: "after-scan-report.json",
    }
    for profile in PROFILES:
        profile_data = profiles[profile]
        _require(isinstance(profile_data, dict), f"invalid profile record: {profile}")
        scan_path = _resolve_relative(root, profile_data.get("scan_report", ""))
        _require(
            scan_path == (artifact_root / expected_scan_names[profile]).resolve(),
            f"unexpected scan report path for {profile}",
        )
        _require(
            _sha256(scan_path) == profile_data.get("scan_report_sha256"),
            f"scan report hash mismatch for {profile}",
        )
        scan = _load_json(scan_path)
        groups = scan.get("probable_version_groups")
        _require(isinstance(groups, list), f"warning list missing for {profile}")
        warning_counts[profile] = len(groups)
        readiness[profile] = score_scan_report_file(scan_path)
        _require(
            readiness[profile] == profile_data.get("readiness"),
            f"readiness receipt mismatch for {profile}",
        )

        source_root = _resolve_relative(root, profile_data.get("source_root", ""))
        _require(source_root.is_dir(), f"source tree missing for {profile}")
        source_roots.append(source_root)
        source_files = frozen_sorted_files(source_root)
        recorded_files = profile_data.get("files")
        _require(isinstance(recorded_files, list), f"source file list missing for {profile}")
        _require(
            [path.relative_to(source_root).as_posix() for path in source_files]
            == [item.get("relative_path") for item in recorded_files],
            f"source file set changed for {profile}",
        )
        for path, item in zip(source_files, recorded_files, strict=True):
            _require(_sha256(path) == item.get("sha256"), f"source hash mismatch: {path}")
            _require(path.stat().st_size == item.get("size_bytes"), f"source size mismatch: {path}")

    before = readiness[PROFILES[0]]
    after = readiness[PROFILES[1]]
    _require(
        before["readiness_score"] == after["readiness_score"],
        "before/after readiness totals differ",
    )
    _require(
        before["dimensions"] == after["dimensions"],
        "before/after readiness dimensions differ",
    )
    _require(
        warning_counts == {PROFILES[0]: 1, PROFILES[1]: 0},
        f"warning transition is not 1 -> 0: {warning_counts}",
    )

    comparison = remediation.get("readiness_comparison", {})
    _require(comparison.get("same_total") is True, "remediation total equality changed")
    _require(
        comparison.get("same_dimensions") is True,
        "remediation dimension equality changed",
    )
    _require(
        comparison.get("before_total") == before["readiness_score"]
        and comparison.get("after_total") == after["readiness_score"],
        "remediation readiness totals do not match scans",
    )
    _require(
        comparison.get("before_dimensions") == before["dimensions"]
        and comparison.get("after_dimensions") == after["dimensions"],
        "remediation readiness dimensions do not match scans",
    )
    _require(
        remediation.get("before", {}).get("probable_version_group_count") == 1
        and remediation.get("after", {}).get("probable_version_group_count") == 0,
        "remediation warning transition changed",
    )
    return source_roots


def _verify_official_runs(
    root: Path,
    artifact_root: Path,
    manifest: dict[str, Any],
    summary: dict[str, Any],
    dataset: dict[str, Any],
) -> list[Path]:
    _require(manifest.get("claim_scope") == CLAIM_SCOPE, "run claim scope changed")
    _require(summary.get("claim_scope") == CLAIM_SCOPE, "summary claim scope changed")
    _require(manifest.get("mode") == "official", "run manifest is not official")
    _require(summary.get("mode") == "official", "summary is not official")
    _require(
        isinstance(manifest.get("execution_id"), str) and manifest["execution_id"],
        "official execution ID missing",
    )
    runs = manifest.get("runs")
    summary_runs = summary.get("runs")
    _require(isinstance(runs, list) and len(runs) == 6, "official run count is not 6")
    _require(
        isinstance(summary_runs, list) and len(summary_runs) == 6,
        "summary run count is not 6",
    )
    run_ids = [run.get("run_id") for run in runs]
    _require(len(set(run_ids)) == 6 and all(run_ids), "official run IDs are not unique")
    _require(summary.get("run_count") == 6, "summary run_count is not 6")
    _require(summary.get("run_ids") == run_ids, "summary run IDs differ from manifest")
    _require(summary_runs == runs, "manifest and summary run records differ")
    expected_profiles = [PROFILES[0], PROFILES[1]] * 3
    _require(
        [run.get("dataset_profile") for run in runs] == expected_profiles,
        "official before/after schedule changed",
    )

    runs_root = artifact_root / "runs"
    actual_directories = sorted(
        path.name for path in runs_root.iterdir() if path.is_dir()
    )
    _require(actual_directories == sorted(run_ids), "official run directories changed")

    frozen_run_files: list[Path] = []
    before_conflicting = 0
    after_answered = 0
    profiles = dataset["profiles"]
    for order, record in enumerate(runs, start=1):
        run_id = record["run_id"]
        profile = record.get("dataset_profile")
        _require(record.get("execution_order") == order, f"execution order changed: {run_id}")
        expected_directory = runs_root / run_id
        recorded_directory = _resolve_relative(
            root, record.get("run_artifact_directory", "")
        )
        _require(
            recorded_directory == expected_directory.resolve(),
            f"run directory does not match run_id: {run_id}",
        )
        _require(
            not (expected_directory / "state.json").exists(),
            f"official run has state.json: {run_id}",
        )

        delivery_path = expected_directory / "delivery.json"
        evidence_path = expected_directory / "evidence-check.json"
        delivery = _load_json(delivery_path)
        evidence = _load_json(evidence_path)
        _require(delivery.get("run_id") == run_id, f"delivery run_id mismatch: {run_id}")
        _require(evidence.get("run_id") == run_id, f"evidence run_id mismatch: {run_id}")
        _require(delivery.get("dataset") == profile, f"delivery dataset mismatch: {run_id}")
        delivery_sha = _sha256(delivery_path)
        evidence_sha = _sha256(evidence_path)
        _require(delivery_sha == record.get("delivery_sha256"), f"delivery hash mismatch: {run_id}")
        _require(
            evidence_sha == record.get("evidence_check_sha256"),
            f"evidence hash mismatch: {run_id}",
        )
        _require(
            evidence.get("delivery_sha256") == delivery_sha,
            f"evidence delivery_sha256 mismatch: {run_id}",
        )
        _require(
            record.get("readiness_total")
            == profiles[profile]["readiness"]["readiness_score"]
            and record.get("readiness_dimensions")
            == profiles[profile]["readiness"]["dimensions"],
            f"run readiness record mismatch: {run_id}",
        )

        response_root = expected_directory / "tool-responses"
        responses = sorted(response_root.glob("*.json")) if response_root.is_dir() else []
        _require(
            len(responses) == record.get("tool_response_count"),
            f"tool response count mismatch: {run_id}",
        )
        _require(
            not response_root.is_dir()
            or sorted(path.name for path in response_root.iterdir() if path.is_file())
            == [path.name for path in responses],
            f"unexpected tool response artifact: {run_id}",
        )
        for sequence, response_path in enumerate(responses, start=1):
            response = _load_json(response_path)
            _require(response.get("run_id") == run_id, f"tool response run_id mismatch: {response_path}")
            _require(response.get("sequence") == sequence, f"tool response sequence mismatch: {response_path}")
            _require(
                response.get("output_sha256") == _canonical_sha256(response.get("output")),
                f"tool response output hash mismatch: {response_path}",
            )

        payload = delivery.get("payload") or {}
        if profile == PROFILES[0]:
            _require(
                delivery.get("delivery_status") == "DELIVERED"
                and payload.get("status") == "ABSTAINED"
                and payload.get("abstention_reason") == "CONFLICTING_EVIDENCE",
                f"before outcome changed: {run_id}",
            )
            before_conflicting += 1
        else:
            _require(
                delivery.get("delivery_status") == "DELIVERED"
                and payload.get("status") == "ANSWERED",
                f"after outcome changed: {run_id}",
            )
            after_answered += 1

        forbidden = [
            path for path in expected_directory.rglob("*") if path.is_file()
            and ("stdout" in path.name.casefold() or "finaltext" in path.name.casefold())
        ]
        _require(not forbidden, f"raw Kiro output found in official run: {run_id}")
        frozen_run_files.extend([delivery_path, evidence_path, *responses])

    _require(before_conflicting == 3, "Before is not 3/3 conflicting abstention")
    _require(after_answered == 3, "After is not 3/3 answered")
    criteria = summary.get("sanity_criteria", {})
    _require(
        criteria.get("before_conflicting_abstention_count") == 3
        and criteria.get("after_answered_count") == 3
        and criteria.get("passed") is True,
        "summary sanity criteria changed",
    )
    return frozen_run_files


def _verify_diagnostic_closure(root: Path, artifact_root: Path) -> None:
    receipt_path = root / DIAGNOSTIC_RECEIPT_RELATIVE
    receipt = _load_json(receipt_path)
    _require(
        receipt.get("schema_version") == "ax-phase6-diagnostic-closure-v1",
        "diagnostic receipt schema changed",
    )
    _require(receipt.get("active_process_count") == 0, "diagnostic process check is not zero")
    entries = receipt.get("runs")
    _require(isinstance(entries, list), "diagnostic receipt runs missing")
    _require(
        {entry.get("run_id") for entry in entries} == set(DIAGNOSTIC_RUNS),
        "diagnostic receipt run set changed",
    )
    for entry in entries:
        run_id = entry["run_id"]
        label = DIAGNOSTIC_RUNS[run_id]
        directory = artifact_root / "pilots" / label / "runs" / run_id
        _require(entry.get("stale_running_state_observed") is True, f"stale state not recorded: {run_id}")
        previous = entry.get("previous_state", {})
        _require(
            previous.get("run_id") == run_id
            and previous.get("dataset") == "demo-return-after"
            and previous.get("run_status") == "RUNNING",
            f"original diagnostic state changed: {run_id}",
        )
        delivery_path = directory / "delivery.json"
        evidence_path = directory / "evidence-check.json"
        delivery = _load_json(delivery_path)
        evidence = _load_json(evidence_path)
        _require(
            delivery.get("run_id") == run_id
            and delivery.get("dataset") == "demo-return-after"
            and delivery.get("delivery_status") == "REJECTED"
            and delivery.get("reject_reason") == "RUNTIME_ERROR",
            f"diagnostic final status changed: {run_id}",
        )
        delivery_sha = _sha256(delivery_path)
        evidence_sha = _sha256(evidence_path)
        _require(entry.get("delivery_sha256") == delivery_sha, f"diagnostic delivery hash mismatch: {run_id}")
        _require(entry.get("evidence_check_sha256") == evidence_sha, f"diagnostic evidence hash mismatch: {run_id}")
        _require(
            evidence.get("run_id") == run_id
            and evidence.get("delivery_sha256") == delivery_sha,
            f"diagnostic evidence binding mismatch: {run_id}",
        )
        _require(not (directory / "state.json").exists(), f"diagnostic state remains: {run_id}")


def _core_verification(root: Path) -> dict[str, Any]:
    root = root.resolve()
    artifact_root = root / ARTIFACT_RELATIVE
    dataset = _load_json(artifact_root / "dataset-manifest.json")
    remediation = _load_json(artifact_root / "remediation-receipt.json")
    manifest = _load_json(artifact_root / "run-manifest.json")
    summary = _load_json(artifact_root / "summary.json")
    source_roots = _verify_static_artifacts(
        root, artifact_root, dataset, remediation
    )
    run_files = _verify_official_runs(
        root, artifact_root, manifest, summary, dataset
    )
    _verify_diagnostic_closure(root, artifact_root)

    states = sorted(artifact_root.rglob("state.json"))
    _require(not states, f"unterminated Phase 6 state files remain: {states}")
    temporary_agents = sorted((root / ".kiro" / "agents").glob("ax-product-run*.json"))
    _require(not temporary_agents, f"temporary product agents remain: {temporary_agents}")

    top_files = [artifact_root / name for name in TOP_LEVEL_FROZEN_FILES]
    frozen_files = sorted(
        (_file_record(root, path) for path in [*top_files, *run_files]),
        key=lambda item: item["path"],
    )
    frozen_trees = sorted(
        (
            _tree_record(root, path)
            for path in [*source_roots, artifact_root / "runs"]
        ),
        key=lambda item: item["path"],
    )
    return {
        "manifest": manifest,
        "run_ids": [run["run_id"] for run in manifest["runs"]],
        "files": frozen_files,
        "trees": frozen_trees,
        "state_json_count": 0,
    }


def _verify_freeze_receipt(root: Path, core: dict[str, Any]) -> None:
    freeze_path = root / FREEZE_RELATIVE
    receipt = _load_json(freeze_path)
    _require(
        receipt.get("schema_version") == "ax-phase6-product-demo-freeze-v1",
        "freeze schema changed",
    )
    _require(receipt.get("hash_algorithm") == "SHA-256", "freeze hash algorithm changed")
    _require(receipt.get("claim_scope") == CLAIM_SCOPE, "freeze claim scope changed")
    _require(
        receipt.get("official_execution_id") == core["manifest"]["execution_id"],
        "freeze execution ID changed",
    )
    _require(receipt.get("run_ids") == core["run_ids"], "freeze run IDs changed")
    _require(
        receipt.get("verification", {}).get("passed") is True,
        "freeze verification status is not passed",
    )
    artifacts = receipt.get("artifacts", {})
    _require(artifacts.get("files") == core["files"], "frozen file hashes changed")
    _require(artifacts.get("trees") == core["trees"], "frozen tree hashes changed")
    frozen_paths = {
        item["path"] for item in [*artifacts.get("files", []), *artifacts.get("trees", [])]
    }
    _require(FREEZE_RELATIVE.as_posix() not in frozen_paths, "freeze receipt hashes itself")
    for item in artifacts.get("files", []):
        path = _resolve_relative(root, item["path"])
        _require(_sha256(path) == item["sha256"], f"frozen file mismatch: {item['path']}")
    for item in artifacts.get("trees", []):
        actual = _tree_record(root, _resolve_relative(root, item["path"]))
        _require(actual == item, f"frozen tree mismatch: {item['path']}")


def verify_phase6_demo(
    *, root: str | Path = ROOT, require_freeze: bool = True
) -> dict[str, Any]:
    """Verify semantic closure and, by default, every frozen hash."""
    selected_root = Path(root).resolve()
    core = _core_verification(selected_root)
    if require_freeze:
        _verify_freeze_receipt(selected_root, core)
    return {
        "passed": True,
        "official_execution_id": core["manifest"]["execution_id"],
        "official_run_count": len(core["run_ids"]),
        "frozen_file_count": len(core["files"]),
        "frozen_tree_count": len(core["trees"]),
        "state_json_count": core["state_json_count"],
        "freeze_verified": require_freeze,
    }


def _write_json_once(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FileExistsError(f"freeze receipt already exists: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def create_freeze_receipt(*, root: str | Path = ROOT) -> Path:
    """Verify current official artifacts, then publish their receipt once."""
    selected_root = Path(root).resolve()
    freeze_path = selected_root / FREEZE_RELATIVE
    _require(not freeze_path.exists(), f"freeze receipt already exists: {freeze_path}")
    core = _core_verification(selected_root)
    receipt = {
        "schema_version": "ax-phase6-product-demo-freeze-v1",
        "hash_algorithm": "SHA-256",
        "claim_scope": CLAIM_SCOPE,
        "official_execution_id": core["manifest"]["execution_id"],
        "run_ids": core["run_ids"],
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "verification": {
            "passed": True,
            "official_integrity_checked_before_freeze": True,
        },
        "artifacts": {
            "files": core["files"],
            "trees": core["trees"],
        },
    }
    _write_json_once(freeze_path, receipt)
    _verify_freeze_receipt(selected_root, core)
    return freeze_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--pre-freeze",
        action="store_true",
        help="verify semantic integrity without requiring a freeze receipt",
    )
    mode.add_argument(
        "--create-freeze",
        action="store_true",
        help="verify and publish FROZEN_MANIFEST.json exactly once",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.create_freeze:
        path = create_freeze_receipt()
        result = verify_phase6_demo()
        result["freeze_receipt"] = _relative(ROOT, path)
    else:
        result = verify_phase6_demo(require_freeze=not args.pre_freeze)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
