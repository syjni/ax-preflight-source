"""Official ax-exp-v3 semi-automated fresh-process runner."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from scripts.interactive_run_v3 import ROOT, capture_kiro_session_v3, finalize_run_v3, prepare_run_v3
from scripts.runtime_prompt import construct_runtime_prompt, project_runtime_prompt


DEFAULT_ARTIFACT_ROOT = Path("artifacts/heldout_ax-exp-v3")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _session_ids(sessions_root: Path) -> set[str]:
    return {path.stem for path in sessions_root.glob("*.json") if path.is_file()}


def _new_agent_sessions(before: set[str], expected_agent: str, sessions_root: Path) -> list[str]:
    matches = []
    for session_id in sorted(_session_ids(sessions_root) - before):
        try:
            session = _read(sessions_root / f"{session_id}.json")
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if session.get("session_state", {}).get("agent_name") == expected_agent:
            matches.append(session_id)
    return matches


def _copy_exact_prompt(prompt: str) -> None:
    powershell = shutil.which("powershell") or shutil.which("powershell.exe")
    if not powershell:
        raise FileNotFoundError("PowerShell is required for clipboard preparation")
    completed = subprocess.run(
        [
            powershell, "-NoProfile", "-STA", "-Command",
            "$utf8=[Text.UTF8Encoding]::new($false); [Console]::InputEncoding=$utf8; "
            "$text=[Console]::In.ReadToEnd(); Set-Clipboard -Value $text",
        ],
        input=prompt.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"failed to copy prompt to clipboard: {completed.stderr.decode('utf-8', errors='replace')}")


def run_one(
    run_dir: Path,
    *,
    root: Path = ROOT,
    sessions_root: Path | None = None,
    executable: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    run_dir = run_dir.resolve()
    sessions_root = sessions_root or (Path.home() / ".kiro" / "sessions" / "cli")
    metadata_path = run_dir / "metadata.json"
    metadata = _read(metadata_path)
    if metadata.get("experiment_version") != "ax-exp-v3" or metadata.get("run_status") != "PREPARED":
        raise ValueError("run-one requires a PREPARED ax-exp-v3 run")
    prompt_bytes = (run_dir / "prompt.txt").read_bytes()
    prompt = prompt_bytes.decode("utf-8")
    if not prompt:
        raise ValueError("refusing to launch Kiro with an empty prompt")
    _copy_exact_prompt(prompt)
    binary = executable or shutil.which("kiro-cli")
    if not binary:
        raise FileNotFoundError("kiro-cli executable not found")
    before = _session_ids(sessions_root)
    metadata["session_ids_before_launch"] = sorted(before)
    metadata["operator_action"] = "Paste once with Ctrl+V, submit once, wait for completion, then exit the process."
    _write(metadata_path, metadata)
    print(f"Prepared {metadata['task_id']} {metadata['condition']} r{metadata['repetition']}.")
    print("The exact prompt is on the clipboard. In the new Kiro window: Ctrl+V, Enter, wait, then exit.")
    creationflags = subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
    process = subprocess.Popen(
        [binary, "chat", "--agent", metadata["kiro_agent_name"], "--require-mcp-startup"],
        cwd=root,
        shell=False,
        creationflags=creationflags,
    )
    exit_code = process.wait()
    metadata = _read(metadata_path)
    metadata.update({
        "process_id": process.pid,
        "process_exit_code": exit_code,
        "process_terminated": process.poll() is not None,
        "fresh_process": True,
        "resume_used": False,
    })
    _write(metadata_path, metadata)
    candidates = _new_agent_sessions(before, metadata["kiro_agent_name"], sessions_root)
    if len(candidates) != 1:
        metadata["validity_status"] = "INVALID"
        metadata["invalid_reason"] = "INVALID_SESSION_DISCOVERY"
        metadata["validation_errors"] = [f"INVALID_SESSION_DISCOVERY: candidates={candidates}"]
        _write(metadata_path, metadata)
        return metadata
    capture_kiro_session_v3(run_dir, candidates[0], sessions_root=sessions_root)
    return finalize_run_v3(run_dir, root=root)


def _task_prompt(root: Path, task_id: str) -> str:
    benchmark = _read(root / "benchmark_tasks.json")
    matches = [task for task in benchmark["tasks"] if task["task_id"] == task_id]
    if len(matches) != 1:
        raise ValueError(f"unknown benchmark task: {task_id}")
    return construct_runtime_prompt(project_runtime_prompt(matches[0]))


def _prepare_and_run(root: Path, artifact_root: Path, task_id: str, condition: str, repetition: int) -> dict[str, Any]:
    run_dir = artifact_root / task_id / condition / f"r{repetition}"
    prepare_run_v3(
        run_dir,
        task_id=task_id,
        condition=condition,
        repetition=repetition,
        prompt=_task_prompt(root, task_id),
        root=root,
    )
    result = run_one(run_dir, root=root)
    if result.get("validity_status") != "VALID":
        raise RuntimeError(f"run stopped as {result.get('validity_status')}: {result.get('validation_errors')}")
    return result


def run_pair(root: Path, artifact_root: Path, task_id: str, repetition: int) -> list[dict[str, Any]]:
    return [_prepare_and_run(root, artifact_root, task_id, condition, repetition) for condition in ("Before", "Ceiling")]


def run_all(root: Path, artifact_root: Path) -> list[dict[str, Any]]:
    bindings = _read(root / "task_runtime_bindings.json")["bindings"]
    results = []
    for repetition in (1, 2):
        for entry in bindings:
            for condition in ("Before", "Ceiling"):
                results.append(_prepare_and_run(root, artifact_root, entry["task_id"], condition, repetition))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    one = sub.add_parser("run-one")
    one.add_argument("--run-dir", type=Path, required=True)
    one.add_argument("--execute", action="store_true")
    pair = sub.add_parser("run-pair")
    pair.add_argument("--task-id", required=True)
    pair.add_argument("--repetition", type=int, choices=(1, 2), required=True)
    pair.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    pair.add_argument("--execute", action="store_true")
    all_runs = sub.add_parser("run-all")
    all_runs.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    all_runs.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("refusing to start official runs without explicit --execute")
    if args.action == "run-one":
        result: Any = run_one(args.run_dir)
    elif args.action == "run-pair":
        result = run_pair(ROOT, args.artifact_root.resolve(), args.task_id, args.repetition)
    else:
        result = run_all(ROOT, args.artifact_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
