"""Create and verify the immutable Phase 6 evidence-checker v2 snapshot.

Version 2 copies only the six official run inputs from frozen v1 and recomputes
their evidence-check artifacts.  The v1 tree is verified before creation and is
never opened for writing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from ax_product.evidence import EvidenceCheckResult, EvidenceCheckStore, check_run
from portable_path_order import frozen_sorted_files
from scripts.verify_phase6_demo import verify_phase6_demo


ROOT = Path(__file__).resolve().parents[1]
V1_RELATIVE = Path("artifacts/phase6_product_demo")
V2_RELATIVE = Path("artifacts/phase6_product_demo_v2")
V2_MANIFEST_NAME = "FROZEN_MANIFEST.v2.json"
V1_MANIFEST_RELATIVE = V1_RELATIVE / "FROZEN_MANIFEST.json"
V1_RUN_MANIFEST_RELATIVE = V1_RELATIVE / "run-manifest.json"
COMPARISON_RELATIVE = Path(
    "artifacts/posthoc_phase6_evidence_checker_fix/COMPARISON.json"
)
CHECKER_SOURCE_RELATIVE = Path("ax_product/evidence.py")
CHECKER_COMMIT = "71c610f05a9626555405d67ec19f73152e7a4fa3"


class Phase6V2VerificationError(ValueError):
    """Raised when the v2 snapshot is incomplete or no longer hash-bound."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase6V2VerificationError(message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Phase6V2VerificationError(f"cannot read JSON artifact: {path}") from exc
    _require(isinstance(value, dict), f"JSON artifact must be an object: {path}")
    return value


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in frozen_sorted_files(path):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256(item)))
    return digest.hexdigest()


