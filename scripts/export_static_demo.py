"""Export the verified read-only AX demo as a deterministic static snapshot."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ax_product.api import (
    FROZEN_RESULTS_ROOT_ENV,
    PHASE6_FROZEN_V4_RESULTS_ROOT,
    create_read_only_app_from_env,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "results_console" / "public" / "static-demo.json"


def _get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def _validate_featured_cases(snapshot: dict[str, Any]) -> None:
    """Fail export when a promoted case drifts from the verified frozen facts."""
    for case in snapshot["featured_cases"]:
        before = case["before"]
        after = case["after"]
        walkthrough = case.get("walkthrough") or {}
        if (
            walkthrough.get("schema_version") != "ax-frozen-poc-walkthrough-v1"
            or walkthrough.get("label") != "검증된 동결 예시"
            or walkthrough.get("read_only") is not True
            or walkthrough.get("snapshot_id") != "phase6-v4"
            or walkthrough.get("recommendation") != "CONDITIONAL_GO"
            or walkthrough.get("approved_task_id") != "TASK_POLICY_RETURN_WINDOW"
            or walkthrough.get("successful_runs") != 3
            or walkthrough.get("direct_evidence_runs") != 3
            or walkthrough.get("direct_evidence_ratio") != 1.0
            or not walkthrough.get("cited_source_ids")
        ):
            raise ValueError("Featured PoC walkthrough no longer matches verified facts")
        gate_statuses = {
            gate.get("code"): gate.get("status")
            for gate in walkthrough.get("gates", [])
        }
        if gate_statuses != {
            "EXECUTION_SAMPLE": "PASS",
            "DIRECT_EVIDENCE": "PASS",
            "MODEL_BOUNDARY": "WARN",
            "COST_CONTROL": "WARN",
            "AUDIT_RETENTION": "WARN",
        }:
            raise ValueError("Featured PoC gate summary no longer matches verified facts")
        for reference in (before, after):
            run = snapshot["runs"].get(reference["run_id"])
            evidence = snapshot["evidence"].get(reference["run_id"])
            if run is None or evidence is None:
                raise ValueError(f"Featured run is missing: {reference['run_id']}")
            if run.get("dataset") != reference["dataset"]:
                raise ValueError(f"Featured run dataset mismatch: {reference['run_id']}")
            if run.get("task_id") != "TASK_POLICY_RETURN_WINDOW":
                raise ValueError(f"Featured run task mismatch: {reference['run_id']}")

        before_payload = snapshot["runs"][before["run_id"]].get("payload") or {}
        after_payload = snapshot["runs"][after["run_id"]].get("payload") or {}
        if before_payload.get("status") != "ABSTAINED" or before_payload.get("abstention_reason") != "CONFLICTING_EVIDENCE":
            raise ValueError("Featured Before run no longer represents conflicting evidence")
        if after_payload.get("status") != "ANSWERED" or after_payload.get("answer") != "30일":
            raise ValueError("Featured After run no longer answers 30 days")
        if snapshot["evidence"][after["run_id"]].get("verdict") != "DIRECT_MATCH":
            raise ValueError("Featured After run no longer has DIRECT_MATCH evidence")
        after_trace = snapshot["retrieval_traces"].get(after["run_id"])
        if after_trace is None or not any(
            step.get("cited_source_ids") for step in after_trace.get("steps", [])
        ):
            raise ValueError("Featured After run no longer has a cited retrieval path")
        traced_source_ids = {
            source_id
            for step in after_trace.get("steps", [])
            for source_id in step.get("cited_source_ids", [])
        }
        if not set(walkthrough["cited_source_ids"]).issubset(traced_source_ids):
            raise ValueError("Featured PoC citations are not in the verified retrieval path")

        comparison = next(
            (
                item.get("comparison")
                for item in snapshot["findings"][after["dataset"]]["findings"]
                if item.get("finding_type") == "CONFLICTING_SOURCES"
                and item.get("comparison_status") == "NOT_REPRODUCED_AFTER"
            ),
            None,
        )
        if comparison is None or (
            comparison.get("before_observed_run_count"),
            comparison.get("before_abstained_run_count"),
            comparison.get("after_observed_run_count"),
            comparison.get("after_answered_run_count"),
        ) != (3, 3, 3, 3):
            raise ValueError("Featured case no longer has the verified 0/3 to 3/3 comparison")


def build_static_demo_snapshot() -> dict[str, Any]:
    """Return all responses needed by the public read-only console."""
    previous = os.environ.get(FROZEN_RESULTS_ROOT_ENV)
    os.environ[FROZEN_RESULTS_ROOT_ENV] = str(PHASE6_FROZEN_V4_RESULTS_ROOT)
    try:
        client = TestClient(create_read_only_app_from_env())
    finally:
        if previous is None:
            os.environ.pop(FROZEN_RESULTS_ROOT_ENV, None)
        else:
            os.environ[FROZEN_RESULTS_ROOT_ENV] = previous

    datasets = _get(client, "/api/datasets")
    profiles = [item["profile"] for item in datasets["datasets"]]
    snapshot: dict[str, Any] = {
        "schema_version": "ax-static-demo-v5",
        "read_only": True,
        "default_dataset": "portfolio-hidden-conflict-before",
        "featured_cases": _get(client, "/api/featured-cases")["featured_cases"],
        "datasets": datasets,
        "readiness": {},
        "onboarding": {},
        "tasks": {},
        "findings": {},
        "runs": {},
        "evidence": {},
        "retrieval_traces": {},
    }
    for profile in profiles:
        snapshot["readiness"][profile] = _get(client, f"/api/readiness/{profile}")
        snapshot["onboarding"][profile] = _get(
            client, f"/api/onboarding/{profile}"
        )
        snapshot["tasks"][profile] = _get(client, f"/api/tasks/{profile}")
        snapshot["findings"][profile] = _get(client, f"/api/findings/{profile}")

    for run_dir in sorted(PHASE6_FROZEN_V4_RESULTS_ROOT.iterdir()):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        snapshot["runs"][run_id] = _get(client, f"/api/runs/{run_id}")
        evidence = client.get(f"/api/runs/{run_id}/evidence-check")
        if evidence.status_code == 200:
            snapshot["evidence"][run_id] = evidence.json()
        elif evidence.status_code != 404:
            evidence.raise_for_status()
        snapshot["retrieval_traces"][run_id] = _get(
            client, f"/api/runs/{run_id}/retrieval-trace"
        )
    _validate_featured_cases(snapshot)
    return snapshot


def write_snapshot(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            build_static_demo_snapshot(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    write_snapshot(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
