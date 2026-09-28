"""Estimate or run the 60-run Phase 6 v4 repeated portfolio pilot."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from scripts.run_candidate_portfolio import DEFAULT_MODEL, execute
from scripts.verify_phase6_demo_v3 import verify_phase6_demo_v3


ROOT = Path(__file__).resolve().parents[1]
V3_SUMMARY = ROOT / "artifacts" / "phase6_product_demo_v3" / "SUMMARY.json"
V4_FROZEN = ROOT / "artifacts" / "phase6_product_demo_v4"
PILOT_ROOT = ROOT / "_review_v2" / "phase6_product_demo_v4"
RESULTS_ROOT = PILOT_ROOT / "runs"
SUMMARY_PATH = PILOT_ROOT / "summary.json"
CONFIG = ROOT / "runtime_datasets.json"
CATALOG = ROOT / "business_task_catalog.json"
PROFILES = ["portfolio-hidden-conflict-before", "portfolio-ceiling-after"]
TASK_COUNT = 10
REPETITIONS = 3
EXPECTED_RUN_COUNT = len(PROFILES) * TASK_COUNT * REPETITIONS


def estimate_runtime(summary_path: Path = V3_SUMMARY) -> dict[str, Any]:
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    durations = [
        float(row["duration_seconds"])
        for row in summary.get("runs", [])
        if row.get("dataset") in PROFILES
        and isinstance(row.get("duration_seconds"), (int, float))
        and float(row["duration_seconds"]) >= 0
    ]
    if len(durations) != 20:
        raise ValueError("v3 summary must contain exactly 20 portfolio durations")
    mean_seconds = statistics.fmean(durations)
    median_seconds = statistics.median(durations)
    estimated_seconds = mean_seconds * EXPECTED_RUN_COUNT
    return {
        "schema_version": "ax-phase6-v4-runtime-estimate-v1",
        "historical_snapshot": "artifacts/phase6_product_demo_v3/SUMMARY.json",
        "historical_run_count": len(durations),
        "planned_run_count": EXPECTED_RUN_COUNT,
        "mean_seconds_per_run": round(mean_seconds, 3),
        "median_seconds_per_run": round(median_seconds, 3),
        "estimated_seconds": round(estimated_seconds, 1),
        "estimated_minutes": round(estimated_seconds / 60, 1),
        "planning_minutes_with_25_percent_buffer": round(estimated_seconds * 1.25 / 60, 1),
    }


def run(
    *, model: str = DEFAULT_MODEL, timeout_seconds: float = 300.0,
    kiro_cli: str | None = None,
) -> dict[str, Any]:
    if V4_FROZEN.exists():
        raise FileExistsError(f"frozen v4 already exists: {V4_FROZEN}")
    verify_phase6_demo_v3(root=ROOT)
    PILOT_ROOT.mkdir(parents=True, exist_ok=True)
    estimate = estimate_runtime()
    (PILOT_ROOT / "RUNTIME_ESTIMATE.json").write_text(
        json.dumps(estimate, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    summary = execute(
        profiles=PROFILES,
        results_root=RESULTS_ROOT,
        summary_path=SUMMARY_PATH,
        dataset_config=CONFIG,
        catalog_path=CATALOG,
        task_ids=[],
        repetitions=REPETITIONS,
        model=model,
        timeout_seconds=timeout_seconds,
        kiro_cli=kiro_cli,
        run_namespace="phase6v4",
    )
    if len(summary["runs"]) != EXPECTED_RUN_COUNT:
        raise ValueError("v4 pilot did not produce exactly 60 run records")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("estimate")
    runner = subparsers.add_parser("run")
    runner.add_argument("--model", default=DEFAULT_MODEL)
    runner.add_argument("--timeout-seconds", type=float, default=300.0)
    runner.add_argument("--kiro-cli")
    args = parser.parse_args()
    if args.command == "estimate":
        result = estimate_runtime()
    else:
        result = run(
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            kiro_cli=args.kiro_cli,
        )
        result = {
            "summary": SUMMARY_PATH.relative_to(ROOT).as_posix(),
            "run_count": len(result["runs"]),
            "profile_summaries": result["profile_summaries"],
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
