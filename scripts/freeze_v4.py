"""Freeze the prepared v4 design before any candidate held-out Kiro run."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.v4_preflight import ROOT, validate_manifest
from scripts.verify_v4_candidate_truth import verify as verify_truth
from scripts.validate_v4_tool_access import validate as validate_access


CANDIDATE = ROOT / "experiment" / "v4" / "CANDIDATE_MANIFEST.json"
FROZEN = ROOT / "experiment" / "frozen" / "ax-exp-v4-manifest.json"
OFFICIAL_RUNS = ROOT / "artifacts" / "heldout_ax-exp-v4"


def main() -> int:
    if FROZEN.exists():
        raise FileExistsError(f"v4 is already frozen: {FROZEN}")
    if OFFICIAL_RUNS.exists():
        raise ValueError("official v4 artifact directory already exists before freeze")
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    if candidate.get("status") != "DRAFT":
        raise ValueError("freeze requires a DRAFT candidate")
    errors = validate_manifest(candidate, require_ready=False)
    errors.extend(verify_truth())
    access = validate_access()
    errors.extend(access["errors"])
    if errors:
        raise ValueError(f"v4 freeze preflight failed: {errors}")
    frozen = copy.deepcopy(candidate)
    frozen["status"] = "FROZEN"
    frozen["freeze_timestamp_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    frozen["candidate_manifest_sha256"] = hashlib.sha256(CANDIDATE.read_bytes()).hexdigest()
    ready_errors = validate_manifest(frozen)
    if ready_errors:
        raise ValueError(f"v4 frozen candidate fails ready preflight: {ready_errors}")
    FROZEN.parent.mkdir(parents=True, exist_ok=True)
    FROZEN.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(FROZEN.read_bytes()).hexdigest()
    print(json.dumps({"frozen": str(FROZEN), "sha256": digest, "tasks": len(frozen["tasks"]),
                      "official_runs_present": OFFICIAL_RUNS.exists()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
