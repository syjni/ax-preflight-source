"""One non-official Kiro development probe on a separate one-file corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity
from scripts.session_prompt_validation import validate_submitted_prompt
from scripts.v4_evaluation import evaluate_response
from scripts.v4_prompt import construct_runtime_prompt


ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "experiment" / "v4"
RUN = ROOT / "artifacts" / "v4_development" / "kiro_223_probe"
AGENT_NAME = "ax-v4-development-probe"
AGENT_PATH = ROOT / ".kiro" / "agents" / f"{AGENT_NAME}.json"
DEV_TASK = {
    "task_id": "DEV_KIRO_EXACT_01",
    "category": "knowledge",
    "question": "2027년 시범 매장 재고 점검의 책임팀은 어디인가요?",
    "expected_answer": "시설운영팀",
    "scoring_method": {"type": "exact_text", "accepted_forms": ["시설운영팀"]},
    "expects_abstention": False,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare() -> tuple[str, dict]:
    if RUN.exists():
        raise FileExistsError(f"development probe already exists: {RUN}")
    RUN.mkdir(parents=True)
    prompt = construct_runtime_prompt(DEV_TASK)
    (RUN / "prompt.txt").write_bytes(prompt.encode("utf-8"))
    base = json.loads((ROOT / ".kiro/agents/ax-evaluation.json").read_text(encoding="utf-8"))
    base["name"] = AGENT_NAME
    base["prompt"] = (V4 / "AGENT_PROMPT.txt").read_text(encoding="utf-8")
    server = base["mcpServers"]["ax-tools"]
    server["args"] = [
        "-m", "ax_mcp.server", "--invocation-log", str(RUN / "mcp-invocations-live.jsonl"),
        "--runtime-identity-output", str(RUN / "runtime-identity-receipt.json"),
    ]
    server["env"]["AX_RUNTIME_DATASET"] = "v4-development"
    server["env"]["AX_RUNTIME_DATASET_CONFIG"] = str(V4 / "runtime_datasets.json")
    _write(AGENT_PATH, base)
    metadata = {
        "experiment_version": "ax-exp-v4-development-only",
        "task_id": DEV_TASK["task_id"],
        "kiro_agent_name": AGENT_NAME,
        "kiro_agent_config_sha256": _sha(AGENT_PATH),
        "prompt_sha256": _sha(RUN / "prompt.txt"),
        "runtime_profile": "v4-development",
    }
    _write(RUN / "metadata.json", metadata)
    return prompt, metadata


def run() -> dict:
    prompt, metadata = prepare()
    binary = shutil.which("kiro-cli")
    if binary is None:
        raise FileNotFoundError("kiro-cli")
    command = [binary, "chat", "--no-interactive", "--output-format", "stream-json",
               "--agent-engine", "v2", "--agent", AGENT_NAME,
               "--require-mcp-startup", prompt]
    _write(RUN / "command.json", command)
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, shell=False)
    stdout, stderr = process.communicate(timeout=180)
    (RUN / "stream.jsonl").write_bytes(stdout)
    (RUN / "kiro-stderr.txt").write_bytes(stderr)
    metadata.update({"process_id": process.pid, "process_exit_code": process.returncode,
                     "process_terminated": process.poll() is not None,
                     "fresh_process": True, "resume_used": False})
    events = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    finished = [event["data"] for event in events if event.get("type") == "runFinished"]
    if len(finished) != 1:
        raise RuntimeError(f"expected one runFinished event, got {len(finished)}")
    final = finished[0]
    session_id = final["sessionId"]
    receipt = validate_submitted_prompt(RUN, session_id, AGENT_NAME)
    responses = receipt.pop("assistant_responses")
    _write(RUN / "submitted-prompt-validation.json", receipt)
    if not responses:
        raise RuntimeError("Kiro session has no assistant response")
    raw_response = responses[-1]
    (RUN / "raw_response.txt").write_bytes(raw_response.encode("utf-8"))
    evaluation = evaluate_response(DEV_TASK, raw_response)
    _write(RUN / "evaluation.json", evaluation.receipt())
    runtime_receipt = json.loads((RUN / "runtime-identity-receipt.json").read_text(encoding="utf-8"))
    expected_runtime = runtime_identity(resolve_runtime_dataset("v4-development", V4 / "runtime_datasets.json"))
    checks = {
        "process_success": process.returncode == 0,
        "stream_success": final.get("status") == "success" and final.get("finalTextTruncated") is False,
        "stream_matches_session": final.get("finalText") == raw_response,
        "prompt_receipt_passed": receipt["passed"],
        "runtime_receipt_passed": runtime_receipt.get("passed") is True,
        "runtime_identity_matches": runtime_receipt.get("identity") == expected_runtime,
        "run_agent_config_unchanged": _sha(AGENT_PATH) == metadata["kiro_agent_config_sha256"],
        "answer_correct": evaluation.correct,
    }
    metadata.update({"session_id": session_id, "checks": checks,
                     "all_checks_passed": all(checks.values()),
                     "native_strict": evaluation.native_strict,
                     "delivered_valid": evaluation.delivered_valid,
                     "gate_decision": evaluation.gate_decision})
    _write(RUN / "metadata.json", metadata)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("refusing to contact Kiro without --execute")
    result = run()
    print(json.dumps({"development_only": True, "all_checks_passed": result["all_checks_passed"],
                      "session_id": result["session_id"], "checks": result["checks"],
                      "native_strict": result["native_strict"],
                      "delivered_valid": result["delivered_valid"]}, ensure_ascii=False, indent=2))
    return 0 if result["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
