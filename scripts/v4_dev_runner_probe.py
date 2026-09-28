"""Exercise the v4 runner path once on development-only evidence."""

from __future__ import annotations

import argparse
import json

from scripts.v4_dev_kiro_probe import DEV_TASK, ROOT, V4
from scripts.v4_official_runner import run_one


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("refusing to contact Kiro without --execute")
    manifest_path = V4 / "DEV_RUNNER_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = run_one(
        DEV_TASK, 1, manifest,
        artifact_root=ROOT / "artifacts" / "v4_development" / "runner_probe",
        manifest_path=manifest_path,
    )
    summary = {key: result.get(key) for key in (
        "task_id", "repetition", "validity_status", "validation_errors",
        "native_strict", "delivered_valid", "outcome", "primary_success",
    )}
    summary["development_only"] = True
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["validity_status"] == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
