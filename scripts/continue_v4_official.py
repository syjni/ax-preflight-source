"""Resume the frozen v4 runner after preserved invalid attempts.

This post-freeze operator only chooses the next registered slot. It delegates
each new run to the frozen runner and stops at the first invalid attempt.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.v4_official_runner import ARTIFACT_ROOT, ROOT, _events, _load_frozen, run_one


RETRY_ROOT = ROOT / "artifacts" / "heldout_ax-exp-v4-retries"
MAX_ATTEMPTS_PER_SLOT = 10


def _attempts(task_id: str, repetition: int) -> list[Path]:
    suffix = Path(task_id) / f"r{repetition}"
    paths = [ARTIFACT_ROOT / suffix]
    paths.extend(sorted(RETRY_ROOT.glob(f"attempt-*/{suffix.as_posix()}")))
    return [path for path in paths if path.is_dir()]


def _known_stream_aggregation(path: Path, receipt: dict) -> bool:
    """Identify the Kiro 2.23.0 stream aggregate seen in the first stopped slot."""
    if receipt.get("validation_errors") != ["INVALID_STREAM_SESSION_RESPONSE_MISMATCH"]:
        return False
    prompt_receipt = json.loads((path / "submitted-prompt-validation.json").read_text(encoding="utf-8"))
    if prompt_receipt.get("passed") is not True:
        return False
    events = _events((path / "stream.jsonl").read_bytes())
    finished = [event["data"] for event in events if event.get("type") == "runFinished"]
    if len(finished) != 1:
        return False
    stream_text = finished[0].get("finalText")
    raw = (path / "raw_response.txt").read_text(encoding="utf-8")
    return isinstance(stream_text, str) and len(stream_text) > len(raw) and stream_text.endswith(raw)


def main() -> int:
    manifest = _load_frozen()
    completed = 0
    for repetition in (1, 2):
        for task in manifest["tasks"]:
            task_id = task["task_id"]
            attempts = _attempts(task_id, repetition)
            receipts = [json.loads((path / "metadata.json").read_text(encoding="utf-8"))
                        for path in attempts]
            valid = [receipt for receipt in receipts if receipt.get("validity_status") == "VALID"]
            if len(valid) > 1:
                raise RuntimeError(f"duplicate valid attempts: {task_id} r{repetition}")
            if valid:
                completed += 1
                print(json.dumps({"completed": completed, "task_id": task_id,
                                  "repetition": repetition, "status": "previously VALID"}), flush=True)
                continue
            while True:
                if attempts:
                    last = receipts[-1]
                    if not _known_stream_aggregation(attempts[-1], last):
                        raise RuntimeError(f"uninvestigated invalid slot: {task_id} r{repetition}")
                    if len(attempts) >= MAX_ATTEMPTS_PER_SLOT:
                        raise RuntimeError(f"repeated stream mismatch needs investigation: {task_id} r{repetition}")
                    artifact_root = RETRY_ROOT / f"attempt-{len(attempts) + 1:02d}"
                else:
                    artifact_root = ARTIFACT_ROOT
                receipt = run_one(task, repetition, manifest, artifact_root=artifact_root)
                attempts = _attempts(task_id, repetition)
                receipts.append(receipt)
                if receipt["validity_status"] == "VALID":
                    break
                print(json.dumps({"completed": completed, "task_id": task_id,
                                  "repetition": repetition, "attempts": len(attempts),
                                  "status": "INVALID", "errors": receipt["validation_errors"]},
                                 ensure_ascii=False), flush=True)
            completed += 1
            print(json.dumps({"completed": completed, "task_id": task_id,
                              "repetition": repetition, "attempts": len(attempts), "status": "VALID",
                              "outcome": receipt["outcome"],
                              "native_strict": receipt["native_strict"],
                              "delivered_valid": receipt["delivered_valid"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
