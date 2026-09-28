"""Prepare and finalize reproducible human-driven Kiro interactive runs.

This module never starts or automates Kiro. A human launches the recorded
command, submits the exact prompt once, preserves the raw response, exits the
process, and then finalizes the run artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity

from .output_contract import parse_agent_response
from .runtime_binding import RuntimeBindingError, resolve_runtime_binding


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_VERSION = "ax-exp-v2"
AGENT_CONFIG = Path(".kiro/agents/ax-evaluation.json")
PROMPT_METADATA = Path(".kiro/ax-evaluation.prompt-metadata.json")
RUNTIME_CONFIG = Path("runtime_datasets.json")
EXPECTED_MODEL = "claude-sonnet-5"
EXPECTED_PROMPT_HASH = "dc783a41a5b06eb871ada33be7dd21aec2e4106757a40921ddf59fcf81176fc8"
EXPECTED_TOOLS = (
    "@ax-tools/search_documents",
    "@ax-tools/read_document",
    "@ax-tools/lookup_value",
    "@ax-tools/query_table",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes().decode("utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _git_commit(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _kiro_cli_version() -> str:
    completed = subprocess.run(
        ["kiro-cli", "--version"], capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("unable to record the Kiro CLI version")
    return completed.stdout.strip()


def _runtime_record(root: Path, config: dict[str, Any]) -> tuple[dict[str, Any], str]:
    server = config["mcpServers"]["ax-tools"]
    environment = server["env"]
    dataset = resolve_runtime_dataset(
        environment["AX_RUNTIME_DATASET"], environment["AX_RUNTIME_DATASET_CONFIG"],
    )
    identity = runtime_identity(dataset)
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return identity, _sha256_bytes(canonical)


def _validate_agent_invariants(config: dict[str, Any], prompt_metadata: dict[str, Any]) -> None:
    prompt_hash = _sha256_bytes(config.get("prompt", "").encode("utf-8"))
    if config.get("model") != EXPECTED_MODEL:
        raise ValueError(f"evaluation model must be {EXPECTED_MODEL}")
    if prompt_hash != EXPECTED_PROMPT_HASH or prompt_metadata.get("prompt_sha256") != EXPECTED_PROMPT_HASH:
        raise ValueError("frozen prompt v2 hash mismatch")
    if tuple(config.get("tools", [])) != EXPECTED_TOOLS:
        raise ValueError("agent tool surface is not exactly the frozen four tools")
    if tuple(config.get("allowedTools", [])) != EXPECTED_TOOLS:
        raise ValueError("agent allowed-tool surface is not exactly the frozen four tools")


def _agent_name(run_dir: Path) -> str:
    suffix = hashlib.sha256(str(run_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"ax-evaluation-{suffix}"


def _build_run_config(
    root: Path,
    run_dir: Path,
    base: dict[str, Any],
    runtime_profile: str,
) -> tuple[Path, dict[str, Any]]:
    config = json.loads(json.dumps(base))
    name = _agent_name(run_dir)
    config["name"] = name
    server = config["mcpServers"]["ax-tools"]
    server["env"]["AX_RUNTIME_DATASET"] = runtime_profile
    server["env"]["AX_RUNTIME_DATASET_CONFIG"] = str((root / RUNTIME_CONFIG).resolve())
    server["args"] = [
        "-m", "ax_mcp.server",
        "--invocation-log", str((run_dir / "mcp-invocations-live.jsonl").resolve()),
        "--runtime-identity-output", str((run_dir / "runtime-identity-receipt.json").resolve()),
    ]
    path = root / ".kiro" / "agents" / f"{name}.json"
    return path, config


def _consistency_errors(metadata: dict[str, Any], root: Path) -> list[str]:
    errors: list[str] = []
    try:
        binding = resolve_runtime_binding(metadata.get("task_id"), metadata.get("condition"), root / "task_runtime_bindings.json")
    except Exception as exc:
        return [f"binding_resolution_failed: {exc}"]
    if metadata.get("expected_runtime_profile") != binding.runtime_profile:
        errors.append("expected_runtime_profile_changed_or_tampered")
    if metadata.get("task_group") != binding.task_group:
        errors.append("task_group_changed_or_tampered")
    config_path = root / metadata.get("kiro_agent_config", "")
    if not config_path.is_file():
        return errors + ["run_specific_agent_config_missing"]
    config = _read_json(config_path)
    prompt_metadata = _read_json(root / PROMPT_METADATA)
    try:
        _validate_agent_invariants(config, prompt_metadata)
    except ValueError as exc:
        errors.append(f"agent_invariant_failure: {exc}")
    if config.get("name") != metadata.get("kiro_agent_name"):
        errors.append("run_specific_agent_name_mismatch")
    try:
        identity, identity_hash = _runtime_record(root, config)
    except Exception as exc:
        return errors + [f"runtime_identity_resolution_failed: {exc}"]
    if identity.get("dataset_profile") != binding.runtime_profile:
        errors.append("requested_condition_actual_runtime_profile_mismatch")
    if identity != metadata.get("runtime_dataset_identity"):
        errors.append("recorded_runtime_identity_mismatch")
    if identity_hash != metadata.get("runtime_dataset_identity_sha256"):
        errors.append("recorded_runtime_identity_hash_mismatch")
    if _sha256_file(config_path) != metadata.get("kiro_agent_config_sha256"):
        errors.append("run_specific_agent_config_hash_mismatch")
    receipt_path = run_dir = Path(metadata.get("run_directory", config_path.parent)) / "runtime-identity-receipt.json"
    if receipt_path.is_file():
        receipt = _read_json(receipt_path)
        if not receipt.get("passed"):
            errors.append("runtime_identity_receipt_failed")
        if receipt.get("identity") != identity:
            errors.append("runtime_identity_receipt_mismatch")
    elif metadata.get("kiro_session_id"):
        errors.append("runtime_identity_receipt_missing_for_captured_session")
    return errors


def prepare_run(
    run_dir: Path,
    *,
    task_id: str,
    condition: str,
    repetition: int,
    prompt: str,
    root: Path = ROOT,
    actual_runtime_profile: str | None = None,
) -> dict[str, Any]:
    if repetition < 1:
        raise ValueError("repetition must be at least 1")
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {run_dir}")
    binding = resolve_runtime_binding(task_id, condition, root / "task_runtime_bindings.json")
    selected_profile = actual_runtime_profile or binding.runtime_profile
    if selected_profile != binding.runtime_profile:
        raise ValueError(
            f"requested {binding.condition} for {task_id} requires runtime profile "
            f"{binding.runtime_profile!r}, not {selected_profile!r}"
        )
    config_path = root / AGENT_CONFIG
    base_config = _read_json(config_path)
    prompt_metadata = _read_json(root / PROMPT_METADATA)
    _validate_agent_invariants(base_config, prompt_metadata)
    generated_config_path, config = _build_run_config(root, run_dir, base_config, selected_profile)
    runtime, runtime_hash = _runtime_record(root, config)
    if runtime["dataset_profile"] != binding.runtime_profile:
        raise ValueError("generated runtime profile does not match the pre-registered task/condition binding")

    run_dir.mkdir(parents=True)
    generated_config_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(generated_config_path, config)
    prompt_bytes = prompt.encode("utf-8")
    (run_dir / "prompt.txt").write_bytes(prompt_bytes)
    invocation_path = run_dir / "mcp-invocations-live.jsonl"
    invocation_bytes = invocation_path.read_bytes() if invocation_path.is_file() else b""

    command = f"kiro-cli chat --agent {config['name']} --require-mcp-startup"
    (run_dir / "command.txt").write_text(command + "\n", encoding="utf-8")
    metadata = {
        "schema_version": "ax-interactive-run-v2",
        "experiment_version": EXPERIMENT_VERSION,
        "run_status": "PREPARED",
        "validity_status": "PENDING",
        "execution_backend": "INTERACTIVE_FRESH_PROCESS",
        "task_id": task_id,
        "condition": binding.condition,
        "task_group": binding.task_group,
        "defect_variant_id": binding.defect_variant_id,
        "expected_runtime_profile": binding.runtime_profile,
        "actual_runtime_profile": runtime["dataset_profile"],
        "repetition": repetition,
        "prompt_file": "prompt.txt",
        "prompt_sha256": _sha256_bytes(prompt_bytes),
        "runtime_dataset_identity": runtime,
        "runtime_dataset_identity_sha256": runtime_hash,
        "kiro_agent_name": config["name"],
        "kiro_agent_config": generated_config_path.relative_to(root).as_posix(),
        "kiro_agent_config_sha256": _sha256_file(generated_config_path),
        "base_kiro_agent_config": AGENT_CONFIG.as_posix(),
        "base_kiro_agent_config_sha256": _sha256_file(config_path),
        "agent_prompt_version": prompt_metadata["prompt_version"],
        "agent_prompt_sha256": prompt_metadata["prompt_sha256"],
        "model": config["model"],
        "kiro_cli_version": _kiro_cli_version(),
        "git_commit": _git_commit(root),
        "start_timestamp": _utc_now(),
        "end_timestamp": None,
        "fresh_process": True,
        "resume_used": False,
        "command_file": "command.txt",
        "run_directory": str(run_dir.resolve()),
        "invocation_log_source": str(invocation_path.resolve()),
        "runtime_identity_receipt_file": "runtime-identity-receipt.json",
        "invocation_log_start_size": len(invocation_bytes),
        "invocation_log_start_sha256": _sha256_bytes(invocation_bytes),
        "raw_response_file": None,
        "raw_terminal_transcript_file": None,
        "mcp_invocation_log_file": None,
        "parsed_result_file": None,
        "output_contract_valid": None,
        "semantic_json_available": None,
        "tool_call_count": None,
        "used_source_ids": [],
        "semantic_scoring_fields": None,
        "validation_errors": [],
    }
    _write_json(run_dir / "metadata.json", metadata)
    return metadata


def finalize_run(run_dir: Path, *, root: Path = ROOT) -> dict[str, Any]:
    metadata_path = run_dir / "metadata.json"
    metadata = _read_json(metadata_path)
    if metadata["run_status"] != "PREPARED":
        raise ValueError("only a PREPARED run can be finalized")

    raw_path = run_dir / "raw_response.txt"
    if not raw_path.is_file():
        raise FileNotFoundError("raw_response.txt must contain the preserved model response")
    raw_bytes = raw_path.read_bytes()
    raw_response = raw_bytes.decode("utf-8")
    parsed = parse_agent_response(raw_response)

    invocation_path = Path(metadata["invocation_log_source"])
    invocation_bytes = invocation_path.read_bytes() if invocation_path.is_file() else b""
    start_size = metadata["invocation_log_start_size"]
    if start_size > len(invocation_bytes):
        raise ValueError("shared MCP invocation log was truncated during the run")
    if _sha256_bytes(invocation_bytes[:start_size]) != metadata["invocation_log_start_sha256"]:
        raise ValueError("shared MCP invocation log prefix changed during the run")
    run_invocations = invocation_bytes[start_size:]
    invocation_output = run_dir / "mcp-invocations.jsonl"
    invocation_output.write_bytes(run_invocations)
    invocation_count = len([line for line in run_invocations.splitlines() if line.strip()])

    result = {
        "schema_version": "ax-output-contract-result-v1",
        "output_contract_valid": parsed.output_contract_valid,
        "semantic_json_available": parsed.semantic_json_available,
        "parsed_result": parsed.parsed_result,
    }
    result_path = run_dir / "parsed_result.json"
    _write_json(result_path, result)

    transcript_path = run_dir / "terminal-transcript.txt"
    semantic_fields = parsed.parsed_result
    captured_session = bool(metadata.get("kiro_session_id"))
    consistency_errors = _consistency_errors(metadata, root)
    if consistency_errors:
        validity_status = "INVALID"
    elif captured_session:
        validity_status = "VALID"
    else:
        validity_status = "REQUIRES_MANUAL_PROTOCOL_REVIEW"
    metadata.update({
        "run_status": "RECORDED",
        "validity_status": validity_status,
        "validation_errors": consistency_errors,
        "end_timestamp": _utc_now(),
        "raw_response_file": raw_path.name,
        "raw_response_sha256": _sha256_bytes(raw_bytes),
        "raw_terminal_transcript_file": transcript_path.name if transcript_path.is_file() else None,
        "raw_terminal_transcript_sha256": _sha256_file(transcript_path) if transcript_path.is_file() else None,
        "mcp_invocation_log_file": invocation_output.name,
        "mcp_invocation_log_sha256": _sha256_bytes(run_invocations),
        "mcp_invocation_count": invocation_count,
        "tool_call_count": invocation_count,
        "parsed_result_file": result_path.name,
        "output_contract_valid": parsed.output_contract_valid,
        "semantic_json_available": parsed.semantic_json_available,
        "used_source_ids": semantic_fields.get("source_ids", []) if semantic_fields else [],
        "semantic_scoring_fields": semantic_fields,
    })
    _write_json(metadata_path, metadata)
    return metadata


def capture_kiro_session(
    run_dir: Path,
    session_id: str,
    *,
    sessions_root: Path | None = None,
) -> dict[str, Any]:
    """Preserve the exact final assistant text from one explicit Kiro session."""
    metadata_path = run_dir / "metadata.json"
    metadata = _read_json(metadata_path)
    if metadata["run_status"] != "PREPARED":
        raise ValueError("session capture requires a PREPARED run")
    sessions_root = sessions_root or (Path.home() / ".kiro" / "sessions" / "cli")
    session_path = sessions_root / f"{session_id}.json"
    session = _read_json(session_path)
    if session.get("session_id") != session_id:
        raise ValueError("Kiro session ID does not match its filename")
    state = session["session_state"]
    if state.get("agent_name") != metadata.get("kiro_agent_name"):
        raise ValueError("Kiro session did not use the prepared run-specific evaluation agent")
    turns = state["conversation_metadata"]["user_turn_metadatas"]
    if len(turns) != 1:
        raise ValueError("a frozen interactive run must contain exactly one user turn")
    turn = turns[0]
    outcome = turn["result"]
    if "Ok" not in outcome:
        raise ValueError("Kiro turn did not complete successfully")
    content = outcome["Ok"]["content"]
    raw_response = "".join(item["data"] for item in content if item.get("kind") == "text")
    if not raw_response:
        raise ValueError("Kiro session contains no final assistant text")
    (run_dir / "raw_response.txt").write_bytes(raw_response.encode("utf-8"))
    credits = sum(
        item["value"] for item in turn.get("metering_usage", []) if item.get("unit") == "credit"
    )
    duration = turn.get("turn_duration", {})
    metadata.update({
        "kiro_session_id": session_id,
        "kiro_session_file": str(session_path),
        "kiro_turn_end_timestamp": turn.get("end_timestamp"),
        "kiro_turn_duration_seconds": duration.get("secs", 0) + duration.get("nanos", 0) / 1_000_000_000,
        "kiro_credits": credits,
    })
    _write_json(metadata_path, metadata)
    return metadata


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--run-dir", type=Path, required=True)
    prepare.add_argument("--task-id", required=True)
    prepare.add_argument("--condition", required=True)
    prepare.add_argument("--repetition", type=int, required=True)
    prepare.add_argument("--prompt-file", type=Path, required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--run-dir", type=Path, required=True)
    capture = subparsers.add_parser("capture-session")
    capture.add_argument("--run-dir", type=Path, required=True)
    capture.add_argument("--session-id", required=True)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.action == "prepare":
        prompt = arguments.prompt_file.read_bytes().decode("utf-8")
        result = prepare_run(
            arguments.run_dir,
            task_id=arguments.task_id,
            condition=arguments.condition,
            repetition=arguments.repetition,
            prompt=prompt,
        )
    elif arguments.action == "capture-session":
        result = capture_kiro_session(arguments.run_dir, arguments.session_id)
    else:
        result = finalize_run(arguments.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