def _file_records(root: Path, runs_root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": _relative(root, path),
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in frozen_sorted_files(runs_root)
    ]


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def create_phase6_demo_v2(*, root: str | Path = ROOT) -> dict[str, Any]:
    """Publish v2 once; refuse to replace any existing target."""
    selected_root = Path(root).resolve()
    v1_root = selected_root / V1_RELATIVE
    target = selected_root / V2_RELATIVE
    if target.exists():
        raise FileExistsError(f"Phase 6 v2 snapshot already exists: {target}")

    verify_phase6_demo(root=selected_root)
    v1_tree_before = _tree_sha256(v1_root)
    run_manifest = _load_json(selected_root / V1_RUN_MANIFEST_RELATIVE)
    comparison_path = selected_root / COMPARISON_RELATIVE
    checker_source_path = selected_root / CHECKER_SOURCE_RELATIVE
    parent_manifest_path = selected_root / V1_MANIFEST_RELATIVE
    run_records = run_manifest.get("runs")
    _require(isinstance(run_records, list) and len(run_records) == 6, "v1 run set is not six")

    temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    temporary_runs = temporary / "runs"
    try:
        temporary_runs.mkdir(parents=True)
        manifest_runs: list[dict[str, Any]] = []
        after_verdicts: list[str] = []
        before_verdicts: list[str] = []
        for source_record in run_records:
            run_id = source_record["run_id"]
            profile = source_record["dataset_profile"]
            source_run = v1_root / "runs" / run_id
            target_run = temporary_runs / run_id
            target_run.mkdir()
            shutil.copyfile(source_run / "delivery.json", target_run / "delivery.json")
            source_responses = source_run / "tool-responses"
            if source_responses.is_dir():
                shutil.copytree(source_responses, target_run / "tool-responses")

            recomputed = check_run(temporary_runs, run_id)
            EvidenceCheckStore(temporary_runs).write(recomputed)
            baseline = EvidenceCheckResult.model_validate_json(
                (source_run / "evidence-check.json").read_text(encoding="utf-8")
            )
            response_paths = sorted(source_responses.glob("*.json"))
            response_hashes = [_sha256(path) for path in response_paths]
            copied_response_paths = sorted((target_run / "tool-responses").glob("*.json"))
            copied_response_hashes = [_sha256(path) for path in copied_response_paths]
            _require(response_hashes == copied_response_hashes, f"tool responses changed: {run_id}")
            _require(
                (source_run / "delivery.json").read_bytes()
                == (target_run / "delivery.json").read_bytes(),
                f"delivery changed: {run_id}",
            )
            _require(
                baseline.matched_source_ids == recomputed.matched_source_ids
                and baseline.unmatched_source_ids == recomputed.unmatched_source_ids,
                f"source bindings changed: {run_id}",
            )
            if profile == "demo-return-after":
                after_verdicts.append(recomputed.verdict)
            else:
                before_verdicts.append(recomputed.verdict)
            manifest_runs.append({
                "run_id": run_id,
                "dataset_profile": profile,
                "delivery_sha256": _sha256(target_run / "delivery.json"),
                "tool_response_sha256": copied_response_hashes,
                "parent_evidence_sha256": _sha256(source_run / "evidence-check.json"),
                "evidence_sha256": _sha256(target_run / "evidence-check.json"),
                "baseline_verdict": baseline.verdict,
                "v2_verdict": recomputed.verdict,
                "source_bindings_unchanged": True,
            })

        _require(after_verdicts == ["DIRECT_MATCH"] * 3, "After is not 3/3 DIRECT_MATCH")
        _require(before_verdicts == ["UNCONFIRMED"] * 3, "Before verdicts changed")
        _require(_tree_sha256(v1_root) == v1_tree_before, "v1 tree changed during creation")

        manifest = {
            "schema_version": "ax-phase6-product-demo-freeze-v2",
            "hash_algorithm": "SHA-256",
            "parent_manifest_path": V1_MANIFEST_RELATIVE.as_posix(),
            "parent_manifest_sha256": _sha256(parent_manifest_path),
            "parent_tree_sha256": v1_tree_before,
            "checker_commit": CHECKER_COMMIT,
            "checker_source_path": CHECKER_SOURCE_RELATIVE.as_posix(),
            "checker_source_sha256": _sha256(checker_source_path),
            "comparison_report_path": COMPARISON_RELATIVE.as_posix(),
            "comparison_report_sha256": _sha256(comparison_path),
            "policy": "COPY_V1_INPUTS_BY_HASH_AND_RECOMPUTE_EVIDENCE_WITHOUT_OVERWRITING_V1",
            "run_ids": [record["run_id"] for record in manifest_runs],
            "runs": manifest_runs,
            "summary": {
                "run_count": 6,
                "after_direct_match_count": 3,
                "before_unconfirmed_count": 3,
                "changed_evidence_count": sum(
                    record["parent_evidence_sha256"] != record["evidence_sha256"]
                    for record in manifest_runs
                ),
            },
            "artifacts": {"files": _file_records(selected_root, temporary_runs)},
            "verification": {"passed": True, "v1_preserved": True},
        }
        # The temporary directory has a generated name, so normalize artifact paths.
        prefix = _relative(selected_root, temporary_runs)
        expected_prefix = (V2_RELATIVE / "runs").as_posix()
        for record in manifest["artifacts"]["files"]:
            record["path"] = record["path"].replace(prefix, expected_prefix, 1)
        _write_json(temporary / V2_MANIFEST_NAME, manifest)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)

    return verify_phase6_demo_v2(root=selected_root)


