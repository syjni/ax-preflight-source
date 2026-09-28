"""Freeze v5 only after independent truth, access, stream, and runner checks."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone

from scripts.build_v5_candidate import ROOT, V5
from scripts.v5_preflight import validate_manifest
from scripts.validate_v5_development import validate as validate_development
from scripts.validate_v5_tool_access import validate as validate_access
from scripts.verify_v5_candidate_truth import verify as verify_truth


CANDIDATE = V5 / "CANDIDATE_MANIFEST.json"
FROZEN = ROOT / "experiment" / "frozen" / "ax-exp-v5-manifest.json"
OFFICIAL = ROOT / "artifacts" / "heldout_ax-exp-v5"


def main() -> int:
    if FROZEN.exists():
        raise FileExistsError(f"v5 is already frozen: {FROZEN}")
    if OFFICIAL.exists():
        raise ValueError("official v5 artifacts exist before freeze")
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    if candidate.get("status") != "DRAFT":
        raise ValueError("v5 freeze requires a DRAFT candidate")
    errors = validate_manifest(candidate, require_ready=False)
    errors.extend(verify_truth())
    errors.extend(validate_access()["errors"])
    errors.extend(validate_development()["errors"])
    tests = subprocess.run([sys.executable, "-m", "unittest", "-q",
                            "tests.test_stream_response_validation", "tests.test_v5_preflight",
                            "tests.test_v4_development",
                            "tests.test_output_contract"], cwd=ROOT, capture_output=True, text=True,
                           check=False)
    if tests.returncode != 0:
        errors.append("development tests failed: " + tests.stdout + tests.stderr)
    if errors:
        raise ValueError(f"v5 freeze preflight failed: {errors}")
    frozen = copy.deepcopy(candidate)
    frozen["status"] = "FROZEN"
    frozen["freeze_timestamp_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    frozen["candidate_manifest_sha256"] = hashlib.sha256(CANDIDATE.read_bytes()).hexdigest()
    errors = validate_manifest(frozen)
    if errors:
        raise ValueError(f"v5 frozen manifest failed ready preflight: {errors}")
    FROZEN.parent.mkdir(parents=True, exist_ok=True)
    FROZEN.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(FROZEN.read_bytes()).hexdigest()
    print(json.dumps({"frozen": str(FROZEN), "sha256": digest,
                      "tasks": len(frozen["tasks"]), "official_runs_present": OFFICIAL.exists()},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
