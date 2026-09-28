"""Read-only integrity audit of preserved AX v4 official attempts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from scripts.session_prompt_validation import validate_submitted_prompt
from scripts.v4_evaluation import evaluate_response
from scripts.v4_official_runner import ARTIFACT_ROOT, ROOT, _agent_config, _events, _load_frozen
from scripts.v4_prompt import construct_runtime_prompt


RETRY_ROOT = ROOT / "artifacts" / "heldout_ax-exp-v4-retries"
OUTPUT = ARTIFACT_ROOT / "PARTIAL_AUDIT.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    manifest = _load_frozen()
    tasks = {task["task_id"]: task for task in manifest["tasks"]}
    order = {(task["task_id"], repetition): index
             for index, (repetition, task) in enumerate(
                 (pair for rep in (1, 2) for pair in ((rep, task) for task in manifest["tasks"]))) }
    paths = [path.parent for root in (ARTIFACT_ROOT, RETRY_ROOT)
             for path in root.rglob("metadata.json")
             if path.parent.name in ("r1", "r2")]
    rows = []
    errors = []
    for path in paths:
        label = path.relative_to(ROOT).as_posix()
        issues = []
        metadata = read(path / "metadata.json")
        task_id = metadata.get("task_id")
        repetition = metadata.get("repetition")
        task = tasks.get(task_id)
        if task is None or (task_id, repetition) not in order:
            issues.append("unknown registered slot")
        if path.parts[-2:] != (task_id, f"r{repetition}"):
            issues.append("path and slot disagree")
        if metadata.get("manifest_sha256") != sha(ROOT / "experiment/frozen/ax-exp-v4-manifest.json"):
            issues.append("manifest hash mismatch")
        if metadata.get("run_status") != "RECORDED" or metadata.get("execution_backend") != manifest["backend"]:
            issues.append("run status or backend mismatch")
        if task is not None and (path / "prompt.txt").read_bytes() != construct_runtime_prompt(task).encode("utf-8"):
            issues.append("prepared prompt differs from frozen task projection")
        for name, field in (("prompt.txt", "prompt_sha256"),
                            ("raw_response.txt", "raw_response_sha256"),
                            ("runtime-identity-receipt.json", "runtime_receipt_sha256"),
                            ("mcp-invocations-live.jsonl", "mcp_invocation_log_sha256")):
            file = path / name
            if not file.is_file() or sha(file) != metadata.get(field):
                issues.append(f"{name} hash mismatch")
        agent_config = ROOT / metadata["agent_config"]
        if not agent_config.is_file() or sha(agent_config) != metadata.get("agent_config_sha256"):
            issues.append("agent config hash mismatch")
        elif read(agent_config) != _agent_config(path, manifest, metadata["agent_name"]):
            issues.append("agent config differs from frozen construction")
        for field, hash_field in (("session_file", "session_file_sha256"),
                                  ("session_events_file", "session_events_file_sha256")):
            file = Path(metadata[field])
            if not file.is_file() or sha(file) != metadata.get(hash_field):
                issues.append(f"{field} hash mismatch")
        if metadata.get("process_exit_code") != 0 or not metadata.get("process_terminated"):
            issues.append("process did not exit cleanly")
        if metadata.get("fresh_process") is not True or metadata.get("resume_used") is not False:
            issues.append("fresh process claim failed")
        runtime_receipt = read(path / "runtime-identity-receipt.json")
        if runtime_receipt.get("passed") is not True or runtime_receipt.get("identity") != metadata.get("runtime_identity"):
            issues.append("runtime identity receipt differs")
        session = read(Path(metadata["session_file"]))
        if session.get("session_state", {}).get("rts_model_state", {}).get("model_info", {}).get("model_id") != manifest["model"]:
            issues.append("session model differs from frozen model")
        invocation_count = len([line for line in (path / "mcp-invocations-live.jsonl").read_bytes().splitlines()
                                if line.strip()])
        if invocation_count != metadata.get("mcp_invocation_count"):
            issues.append("MCP invocation count mismatch")
        prompt_receipt = validate_submitted_prompt(path, metadata["session_id"], metadata["agent_name"])
        responses = prompt_receipt.pop("assistant_responses")
        if prompt_receipt != read(path / "submitted-prompt-validation.json"):
            issues.append("prompt validation receipt differs")
        if not prompt_receipt["passed"] or len(responses) != 1:
            issues.append("prompt or response verification failed")
        raw = (path / "raw_response.txt").read_text(encoding="utf-8")
        if responses and responses[-1] != raw:
            issues.append("session final response differs from saved raw")
        finished = [event["data"] for event in _events((path / "stream.jsonl").read_bytes())
                    if event.get("type") == "runFinished"]
        if len(finished) != 1 or finished[0].get("status") != "success":
            issues.append("stream completion failed")
            stream_text = None
        else:
            stream_text = finished[0].get("finalText")
        if task is not None:
            evaluation = evaluate_response(task, raw)
            if evaluation.receipt() != read(path / "evaluation.json"):
                issues.append("evaluation receipt differs from frozen rules")
            for field in ("native_strict", "delivered_valid", "outcome", "primary_success"):
                if metadata.get(field) != getattr(evaluation, field):
                    issues.append(f"metadata {field} differs from frozen evaluation")
            delivered_path = path / "delivered.json"
            if evaluation.delivered_json is None:
                if delivered_path.exists():
                    issues.append("unexpected delivered JSON")
            elif not delivered_path.is_file() or delivered_path.read_bytes() != evaluation.delivered_json.encode("utf-8"):
                issues.append("delivered JSON differs")
        validity = metadata.get("validity_status")
        if validity == "VALID":
            if metadata.get("validation_errors") or stream_text != raw:
                issues.append("validity receipt differs")
        elif validity == "INVALID":
            if metadata.get("validation_errors") != ["INVALID_STREAM_SESSION_RESPONSE_MISMATCH"]:
                issues.append("unexplained invalidity")
            if not isinstance(stream_text, str) or not stream_text.endswith(raw) or stream_text == raw:
                issues.append("stream aggregation explanation failed")
        else:
            issues.append("missing final validity")
        rows.append({"path": label, "task_id": task_id, "repetition": repetition,
                     "start_timestamp": metadata.get("start_timestamp"),
                     "end_timestamp": metadata.get("end_timestamp"),
                     "session_id": metadata.get("session_id"),
                     "process_id": metadata.get("process_id"),
                     "stream_sha256": sha(path / "stream.jsonl"),
                     "validity_status": validity,
                     "validation_errors": metadata.get("validation_errors"),
                     "integrity_issues": issues})
        errors.extend(f"{label}: {issue}" for issue in issues)
    rows.sort(key=lambda row: row["start_timestamp"])
    slot_positions = [order[(row["task_id"], row["repetition"])] for row in rows]
    if slot_positions != sorted(slot_positions):
        errors.append("attempt order deviates from registered order")
    sessions = [row["session_id"] for row in rows]
    if len(sessions) != len(set(sessions)):
        errors.append("duplicate session id")
    processes = [row["process_id"] for row in rows]
    if len(processes) != len(set(processes)):
        errors.append("duplicate process id")
    counts = Counter((row["task_id"], row["repetition"]) for row in rows
                     if row["validity_status"] == "VALID")
    if any(count > 1 for count in counts.values()):
        errors.append("duplicate valid slot")
    expected = len(manifest["tasks"]) * manifest["repetitions"]
    result = {
        "schema_version": "ax-v4-partial-audit-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": sha(ROOT / "experiment/frozen/ax-exp-v4-manifest.json"),
        "integrity_passed": not errors,
        "official_complete": len(counts) == expected and not errors,
        "expected_valid_slots": expected,
        "valid_slots": len(counts),
        "attempted_slots": len({(row["task_id"], row["repetition"]) for row in rows}),
        "attempts": len(rows),
        "invalid_attempts": sum(row["validity_status"] == "INVALID" for row in rows),
        "errors": errors,
        "attempt_rows": rows,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("integrity_passed", "official_complete",
                                                  "valid_slots", "expected_valid_slots",
                                                  "attempted_slots", "attempts", "invalid_attempts", "errors")},
                     ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