def verify_phase6_demo_v2(*, root: str | Path = ROOT) -> dict[str, Any]:
    """Verify parent v1, copied inputs, recomputed evidence, and every v2 hash."""
    selected_root = Path(root).resolve()
    verify_phase6_demo(root=selected_root)
    v1_root = selected_root / V1_RELATIVE
    v2_root = selected_root / V2_RELATIVE
    v2_runs = v2_root / "runs"
    manifest = _load_json(v2_root / V2_MANIFEST_NAME)
    _require(
        manifest.get("schema_version") == "ax-phase6-product-demo-freeze-v2",
        "v2 manifest schema changed",
    )
    _require(manifest.get("hash_algorithm") == "SHA-256", "v2 hash algorithm changed")
    _require(
        manifest.get("parent_manifest_sha256")
        == _sha256(selected_root / V1_MANIFEST_RELATIVE),
        "v1 parent manifest changed",
    )
    _require(manifest.get("parent_tree_sha256") == _tree_sha256(v1_root), "v1 tree changed")
    _require(manifest.get("checker_commit") == CHECKER_COMMIT, "checker commit changed")
    _require(
        manifest.get("checker_source_sha256")
        == _sha256(selected_root / CHECKER_SOURCE_RELATIVE),
        "checker source changed",
    )
    _require(
        manifest.get("comparison_report_sha256")
        == _sha256(selected_root / COMPARISON_RELATIVE),
        "comparison report changed",
    )
    _require(
        sorted(path.name for path in v2_root.iterdir()) == [V2_MANIFEST_NAME, "runs"],
        "unexpected top-level v2 artifact",
    )

    records = manifest.get("runs")
    _require(isinstance(records, list) and len(records) == 6, "v2 run count changed")
    run_ids = manifest.get("run_ids")
    _require(run_ids == [record.get("run_id") for record in records], "v2 run IDs changed")
    _require(
        sorted(path.name for path in v2_runs.iterdir() if path.is_dir()) == sorted(run_ids),
        "v2 run directories changed",
    )
    after_direct = 0
    before_unconfirmed = 0
    changed_evidence = 0
    for record in records:
        run_id = record["run_id"]
        source_run = v1_root / "runs" / run_id
        target_run = v2_runs / run_id
        expected_files = {"delivery.json", "evidence-check.json"}
        actual_top = {path.name for path in target_run.iterdir()}
        if (source_run / "tool-responses").is_dir():
            expected_files.add("tool-responses")
        _require(actual_top == expected_files, f"unexpected v2 run artifact: {run_id}")
        _require(
            (source_run / "delivery.json").read_bytes()
            == (target_run / "delivery.json").read_bytes(),
            f"v2 delivery differs from v1: {run_id}",
        )
        source_responses = sorted((source_run / "tool-responses").glob("*.json"))
        target_responses = sorted((target_run / "tool-responses").glob("*.json"))
        _require(
            [path.name for path in source_responses] == [path.name for path in target_responses]
            and [path.read_bytes() for path in source_responses]
            == [path.read_bytes() for path in target_responses],
            f"v2 tool responses differ from v1: {run_id}",
        )
        baseline = EvidenceCheckResult.model_validate_json(
            (source_run / "evidence-check.json").read_text(encoding="utf-8")
        )
        stored = EvidenceCheckResult.model_validate_json(
            (target_run / "evidence-check.json").read_text(encoding="utf-8")
        )
        recomputed = check_run(v2_runs, run_id)
        _require(stored == recomputed, f"stored v2 evidence is not reproducible: {run_id}")
        _require(
            baseline.matched_source_ids == stored.matched_source_ids
            and baseline.unmatched_source_ids == stored.unmatched_source_ids,
            f"v2 source bindings changed: {run_id}",
        )
        _require(record.get("delivery_sha256") == _sha256(target_run / "delivery.json"), f"delivery hash mismatch: {run_id}")
        _require(record.get("tool_response_sha256") == [_sha256(path) for path in target_responses], f"tool response hash mismatch: {run_id}")
        _require(record.get("parent_evidence_sha256") == _sha256(source_run / "evidence-check.json"), f"parent evidence hash mismatch: {run_id}")
        _require(record.get("evidence_sha256") == _sha256(target_run / "evidence-check.json"), f"v2 evidence hash mismatch: {run_id}")
        _require(record.get("baseline_verdict") == baseline.verdict, f"baseline verdict mismatch: {run_id}")
        _require(record.get("v2_verdict") == stored.verdict, f"v2 verdict mismatch: {run_id}")
        if record["dataset_profile"] == "demo-return-after":
            _require(stored.verdict == "DIRECT_MATCH", f"After is not direct: {run_id}")
            after_direct += 1
        else:
            _require(stored.verdict == "UNCONFIRMED", f"Before changed: {run_id}")
            before_unconfirmed += 1
        changed_evidence += record["parent_evidence_sha256"] != record["evidence_sha256"]

    _require(manifest.get("artifacts", {}).get("files") == _file_records(selected_root, v2_runs), "v2 file inventory changed")
    expected_summary = {
        "run_count": 6,
        "after_direct_match_count": after_direct,
        "before_unconfirmed_count": before_unconfirmed,
        "changed_evidence_count": changed_evidence,
    }
    _require(manifest.get("summary") == expected_summary, "v2 summary changed")
    _require(after_direct == 3 and before_unconfirmed == 3, "v2 verdict threshold failed")
    _require(not list(v2_root.rglob("state.json")), "v2 contains mutable run state")
    return {
        "freeze_verified": True,
        "passed": True,
        **expected_summary,
        "frozen_file_count": len(manifest["artifacts"]["files"]),
        "parent_manifest_sha256": manifest["parent_manifest_sha256"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()
    result = create_phase6_demo_v2() if args.create else verify_phase6_demo_v2()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
