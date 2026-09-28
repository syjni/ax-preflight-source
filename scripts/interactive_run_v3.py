"""ax-exp-v3 recorder with exact submitted-prompt validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from . import interactive_run as v2
from .session_prompt_validation import validate_submitted_prompt


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_VERSION = "ax-exp-v3"
EXECUTION_BACKEND = "SEMI_AUTOMATED_FRESH_PROCESS"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_run_v3(
    run_dir: Path,
    *,
    task_id: str,
    condition: str,
    repetition: int,
    prompt: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    metadata = v2.prepare_run(
        run_dir,
        task_id=task_id,
        condition=condition,
        repetition=repetition,
        prompt=prompt,
        root=root,
    )
    metadata.update({
        "schema_version": "ax-interactive-run-v3",
        "experiment_version": EXPERIMENT_VERSION,
        "execution_backend": EXECUTION_BACKEND,
        "prepared_prompt_sha256": metadata["prompt_sha256"],
        "submitted_prompt_sha256": None,
        "submitted_prompt_matches_prepared": None,
        "user_turn_count": None,
        "prompt_event_count": None,
        "prompt_validation_errors": [],
        "process_id": None,
        "process_exit_code": None,
        "process_terminated": None,
    })
    command = f'"{Path(sys.executable).resolve()}" -m scripts.semi_auto_runner_v3 run-one --run-dir "{run_dir.resolve()}" --execute'
    (run_dir / "command.txt").write_text(command + "\n", encoding="utf-8")
    _write(run_dir / "metadata.json", metadata)
    return metadata


def capture_kiro_session_v3(
    run_dir: Path,
    session_id: str,
    *,
    sessions_root: Path | None = None,
) -> dict[str, Any]:
    metadata_path = run_dir / "metadata.json"
    metadata = _read(metadata_path)
    if metadata.get("run_status") != "PREPARED":
        raise ValueError("session capture requires a PREPARED v3 run")
    validation = validate_submitted_prompt(
        run_dir,
        session_id,
        metadata["kiro_agent_name"],
        sessions_root=sessions_root,
    )
    responses = validation.pop("assistant_responses")
    if responses:
        (run_dir / "raw_response.txt").write_bytes(responses[-1].encode("utf-8"))
    receipt_path = run_dir / "submitted-prompt-validation.json"
    _write(receipt_path, validation)
    metadata.update({
        "kiro_session_id": session_id,
        "kiro_session_file": validation["session_file"],
        "kiro_session_events_file": validation["session_events_file"],
        "kiro_session_file_sha256": _sha(Path(validation["session_file"])),
        "kiro_session_events_file_sha256": _sha(Path(validation["session_events_file"])),
        "prepared_prompt_sha256": validation["prepared_prompt_sha256"],
        "submitted_prompt_sha256": validation["submitted_prompt_sha256"],
        "submitted_prompt_matches_prepared": validation["submitted_prompt_matches_prepared"],
        "user_turn_count": validation["user_turn_count"],
        "prompt_event_count": validation["prompt_event_count"],
        "prompt_validation_receipt_file": receipt_path.name,
        "prompt_validation_receipt_sha256": _sha(receipt_path),
        "prompt_validation_errors": validation["validation_errors"],
    })
    if validation["validation_errors"]:
        metadata["validity_status"] = "INVALID"
        metadata["invalid_reason"] = validation["validation_errors"][0]
    _write(metadata_path, metadata)
    return metadata


def finalize_run_v3(run_dir: Path, *, root: Path = ROOT) -> dict[str, Any]:
    before = _read(run_dir / "metadata.json")
    if not before.get("kiro_session_id"):
        raise ValueError("v3 finalization requires explicit session capture")
    if not (run_dir / "raw_response.txt").is_file():
        raise FileNotFoundError("captured session contains no assistant response")
    metadata = v2.finalize_run(run_dir, root=root)
    prompt_errors = list(before.get("prompt_validation_errors", []))
    combined = list(dict.fromkeys([*metadata.get("validation_errors", []), *prompt_errors]))
    prompt_valid = (
        before.get("submitted_prompt_matches_prepared") is True
        and before.get("user_turn_count") == 1
        and before.get("prompt_event_count") == 1
        and not prompt_errors
    )
    metadata.update({
        "schema_version": "ax-interactive-run-v3",
        "experiment_version": EXPERIMENT_VERSION,
        "execution_backend": EXECUTION_BACKEND,
        "prepared_prompt_sha256": before.get("prepared_prompt_sha256"),
        "submitted_prompt_sha256": before.get("submitted_prompt_sha256"),
        "submitted_prompt_matches_prepared": before.get("submitted_prompt_matches_prepared"),
        "user_turn_count": before.get("user_turn_count"),
        "prompt_event_count": before.get("prompt_event_count"),
        "prompt_validation_receipt_file": before.get("prompt_validation_receipt_file"),
        "prompt_validation_receipt_sha256": before.get("prompt_validation_receipt_sha256"),
        "prompt_validation_errors": prompt_errors,
        "validation_errors": combined,
        "process_id": before.get("process_id"),
        "process_exit_code": before.get("process_exit_code"),
        "process_terminated": before.get("process_terminated"),
        "fresh_process": before.get("fresh_process"),
        "resume_used": before.get("resume_used"),
    })
    if not prompt_valid or combined:
        metadata["validity_status"] = "INVALID"
        metadata["invalid_reason"] = (prompt_errors or combined or ["INVALID_PROMPT_VALIDATION"])[0]
    elif not (
        metadata.get("process_id")
        and metadata.get("process_terminated") is True
        and metadata.get("fresh_process") is True
        and metadata.get("resume_used") is False
    ):
        metadata["validity_status"] = "INVALID"
        metadata["invalid_reason"] = "INVALID_AUTOMATION_PROCESS_EVIDENCE"
        metadata["validation_errors"] = [*combined, "INVALID_AUTOMATION_PROCESS_EVIDENCE"]
    else:
        metadata["validity_status"] = "VALID"
        metadata["invalid_reason"] = None
    _write(run_dir / "metadata.json", metadata)
    return metadata


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--run-dir", type=Path, required=True)
    prepare.add_argument("--task-id", required=True)
    prepare.add_argument("--condition", required=True)
    prepare.add_argument("--repetition", type=int, required=True)
    prepare.add_argument("--prompt-file", type=Path, required=True)
    capture = sub.add_parser("capture-session")
    capture.add_argument("--run-dir", type=Path, required=True)
    capture.add_argument("--session-id", required=True)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--run-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.action == "prepare":
        result = prepare_run_v3(
            args.run_dir,
            task_id=args.task_id,
            condition=args.condition,
            repetition=args.repetition,
            prompt=args.prompt_file.read_text(encoding="utf-8"),
        )
    elif args.action == "capture-session":
        result = capture_kiro_session_v3(args.run_dir, args.session_id)
    else:
        result = finalize_run_v3(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
