"""Prepare and execute the Phase 6 return-policy product demo.

This is a product sanity runner, not a research benchmark runner.  It calls the
existing Product API with KiroProductRunner, and treats only delivery.json plus
the run-bound evidence check as authoritative.  Kiro stdout/finalText is never
persisted or aggregated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from ax_mcp.runtime_dataset import (
    resolve_runtime_dataset,
    runtime_identity,
    validate_runtime_resource_leakage,
)
from ax_product.api import create_app
from ax_product.runner import KiroProductRunner
from ax_scanner.models import ScanReport
from readiness_score import calculate_readiness_score, score_scan_report_file


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "phase6_product_demo"
FREEZE_RECEIPT = ARTIFACT_ROOT / "FROZEN_MANIFEST.json"
CONFIG = ROOT / "runtime_datasets.json"
QUESTION_PATH = ROOT / "sample_data" / "product_demo" / "question.txt"
PROFILES = ("demo-return-before", "demo-return-after")
SCAN_PATHS = {
    "demo-return-before": ARTIFACT_ROOT / "before-scan-report.json",
    "demo-return-after": ARTIFACT_ROOT / "after-scan-report.json",
}
FIXED_SOURCE_MTIME = "2026-09-01T00:00:00+00:00"
DEFAULT_MODEL = "claude-sonnet-5"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _official_freeze_markers() -> list[Path]:
    """Return markers that make the official static/result artifacts immutable."""
    return [
        path for path in (
            ARTIFACT_ROOT / "run-manifest.json",
            FREEZE_RECEIPT,
        ) if path.exists()
    ]


def _require_unfrozen_official_artifacts() -> None:
    markers = _official_freeze_markers()
    if markers:
        names = ", ".join(path.name for path in markers)
        raise FileExistsError(
            f"Phase 6 official artifacts are write-once ({names}); "
            "do not run Scanner or overwrite static artifacts"
        )


def _load_frozen_static_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify and read frozen static inputs for a post-official pilot."""
    if not FREEZE_RECEIPT.is_file():
        raise FileNotFoundError(
            "official results exist without FROZEN_MANIFEST.json; freeze and verify "
            "them before starting another pilot"
        )
    # Import lazily so the verifier remains an independently runnable module.
    from scripts.verify_phase6_demo import verify_phase6_demo

    verify_phase6_demo(root=ROOT)
    return (
        json.loads(
            (ARTIFACT_ROOT / "dataset-manifest.json").read_text(encoding="utf-8")
        ),
        json.loads(
            (ARTIFACT_ROOT / "remediation-receipt.json").read_text(
                encoding="utf-8"
            )
        ),
    )


def _question() -> tuple[str, str]:
    prompt_bytes = QUESTION_PATH.read_bytes().rstrip(b"\r\n")
    prompt = prompt_bytes.decode("utf-8")
    if not prompt or "\n" in prompt or "\r" in prompt:
        raise ValueError("Phase 6 question must be one nonblank UTF-8 line")
    return prompt, _sha256_bytes(prompt_bytes)


def _source_files(source_root: Path) -> list[dict[str, Any]]:
    files = []
    for path in sorted(item for item in source_root.rglob("*") if item.is_file()):
        relative = path.relative_to(source_root).as_posix()
        modified_at = datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
        files.append({
            "relative_path": relative,
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
            "modified_at": modified_at,
        })
    return files


def _run_scanner(python_executable: str) -> list[dict[str, Any]]:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    scans = []
    for profile in PROFILES:
        source_root = (ROOT / config["profiles"][profile]["source_root"]).resolve()
        timestamp = datetime.fromisoformat(FIXED_SOURCE_MTIME).timestamp()
        for path in source_root.rglob("*"):
            if path.is_file():
                os.utime(path, (timestamp, timestamp))
        process = subprocess.run(
            [
                python_executable,
                "-m",
                "ax_scanner",
                str(source_root),
                "--output",
                str(SCAN_PATHS[profile]),
            ],
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
                f"Scanner failed for {profile}: {process.stderr.strip()}"
            )
        invocation = json.loads(process.stdout.strip())
        output = Path(invocation["output"])
        if not output.is_absolute():
            output = ROOT / output
        invocation["output"] = output.resolve().relative_to(ROOT).as_posix()
        scans.append(invocation)
    return scans


def _observations(report: ScanReport) -> list[dict[str, Any]]:
    return [
        {
            "code": "PROBABLE_VERSION_GROUP",
            "version_group_id": group.version_group_id,
            "normalized_name": group.normalized_name,
            "file_ids": [candidate.file_id for candidate in group.candidates],
        }
        for group in report.probable_version_groups
    ]


