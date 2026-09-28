"""Close the two confirmed-stale Phase 6 diagnostic runs as runtime errors."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ax_product.evidence import EvidenceCheckStore, check_run
from ax_product.models import DeliveryEnvelope
from ax_product.results import ResultStore


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "phase6_product_demo"
RECEIPT_PATH = ARTIFACT_ROOT / "DIAGNOSTIC_CLOSURE.json"
MODEL = "claude-sonnet-5"
DIAGNOSTICS = {
    "phase6demo-diagnostic-after-001": "diagnostic-001",
    "phase6demo-diagnostic-after-002": "diagnostic-002",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_once(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def close_diagnostics(*, process_check_at: str) -> Path:
    if RECEIPT_PATH.exists():
        raise FileExistsError(f"diagnostic receipt already exists: {RECEIPT_PATH}")
    checked_at = datetime.fromisoformat(process_check_at.replace("Z", "+00:00"))
    if checked_at.tzinfo is None:
        raise ValueError("process-check-at must include a timezone")

    observed: list[tuple[str, str, Path, dict[str, Any]]] = []
    for run_id, label in DIAGNOSTICS.items():
        results_root = ARTIFACT_ROOT / "pilots" / label / "runs"
        state_path = results_root / run_id / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        expected = {
            "run_id": run_id,
            "run_status": "RUNNING",
            "dataset": "demo-return-after",
        }
        if state != expected:
            raise ValueError(f"unexpected diagnostic state for {run_id}: {state}")
        if (state_path.parent / "delivery.json").exists():
            raise FileExistsError(f"diagnostic delivery already exists: {run_id}")
        if (state_path.parent / "evidence-check.json").exists():
            raise FileExistsError(f"diagnostic evidence already exists: {run_id}")
        observed.append((run_id, label, results_root, state))

    entries: list[dict[str, Any]] = []
    for run_id, _label, results_root, state in observed:
        store = ResultStore(results_root)
        delivery_path = store.write(DeliveryEnvelope(
            delivery_status="REJECTED",
            run_id=run_id,
            model=MODEL,
            reject_reason="RUNTIME_ERROR",
        ))
        evidence_path = EvidenceCheckStore(results_root).write(
            check_run(results_root, run_id)
        )
        delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
        if delivery["dataset"] != state["dataset"]:
            raise ValueError(f"ResultStore did not preserve dataset for {run_id}")
        entries.append({
            "run_id": run_id,
            "dataset": delivery["dataset"],
            "stale_running_state_observed": True,
            "previous_state": state,
            "closure_reason": (
                "The persisted RUNNING reservation had no matching live process; "
                "the ResultStore contract requires a terminal RUNTIME_ERROR rejection."
            ),
            "delivery_status": delivery["delivery_status"],
            "reject_reason": delivery["reject_reason"],
            "delivery_path": delivery_path.relative_to(ROOT).as_posix(),
            "delivery_sha256": _sha256(delivery_path),
            "evidence_check_path": evidence_path.relative_to(ROOT).as_posix(),
            "evidence_check_sha256": _sha256(evidence_path),
        })

    receipt = {
        "schema_version": "ax-phase6-diagnostic-closure-v1",
        "claim_scope": "PRODUCT_SANITY_DEMO_NOT_RESEARCH_BENCHMARK",
        "process_check_at": checked_at.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "active_process_count": 0,
        "process_check_scope": list(DIAGNOSTICS),
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runs": entries,
    }
    _write_json_once(RECEIPT_PATH, receipt)
    return RECEIPT_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process-check-at", required=True)
    args = parser.parse_args()
    path = close_diagnostics(process_check_at=args.process_check_at)
    print(path.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
