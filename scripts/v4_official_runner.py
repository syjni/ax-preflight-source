"""Prospective v4 automated runner; refuses to execute without a frozen manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity
from scripts.session_prompt_validation import validate_submitted_prompt
from scripts.v4_evaluation import evaluate_response
from scripts.v4_preflight import ROOT, validate_manifest
from scripts.v4_prompt import construct_runtime_prompt


V4 = ROOT / "experiment" / "v4"
FROZEN_MANIFEST = ROOT / "experiment" / "frozen" / "ax-exp-v4-manifest.json"
ARTIFACT_ROOT = ROOT / "artifacts" / "heldout_ax-exp-v4"
SESSIONS_ROOT = Path.home() / ".kiro" / "sessions" / "cli"
TOOLS = [
    "@ax-tools/search_documents", "@ax-tools/read_document",
    "@ax-tools/lookup_value", "@ax-tools/query_table",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _session_ids() -> set[str]:
    return {path.stem for path in SESSIONS_ROOT.glob("*.json")}


def _new_agent_sessions(before: set[str], expected_agent: str) -> set[str]:
    matches = set()
    for session_id in _session_ids() - before:
        path = SESSIONS_ROOT / f"{session_id}.json"
        try:
            session = _json(path)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if session.get("session_state", {}).get("agent_name") == expected_agent:
            matches.add(session_id)
    return matches


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_frozen() -> dict[str, Any]:
    manifest = _json(FROZEN_MANIFEST)
    if manifest.get("status") != "FROZEN":
        raise ValueError("official runner requires a FROZEN v4 manifest")
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError(f"v4 frozen preflight failed: {errors}")
    return manifest


def _agent_config(run_dir: Path, manifest: dict[str, Any], name: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Read-only AX v4 company-evidence evaluation agent.",
        "model": manifest["model"],
        "prompt": (V4 / "AGENT_PROMPT.txt").read_text(encoding="utf-8"),
        "mcpServers": {
            "ax-tools": {
                "command": str(Path(sys.executable).resolve()),
                "args": [
                    "-m", "ax_mcp.server",
                    "--invocation-log", str(run_dir / "mcp-invocations-live.jsonl"),
                    "--runtime-identity-output", str(run_dir / "runtime-identity-receipt.json"),
                ],
                "env": {
                    "AX_RUNTIME_DATASET": manifest["runtime_profile"],
                    "AX_RUNTIME_DATASET_CONFIG": str(V4 / "runtime_datasets.json"),
                    "PYTHONPATH": str(ROOT),
                    "PYTHONIOENCODING": "utf-8",
                },
                "timeout": 10000,
            },
        },
        "tools": TOOLS,
        "allowedTools": TOOLS,
        "resources": [],
        "includeMcpJson": False,
    }


def _prepare(
    task: dict[str, Any], repetition: int, manifest: dict[str, Any], *,
    artifact_root: Path = ARTIFACT_ROOT, manifest_path: Path = FROZEN_MANIFEST,
) -> tuple[Path, Path, str, dict[str, Any]]:
    if repetition not in (1, 2):
        raise ValueError("registered repetitions are 1 and 2")
    run_dir = artifact_root / task["task_id"] / f"r{repetition}"
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite v4 run: {run_dir}")
    run_dir.mkdir(parents=True)
    prompt = construct_runtime_prompt(task)
    (run_dir / "prompt.txt").write_bytes(prompt.encode("utf-8"))
    suffix = hashlib.sha256(str(run_dir).encode("utf-8")).hexdigest()[:12]
    name = f"ax-v4-{suffix}"
    config_path = ROOT / ".kiro" / "agents" / f"{name}.json"
    if config_path.exists():
        raise FileExistsError(f"run agent already exists: {config_path}")
    _write(config_path, _agent_config(run_dir, manifest, name))
    dataset = resolve_runtime_dataset(manifest["runtime_profile"], V4 / "runtime_datasets.json")
    identity = runtime_identity(dataset)
    metadata = {
        "schema_version": "ax-interactive-run-v4",
        "experiment_version": "ax-exp-v4",
        "execution_backend": "AUTOMATED_FRESH_PROCESS_V2",
        "run_status": "PREPARED",
        "validity_status": "PENDING",
        "task_id": task["task_id"],
        "repetition": repetition,
        "start_timestamp": _timestamp(),
        "manifest_sha256": _sha(manifest_path),
        "prompt_sha256": _sha(run_dir / "prompt.txt"),
        "agent_name": name,
        "agent_config": config_path.relative_to(ROOT).as_posix(),
        "agent_config_sha256": _sha(config_path),
        "runtime_identity": identity,
        "runtime_profile": identity["dataset_profile"],
        "process_id": None,
        "session_id": None,
    }
    _write(run_dir / "metadata.json", metadata)
    return run_dir, config_path, prompt, metadata


def _events(stdout: bytes) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
    return events


def run_one(
    task: dict[str, Any], repetition: int, manifest: dict[str, Any], *,
    artifact_root: Path = ARTIFACT_ROOT, manifest_path: Path = FROZEN_MANIFEST,
) -> dict[str, Any]:
    binary = shutil.which("kiro-cli")
    if binary is None:
        raise FileNotFoundError("kiro-cli")
    version = subprocess.run([binary, "--version"], cwd=ROOT, capture_output=True,
                             text=True, check=False)
    if version.returncode != 0 or version.stdout.strip() != manifest["kiro_cli_version"]:
        raise RuntimeError("Kiro CLI version changed after v4 freeze")
    run_dir, config_path, prompt, metadata = _prepare(
        task, repetition, manifest, artifact_root=artifact_root, manifest_path=manifest_path)
    command = [binary, "chat", "--no-interactive", "--output-format", "stream-json",
               "--agent-engine", "v2", "--agent", metadata["agent_name"],
               "--require-mcp-startup", prompt]
    _write(run_dir / "command.json", command)
    before_sessions = _session_ids()
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, shell=False)
    try:
        stdout, stderr = process.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        metadata["timeout"] = True
    (run_dir / "stream.jsonl").write_bytes(stdout)
    (run_dir / "kiro-stderr.txt").write_bytes(stderr)
    metadata.update({"process_id": process.pid, "process_exit_code": process.returncode,
                     "process_terminated": process.poll() is not None,
                     "fresh_process": True, "resume_used": False})
    errors: list[str] = []
    started = [event for event in _events(stdout) if event.get("type") == "runStarted"]
    if len(started) != 1 or started[0].get("data", {}).get("engine") != "v2":
        errors.append("INVALID_KIRO_ENGINE")
    completed = [event["data"] for event in _events(stdout) if event.get("type") == "runFinished"]
    if len(completed) != 1:
        errors.append("INVALID_RUN_FINISHED_EVENT")
    else:
        final = completed[0]
        session_id = final.get("sessionId")
        metadata["session_id"] = session_id
        if final.get("status") != "success" or final.get("finalTextTruncated") is not False:
            errors.append("INVALID_TURN_COMPLETION")
        if (not isinstance(session_id, str) or session_id in before_sessions
                or _new_agent_sessions(before_sessions, metadata["agent_name"]) != {session_id}):
            errors.append("INVALID_FRESH_SESSION")
        else:
            receipt = validate_submitted_prompt(run_dir, session_id, metadata["agent_name"])
            responses = receipt.pop("assistant_responses")
            _write(run_dir / "submitted-prompt-validation.json", receipt)
            errors.extend(receipt["validation_errors"])
            if receipt["passed"] is not True:
                errors.append("INVALID_PROMPT_RECEIPT")
            if not responses:
                errors.append("INVALID_EMPTY_ASSISTANT_RESPONSE")
            else:
                raw = responses[-1]
                (run_dir / "raw_response.txt").write_bytes(raw.encode("utf-8"))
                if final.get("finalText") != raw:
                    errors.append("INVALID_STREAM_SESSION_RESPONSE_MISMATCH")
                evaluation = evaluate_response(task, raw)
                _write(run_dir / "evaluation.json", evaluation.receipt())
                if evaluation.delivered_json is not None:
                    (run_dir / "delivered.json").write_bytes(evaluation.delivered_json.encode("utf-8"))
                metadata.update({"native_strict": evaluation.native_strict,
                                 "delivered_valid": evaluation.delivered_valid,
                                 "outcome": evaluation.outcome,
                                 "primary_success": evaluation.primary_success})
                metadata["raw_response_sha256"] = _sha(run_dir / "raw_response.txt")
            metadata.update({
                "session_file": receipt["session_file"],
                "session_file_sha256": _sha(Path(receipt["session_file"])),
                "session_events_file": receipt["session_events_file"],
                "session_events_file_sha256": _sha(Path(receipt["session_events_file"])),
                "submitted_prompt_matches_prepared": receipt["submitted_prompt_matches_prepared"],
                "user_turn_count": receipt["user_turn_count"],
                "prompt_event_count": receipt["prompt_event_count"],
            })
    receipt_path = run_dir / "runtime-identity-receipt.json"
    if not receipt_path.is_file():
        errors.append("INVALID_RUNTIME_RECEIPT_MISSING")
    else:
        runtime_receipt = _json(receipt_path)
        if runtime_receipt.get("passed") is not True or runtime_receipt.get("identity") != metadata["runtime_identity"]:
            errors.append("INVALID_RUNTIME_IDENTITY")
        metadata["runtime_receipt_sha256"] = _sha(receipt_path)
    if process.returncode != 0 or not metadata["process_terminated"]:
        errors.append("INVALID_PROCESS_EXIT")
    invocation_path = run_dir / "mcp-invocations-live.jsonl"
    if not invocation_path.is_file():
        errors.append("INVALID_MCP_INVOCATION_LOG_MISSING")
    else:
        metadata["mcp_invocation_log_sha256"] = _sha(invocation_path)
        metadata["mcp_invocation_count"] = len([line for line in invocation_path.read_bytes().splitlines() if line.strip()])
    if metadata.get("timeout"):
        errors.append("INVALID_PROCESS_TIMEOUT")
    if _sha(run_dir / "prompt.txt") != metadata["prompt_sha256"]:
        errors.append("INVALID_PREPARED_PROMPT_CHANGED")
    if _sha(config_path) != metadata["agent_config_sha256"]:
        errors.append("INVALID_AGENT_CONFIG_CHANGED")
    if _sha(manifest_path) != metadata["manifest_sha256"]:
        errors.append("INVALID_MANIFEST_CHANGED")
    dataset_after = resolve_runtime_dataset(manifest["runtime_profile"], V4 / "runtime_datasets.json")
    if runtime_identity(dataset_after) != metadata["runtime_identity"]:
        errors.append("INVALID_RUNTIME_CHANGED")
    metadata.update({
        "run_status": "RECORDED",
        "validity_status": "VALID" if not errors else "INVALID",
        "validation_errors": errors,
        "end_timestamp": _timestamp(),
    })
    _write(run_dir / "metadata.json", metadata)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    one = sub.add_parser("run-one")
    one.add_argument("--task-id", required=True)
    one.add_argument("--repetition", type=int, choices=(1, 2), required=True)
    one.add_argument("--execute", action="store_true")
    all_runs = sub.add_parser("run-all")
    all_runs.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("official execution requires --execute")
    manifest = _load_frozen()
    tasks = manifest["tasks"]
    selected = ([next(task for task in tasks if task["task_id"] == args.task_id)]
                if args.action == "run-one" else tasks)
    repetitions = [args.repetition] if args.action == "run-one" else (1, 2)
    for repetition in repetitions:
        for task in selected:
            result = run_one(task, repetition, manifest)
            print(json.dumps({key: result.get(key) for key in
                              ("task_id", "repetition", "validity_status", "outcome",
                               "native_strict", "delivered_valid", "primary_success")},
                             ensure_ascii=False), flush=True)
            if result["validity_status"] != "VALID":
                raise SystemExit("stopped after invalid v4 run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
