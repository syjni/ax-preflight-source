"""Preserve the known pre-v3 wrong-prompt session as excluded evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from scripts.interactive_run_v3 import ROOT
from scripts.session_prompt_validation import validate_submitted_prompt


SESSION_ID = "35613a28-a498-4707-b72a-c58e67697a58"
RUN_DIR = Path("artifacts/heldout_ax-exp-v2/K01_RETURN_WINDOW/Before/r1")
OUTPUT = Path("experiment/v3/operator-errors/35613a28-a498-4707-b72a-c58e67697a58.json")
EVIDENCE_DIR = Path("experiment/v3/operator-errors/evidence/35613a28-a498-4707-b72a-c58e67697a58")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_receipt(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    run_dir = root / RUN_DIR
    metadata = _read(run_dir / "metadata.json")
    validation = validate_submitted_prompt(run_dir, SESSION_ID, metadata["kiro_agent_name"])
    validation.pop("assistant_responses")
    if "INVALID_OPERATOR_WRONG_PROMPT" not in validation["validation_errors"]:
        raise ValueError("known operator-error session did not reproduce wrong-prompt classification")
    evidence_dir = root / EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)
    preserved_session = evidence_dir / f"{SESSION_ID}.json"
    preserved_events = evidence_dir / f"{SESSION_ID}.jsonl"
    shutil.copyfile(validation["session_file"], preserved_session)
    shutil.copyfile(validation["session_events_file"], preserved_events)
    receipt = {
        "schema_version": "ax-v3-operator-error-audit-v1",
        "experiment_version": "ax-exp-v3",
        "source_experiment_version": "ax-exp-v2",
        "session_id": SESSION_ID,
        "classification": "INVALID_OPERATOR_WRONG_PROMPT",
        "official_denominator_included": False,
        "held_out_task_prompt_submitted": False,
        "prepared_artifact_path": RUN_DIR.as_posix(),
        "prepared_artifact_metadata_sha256": _sha(run_dir / "metadata.json"),
        "prepared_prompt_sha256": validation["prepared_prompt_sha256"],
        "submitted_prompt_sha256": validation["submitted_prompt_sha256"],
        "submitted_prompt_matches_prepared": validation["submitted_prompt_matches_prepared"],
        "user_turn_count": validation["user_turn_count"],
        "session_file": validation["session_file"],
        "session_file_sha256": _sha(Path(validation["session_file"])),
        "session_events_file": validation["session_events_file"],
        "session_events_file_sha256": _sha(Path(validation["session_events_file"])),
        "preserved_session_file": preserved_session.relative_to(root).as_posix(),
        "preserved_session_file_sha256": _sha(preserved_session),
        "preserved_session_events_file": preserved_events.relative_to(root).as_posix(),
        "preserved_session_events_file_sha256": _sha(preserved_events),
        "validation_errors": validation["validation_errors"],
        "preservation_policy": "Source v2 prepared artifact and Kiro session are retained unmodified.",
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = create_receipt(args.root)
    output = args.root.resolve() / OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