def prepare_static_artifacts(
    *, python_executable: str = sys.executable
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the real Scanner and write reproducible demo/remediation receipts."""
    _require_unfrozen_official_artifacts()
    scans = _run_scanner(python_executable)
    question, question_sha256 = _question()
    profiles: dict[str, Any] = {}
    reports: dict[str, ScanReport] = {}
    readiness: dict[str, dict[str, Any]] = {}

    for profile in PROFILES:
        dataset = resolve_runtime_dataset(profile, CONFIG)
        source_files = _source_files(dataset.source_root)
        if len(source_files) != 2:
            raise ValueError(f"{profile} must contain exactly two source files")
        if {item["modified_at"] for item in source_files} != {FIXED_SOURCE_MTIME}:
            raise ValueError(
                f"{profile} source timestamps must all equal {FIXED_SOURCE_MTIME}"
            )
        identity = runtime_identity(dataset)
        leakage = validate_runtime_resource_leakage(dataset)
        if not leakage["passed"]:
            raise ValueError(f"runtime leakage in {profile}: {leakage['violations']}")
        report = ScanReport.model_validate_json(
            dataset.scan_report.read_text(encoding="utf-8")
        )
        reports[profile] = report
        readiness[profile] = score_scan_report_file(dataset.scan_report)
        profiles[profile] = {
            "dataset_name": dataset.dataset_name,
            "source_root": dataset.source_root.relative_to(ROOT).as_posix(),
            "scan_report": dataset.scan_report.relative_to(ROOT).as_posix(),
            "scan_report_sha256": _sha256(dataset.scan_report),
            "files": source_files,
            "file_count": len(source_files),
            "runtime_identity": identity,
            "runtime_leakage": leakage,
            "readiness": readiness[profile],
            "unscored_observations": _observations(report),
        }

    before = readiness[PROFILES[0]]
    after = readiness[PROFILES[1]]
    if before["readiness_score"] != after["readiness_score"]:
        raise ValueError("before/after readiness totals differ")
    if before["dimensions"] != after["dimensions"]:
        raise ValueError("before/after readiness dimensions differ")
    if not reports[PROFILES[0]].probable_version_groups:
        raise ValueError("before dataset lacks PROBABLE_VERSION_GROUP")
    if len(reports[PROFILES[1]].probable_version_groups) >= len(
        reports[PROFILES[0]].probable_version_groups
    ):
        raise ValueError("after version-group count did not decrease")

    # Readiness v1 must be invariant to the unscored observation list.
    for profile, report in reports.items():
        without_observations = report.model_copy(
            update={"probable_version_groups": []}, deep=True
        )
        unscored_readiness = calculate_readiness_score(
            without_observations.model_dump(mode="json")
        )
        if unscored_readiness != readiness[profile]:
            raise ValueError(f"unscored observations changed readiness for {profile}")

    dataset_manifest = {
        "schema_version": "ax-phase6-product-demo-dataset-manifest-v1",
        "claim_scope": "PRODUCT_SANITY_DEMO_NOT_RESEARCH_BENCHMARK",
        "question": question,
        "question_utf8_sha256": question_sha256,
        "scanner_invocations": scans,
        "profiles": profiles,
    }
    before_report = reports[PROFILES[0]]
    after_report = reports[PROFILES[1]]
    remediation_receipt = {
        "schema_version": "ax-phase6-remediation-receipt-v1",
        "claim_scope": "PRODUCT_SANITY_DEMO_NOT_RESEARCH_BENCHMARK",
        "source_file_count_before": len(profiles[PROFILES[0]]["files"]),
        "source_file_count_after": len(profiles[PROFILES[1]]["files"]),
        "controlled_modified_at": FIXED_SOURCE_MTIME,
        "before": {
            "profile": PROFILES[0],
            "policy_state": "two unresolved current-looking claims: 14 days and 30 days",
            "probable_version_group_count": len(before_report.probable_version_groups),
            "source_ids": [file.file_id for file in before_report.files],
        },
        "after": {
            "profile": PROFILES[1],
            "policy_state": "30-day current policy; 14-day policy explicitly retired and replaced",
            "probable_version_group_count": len(after_report.probable_version_groups),
            "current_policy_source_id": next(
                file.file_id
                for file in after_report.files
                if file.relative_path == "policies/반품_정책_운영기준.txt"
            ),
            "retired_policy_source_id": next(
                file.file_id
                for file in after_report.files
                if file.relative_path == "policies/반품_정책_변경기록.txt"
            ),
        },
        "readiness_comparison": {
            "same_total": before["readiness_score"] == after["readiness_score"],
            "same_dimensions": before["dimensions"] == after["dimensions"],
            "before_total": before["readiness_score"],
            "after_total": after["readiness_score"],
            "before_dimensions": before["dimensions"],
            "after_dimensions": after["dimensions"],
        },
        "unscored_observation_policy": (
            "PROBABLE_VERSION_GROUP is reported separately and is not an input "
            "to frozen Readiness Score v1."
        ),
    }
    _write_json(ARTIFACT_ROOT / "dataset-manifest.json", dataset_manifest)
    _write_json(ARTIFACT_ROOT / "remediation-receipt.json", remediation_receipt)
    return dataset_manifest, remediation_receipt


def build_schedule(repetitions: int) -> list[tuple[int, str, int]]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    schedule = []
    for repetition in range(1, repetitions + 1):
        for profile in PROFILES:
            schedule.append((len(schedule) + 1, profile, repetition))
    return schedule


def request_payload(
    *, profile: str, run_id: str, model: str, question: str
) -> dict[str, str]:
    return {
        "dataset": profile,
        "request_type": "AD_HOC_QUESTION",
        "question": question,
        "run_id": run_id,
        "model": model,
    }


def _kiro_executable(override: str | None) -> str:
    executable = override or shutil.which("kiro-cli") or shutil.which("kiro-cli.exe")
    if executable is None:
        raise FileNotFoundError("kiro-cli executable not found")
    return executable


def _kiro_version(executable: str) -> str:
    process = subprocess.run(
        [executable, "--version"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=30,
    )
    if process.returncode != 0:
        raise RuntimeError(f"kiro-cli --version failed: {process.stderr.strip()}")
    return process.stdout.strip()


def _run_record(
    *,
    client: TestClient,
    results_root: Path,
    run_id: str,
    order: int,
    repetition: int,
    profile: str,
    model: str,
    question: str,
    question_sha256: str,
    kiro_version: str,
    profile_manifest: dict[str, Any],
) -> dict[str, Any]:
    started_at = _utc_now()
    response = client.post("/api/run", json=request_payload(
        profile=profile, run_id=run_id, model=model, question=question
    ))
    ended_at = _utc_now()
    response.raise_for_status()
    delivery = response.json()
    delivery_path = results_root / run_id / "delivery.json"
    evidence_path = results_root / run_id / "evidence-check.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload = delivery.get("payload") or {}
    tool_response_count = len(list(
        (results_root / run_id / "tool-responses").glob("*.json")
    ))
    return {
        "run_id": run_id,
        "dataset_profile": profile,
        "execution_order": order,
        "repetition": repetition,
        "model": model,
        "started_at": started_at,
        "ended_at": ended_at,
        "kiro_cli_version": kiro_version,
        "question_utf8_sha256": question_sha256,
        "readiness_total": profile_manifest["readiness"]["readiness_score"],
        "readiness_dimensions": profile_manifest["readiness"]["dimensions"],
        "unscored_observation_count": len(
            profile_manifest["unscored_observations"]
        ),
        "unscored_observation_codes": sorted({
            item["code"] for item in profile_manifest["unscored_observations"]
        }),
        "delivery_status": delivery["delivery_status"],
        "payload_status": payload.get("status"),
        "abstention_reason": payload.get("abstention_reason"),
        "source_ids": payload.get("source_ids", []),
        "evidence_verdict": evidence["verdict"],
        "delivery_sha256": _sha256(delivery_path),
        "evidence_check_sha256": _sha256(evidence_path),
        "tool_response_count": tool_response_count,
        "run_artifact_directory": (
            results_root / run_id
        ).relative_to(ROOT).as_posix(),
    }


def _outcome(record: dict[str, Any]) -> str:
    if record["delivery_status"] == "REJECTED":
        return "REJECTED"
    return record["payload_status"] or "REJECTED"


def summarize_runs(
    records: list[dict[str, Any]], remediation: dict[str, Any], *, mode: str
) -> dict[str, Any]:
    by_profile = {profile: [r for r in records if r["dataset_profile"] == profile]
                  for profile in PROFILES}
    frequencies = {
        profile: dict(Counter(_outcome(record) for record in profile_records))
        for profile, profile_records in by_profile.items()
    }
    for values in frequencies.values():
        for status in ("ANSWERED", "ABSTAINED", "REJECTED"):
            values.setdefault(status, 0)

    before_conflicts = sum(
        record["payload_status"] == "ABSTAINED"
        and record["abstention_reason"] == "CONFLICTING_EVIDENCE"
        for record in by_profile[PROFILES[0]]
    )
    after_answers = sum(
        record["payload_status"] == "ANSWERED"
        for record in by_profile[PROFILES[1]]
    )
    expected_threshold = 2 if mode == "official" else 1
    before_sources = set(remediation["before"]["source_ids"])
    current_source = remediation["after"]["current_policy_source_id"]
    conflict_runs_with_both_sources = sum(
        record["payload_status"] == "ABSTAINED"
        and record["abstention_reason"] == "CONFLICTING_EVIDENCE"
        and before_sources.issubset(record["source_ids"])
        for record in by_profile[PROFILES[0]]
    )
    answered_runs_with_current_source = sum(
        record["payload_status"] == "ANSWERED"
        and current_source in record["source_ids"]
        for record in by_profile[PROFILES[1]]
    )
    return {
        "schema_version": "ax-phase6-product-demo-summary-v1",
        "claim_scope": "PRODUCT_SANITY_DEMO_NOT_RESEARCH_BENCHMARK",
        "mode": mode,
        "run_count": len(records),
        "run_ids": [record["run_id"] for record in records],
        "frequencies": frequencies,
        "abstention_reasons": [
            {"run_id": record["run_id"], "reason": record["abstention_reason"]}
            for record in records if record["payload_status"] == "ABSTAINED"
        ],
        "sanity_criteria": {
            "threshold": expected_threshold,
            "before_conflicting_abstention_count": before_conflicts,
            "before_passed": before_conflicts >= expected_threshold,
            "after_answered_count": after_answers,
            "after_passed": after_answers >= expected_threshold,
            "passed": (
                before_conflicts >= expected_threshold
                and after_answers >= expected_threshold
            ),
        },
        "citation_checks": {
            "before_conflict_runs_with_both_sources": conflict_runs_with_both_sources,
            "after_answered_runs_with_current_source": answered_runs_with_current_source,
        },
        "runs": records,
    }


def _results_markdown(
    manifest: dict[str, Any], remediation: dict[str, Any], summary: dict[str, Any]
) -> str:
    readiness = remediation["readiness_comparison"]
    lines = [
        "# Phase 6 Product Demo Results",
        "",
        f"- Scope: `{summary['claim_scope']}`",
        f"- Question: {manifest['question']}",
        f"- Model: `{summary['runs'][0]['model'] if summary['runs'] else 'N/A'}`",
        f"- Mode: `{summary['mode']}`",
        f"- Runs: {summary['run_count']}",
        f"- Sanity criterion: {'PASS' if summary['sanity_criteria']['passed'] else 'FAIL'}",
        "",
        "This is a product sanity/demo result. It is not merged into v3/v5 metrics "
        "and is not claimed as a new research benchmark result.",
        "",
        "## Static comparison",
        "",
        "| State | Readiness | Accessibility | Completeness | Redundancy | Timeliness | Safety | Version warnings |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for profile in PROFILES:
        profile_data = manifest["profiles"][profile]
        dimensions = profile_data["readiness"]["dimensions"]
        lines.append(
            f"| {profile} | {profile_data['readiness']['readiness_score']} | "
            f"{dimensions['accessibility']} | {dimensions['completeness']} | "
            f"{dimensions['redundancy']} | {dimensions['timeliness']} | "
            f"{dimensions['safety']} | {len(profile_data['unscored_observations'])} |"
        )
    lines.extend([
        "",
        f"Totals equal: `{readiness['same_total']}`; all five dimensions equal: "
        f"`{readiness['same_dimensions']}`.",
        "",
        "## Run results",
        "",
        "| # | Run ID | Profile | Delivery | Payload | Abstention reason | Source IDs | Evidence |",
        "|---:|---|---|---|---|---|---|---|",
    ])
    for record in summary["runs"]:
        sources = ", ".join(record["source_ids"]) or "-"
        lines.append(
            f"| {record['execution_order']} | `{record['run_id']}` | "
            f"{record['dataset_profile']} | {record['delivery_status']} | "
            f"{record['payload_status'] or '-'} | "
            f"{record['abstention_reason'] or '-'} | {sources} | "
            f"{record['evidence_verdict']} |"
        )
    lines.extend([
        "",
        "## Observed frequencies",
        "",
    ])
    for profile in PROFILES:
        freq = summary["frequencies"][profile]
        lines.append(
            f"- {profile}: ANSWERED {freq['ANSWERED']}, "
            f"ABSTAINED {freq['ABSTAINED']}, REJECTED {freq['REJECTED']}"
        )
    lines.extend([
        "",
        f"The observed frequencies are stochastic outcomes from these "
        f"{summary['run_count']} runs; they are not a guarantee of future behavior.",
        "",
    ])
    return "\n".join(lines)


def execute(
    *,
    mode: str,
    repetitions: int,
    model: str,
    timeout_seconds: float,
    kiro_cli: str | None,
    execution_id: str | None,
) -> dict[str, Any]:
    if mode == "official" and repetitions != 3:
        raise ValueError("official mode requires exactly three repetitions per profile")
    label = execution_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if mode == "official":
        # This guard must precede Scanner, Kiro discovery, and every file write.
        _require_unfrozen_official_artifacts()
        results_root = ARTIFACT_ROOT / "runs"
        output_root = ARTIFACT_ROOT
        manifest, remediation = prepare_static_artifacts(
            python_executable=sys.executable
        )
    else:
        output_root = ARTIFACT_ROOT / "pilots" / label
        results_root = output_root / "runs"
        if output_root.exists():
            raise FileExistsError(f"pilot execution already exists: {output_root}")
        if _official_freeze_markers():
            manifest, remediation = _load_frozen_static_artifacts()
        else:
            manifest, remediation = prepare_static_artifacts(
                python_executable=sys.executable
            )
    question, question_sha256 = _question()
    if question_sha256 != manifest["question_utf8_sha256"]:
        raise ValueError("question changed after static preparation")
    executable = _kiro_executable(kiro_cli)
    version = _kiro_version(executable)
    output_root.mkdir(parents=True, exist_ok=True)
    runner = KiroProductRunner(
        project_root=ROOT,
        dataset_config=CONFIG,
        executable=executable,
        timeout_seconds=timeout_seconds,
        python_executable=sys.executable,
    )
    client = TestClient(create_app(
        results_root=results_root, dataset_config=CONFIG, runner=runner
    ))
    records = []
    run_manifest = {
        "schema_version": "ax-phase6-product-demo-run-manifest-v1",
        "claim_scope": "PRODUCT_SANITY_DEMO_NOT_RESEARCH_BENCHMARK",
        "mode": mode,
        "execution_id": label,
        "question_utf8_sha256": question_sha256,
        "model": model,
        "kiro_cli_version": version,
        "fresh_process_per_run": True,
        "raw_kiro_output_used_as_product_result": False,
        "raw_kiro_output_persisted_as_customer_log": False,
        "runs": records,
    }
    _write_json(output_root / "run-manifest.json", run_manifest)
    for order, profile, repetition in build_schedule(repetitions):
        suffix = uuid4().hex[:8]
        state = "before" if profile == PROFILES[0] else "after"
        run_id = f"phase6demo-{mode}-{label}-{order:02d}-{state}-{suffix}"
        record = _run_record(
            client=client,
            results_root=results_root,
            run_id=run_id,
            order=order,
            repetition=repetition,
            profile=profile,
            model=model,
            question=question,
            question_sha256=question_sha256,
            kiro_version=version,
            profile_manifest=manifest["profiles"][profile],
        )
        records.append(record)
        _write_json(output_root / "run-manifest.json", run_manifest)
    summary = summarize_runs(records, remediation, mode=mode)
    _write_json(output_root / "summary.json", summary)
    (output_root / "RESULTS.md").write_text(
        _results_markdown(manifest, remediation, summary), encoding="utf-8"
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pilot", "official"), default="official")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--kiro-cli")
    parser.add_argument("--execution-id")
    parser.add_argument(
        "--prepare-only", action="store_true",
        help="run Scanner and write static receipts without starting Kiro",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.prepare_only:
        prepare_static_artifacts(python_executable=sys.executable)
        print(str(ARTIFACT_ROOT))
        return 0
    repetitions = args.repetitions or (3 if args.mode == "official" else 1)
    summary = execute(
        mode=args.mode,
        repetitions=repetitions,
        model=args.model,
        timeout_seconds=args.timeout_seconds,
        kiro_cli=args.kiro_cli,
        execution_id=args.execution_id,
    )
    print(json.dumps({
        "run_count": summary["run_count"],
        "sanity_passed": summary["sanity_criteria"]["passed"],
        "run_ids": summary["run_ids"],
    }, ensure_ascii=False))
    return 0 if summary["sanity_criteria"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
