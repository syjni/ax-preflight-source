"""Verify that the v5 runner passed a real multi-message development session."""

from __future__ import annotations

import json
from pathlib import Path

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity
from scripts.session_prompt_validation import validate_submitted_prompt
from scripts.stream_response_validation import validate_stream_response
from scripts.v5_official_runner import ROOT


RUN = ROOT / "artifacts" / "v5_development" / "runner_probe" / "DEV_V5_MULTI_01" / "r1"
V5 = ROOT / "experiment" / "v5"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate() -> dict:
    errors: list[str] = []
    metadata = read(RUN / "metadata.json")
    if metadata.get("validity_status") != "VALID" or metadata.get("validation_errors"):
        errors.append("development runner did not finish valid")
    if metadata.get("runtime_profile") != "v5-development":
        errors.append("development profile not selected")
    expected = runtime_identity(resolve_runtime_dataset("v5-development", V5 / "runtime_datasets.json"))
    receipt = read(RUN / "runtime-identity-receipt.json")
    if receipt.get("passed") is not True or receipt.get("identity") != expected:
        errors.append("development runtime identity mismatch")
    submitted = validate_submitted_prompt(RUN, metadata["session_id"], metadata["agent_name"])
    responses = submitted.pop("assistant_responses")
    if submitted != read(RUN / "submitted-prompt-validation.json") or not submitted["passed"]:
        errors.append("development prompt mismatch")
    raw = (RUN / "raw_response.txt").read_text(encoding="utf-8")
    if len(responses) != 1 or responses[-1] != raw:
        errors.append("development final response mismatch")
    stream = validate_stream_response(RUN / "stream.jsonl", Path(metadata["session_events_file"]),
                                      session_id=metadata["session_id"], final_response=raw)
    if stream != read(RUN / "stream-response-validation.json") or not stream["passed"]:
        errors.append("development stream validation mismatch")
    if stream["nonempty_assistant_message_count"] < 2 or stream["aggregate_sha256"] == stream["final_response_sha256"]:
        errors.append("development session did not exercise aggregate/final distinction")
    evaluation = read(RUN / "evaluation.json")
    if evaluation.get("outcome") != "CORRECT_SUPPORTED" or evaluation.get("delivered_valid") is not True:
        errors.append("development delivery path failed")
    config = read(ROOT / metadata["agent_config"])
    if config.get("model") != "claude-sonnet-5" or config.get("prompt") != (V5 / "AGENT_PROMPT.txt").read_text(encoding="utf-8"):
        errors.append("development agent model or prompt differs")
    if config.get("mcpServers", {}).get("ax-tools", {}).get("env", {}).get("AX_RUNTIME_DATASET") != "v5-development":
        errors.append("development agent evidence profile differs")
    return {"passed": not errors, "development_only": True, "errors": errors,
            "assistant_message_count": stream["assistant_message_count"],
            "aggregate_differs_from_final": stream["aggregate_sha256"] != stream["final_response_sha256"]}


def main() -> int:
    result = validate()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
