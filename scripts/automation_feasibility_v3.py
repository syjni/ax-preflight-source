"""Run two harmless Dev-only Kiro automation probes for ax-exp-v3."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from scripts.semi_auto_runner_v3 import _session_ids
from scripts.interactive_run_v3 import ROOT
from scripts.session_prompt_validation import validate_submitted_prompt


DEFAULT_OUTPUT = Path("artifacts/v3_automation_feasibility_2026-09-20")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_probe(root: Path, output_root: Path, index: int, sessions_root: Path) -> dict[str, Any]:
    run_dir = output_root / f"smoke-{index}"
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite feasibility evidence: {run_dir}")
    run_dir.mkdir(parents=True)
    prompt = (
        f"업무 범주: dev_validation\n"
        f"질문: 자동 실행 경로 검증 {index}입니다. 회사 사실을 추정하지 말고 증거가 부족하면 abstain 하세요."
    )
    (run_dir / "prompt.txt").write_bytes(prompt.encode("utf-8"))
    base = _read(root / ".kiro/agents/ax-evaluation.json")
    name = f"ax-evaluation-v3-dev-smoke-{index}"
    base["name"] = name
    server = base["mcpServers"]["ax-tools"]
    server["env"]["AX_RUNTIME_DATASET"] = "mini"
    server["env"]["AX_RUNTIME_DATASET_CONFIG"] = str((root / "runtime_datasets.json").resolve())
    server["args"] = [
        "-m", "ax_mcp.server",
        "--invocation-log", str((run_dir / "mcp-invocations.jsonl").resolve()),
        "--runtime-identity-output", str((run_dir / "runtime-identity-receipt.json").resolve()),
    ]
    agent_path = root / ".kiro" / "agents" / f"{name}.json"
    _write(agent_path, base)
    _write(run_dir / "metadata.json", {
        "schema_version": "ax-v3-automation-feasibility-run-v1",
        "experiment_version": "ax-exp-v3",
        "task_id": f"DEV_AUTOMATION_SMOKE_{index}",
        "run_status": "PREPARED",
        "kiro_agent_name": name,
        "prepared_prompt_sha256": _sha_bytes(prompt.encode("utf-8")),
        "prompt_sha256": _sha_bytes(prompt.encode("utf-8")),
    })
    executable = shutil.which("kiro-cli")
    if not executable:
        raise FileNotFoundError("kiro-cli executable not found")
    before = _session_ids(sessions_root)
    argv = [
        executable, "chat", "--agent", name, "--require-mcp-startup",
        "--no-interactive", prompt,
    ]
    process = subprocess.Popen(
        argv, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", shell=False,
    )
    stdout, stderr = process.communicate(timeout=300)
    (run_dir / "kiro-stdout.jsonl").write_text(stdout, encoding="utf-8")
    (run_dir / "kiro-stderr.txt").write_text(stderr, encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(f"Dev automation probe failed: exit={process.returncode}, stderr={stderr[-1000:]}")
    candidates = sorted(_session_ids(sessions_root) - before)
    exact = []
    for candidate in candidates:
        try:
            candidate_validation = validate_submitted_prompt(run_dir, candidate, name, sessions_root=sessions_root)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            continue
        if candidate_validation["passed"]:
            exact.append(candidate)
    if len(exact) != 1:
        raise RuntimeError(f"expected one persisted exact-prompt session; candidates={candidates}, exact={exact}")
    session_id = exact[0]
    validation = validate_submitted_prompt(run_dir, session_id, name, sessions_root=sessions_root)
    responses = validation.pop("assistant_responses")
    if responses:
        (run_dir / "raw_response.txt").write_text(responses[-1], encoding="utf-8")
    _write(run_dir / "submitted-prompt-validation.json", validation)
    return {
        "probe": index,
        "dev_only": True,
        "process_id": process.pid,
        "process_exit_code": process.returncode,
        "process_terminated": process.poll() is not None,
        "session_id": session_id,
        "user_turn_count": validation["user_turn_count"],
        "submitted_prompt_matches_prepared": validation["submitted_prompt_matches_prepared"],
        "prompt_validation_passed": validation["passed"],
        "runtime_identity_receipt_exists": (run_dir / "runtime-identity-receipt.json").is_file(),
        "response_captured": bool(responses and responses[-1]),
        "run_directory": str(run_dir),
    }


def run_feasibility(root: Path = ROOT, output_root: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output_root = (output_root or (root / DEFAULT_OUTPUT)).resolve()
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite feasibility evidence: {output_root}")
    output_root.mkdir(parents=True)
    sessions_root = Path.home() / ".kiro" / "sessions" / "cli"
    probes = [run_probe(root, output_root, index, sessions_root) for index in (1, 2)]
    checks = {
        "two_fresh_processes": len({probe["process_id"] for probe in probes}) == 2,
        "two_distinct_sessions": len({probe["session_id"] for probe in probes}) == 2,
        "one_run_one_process": len(probes) == 2 and all(probe["process_id"] for probe in probes),
        "one_user_turn_each": all(probe["user_turn_count"] == 1 for probe in probes),
        "exact_prompt_each": all(probe["submitted_prompt_matches_prepared"] for probe in probes),
        "response_capture_each": all(probe["response_captured"] for probe in probes),
        "process_termination_each": all(probe["process_terminated"] for probe in probes),
        "runtime_identity_receipt_each": all(probe["runtime_identity_receipt_exists"] for probe in probes),
        "next_run_fresh_process": probes[0]["process_id"] != probes[1]["process_id"],
        "held_out_prompt_used": False,
    }
    result = {
        "schema_version": "ax-v3-automation-feasibility-v1",
        "experiment_version": "ax-exp-v3",
        "kiro_cli_version": subprocess.run(["kiro-cli", "--version"], capture_output=True, text=True, check=True).stdout.strip(),
        "tested_backend": "AUTOMATED_FRESH_PROCESS",
        "input_transport": "single positional INPUT argument with --no-interactive",
        "output_transport": "text stdout plus authoritative session JSON/JSONL capture",
        "dev_only": True,
        "held_out_execution_count": 0,
        "passed": all(value is True or key == "held_out_prompt_used" and value is False for key, value in checks.items()),
        "checks": checks,
        "probes": probes,
    }
    _write(output_root / "automation-feasibility.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    result = run_feasibility(args.root, args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
