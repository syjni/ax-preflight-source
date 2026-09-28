"""Read-only audit and frozen-score summary for the completed v3 held-out runs.

This script writes only a derived JSON summary. It never edits run artifacts or
changes the frozen answer scorer or output-contract parser.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from ax_agent.models import AgentOutput
from scripts.ceiling_scoring import OutcomeState, score_agent_output


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "artifacts" / "heldout_ax-exp-v3"
CORRECT = {OutcomeState.CORRECT_SUPPORTED.value, OutcomeState.CORRECT_ABSTENTION.value}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit() -> dict:
    bindings = read_json(ROOT / "task_runtime_bindings.json")["bindings"]
    benchmark = {task["task_id"]: task for task in read_json(ROOT / "benchmark_tasks.json")["tasks"]}
    ground_truth = {task["task_id"]: task for task in read_json(ROOT / "ground_truth.json")["tasks"]}
    expected = [(task["task_id"], condition, repetition)
                for repetition in (1, 2) for task in bindings
                for condition in ("Before", "Ceiling")]
    binding_by_id = {task["task_id"]: task for task in bindings}
    rows: list[dict] = []
    excluded: list[dict] = []
    errors: list[str] = []

    for metadata_path in RUNS.rglob("metadata.json"):
        run_dir = metadata_path.parent
        meta = read_json(metadata_path)
        key = (meta["task_id"], meta["condition"], meta["repetition"])
        label = "/".join(map(str, key))
        if meta["validity_status"] != "VALID":
            excluded.append({"directory": str(run_dir.relative_to(ROOT)),
                             "status": meta["validity_status"],
                             "reason": meta.get("invalid_reason")})
            continue

        binding = binding_by_id.get(meta["task_id"])
        if binding is None:
            errors.append(f"{label}: unregistered task")
            continue
        if (meta["run_status"] != "RECORDED"
                or meta["execution_backend"] != "SEMI_AUTOMATED_FRESH_PROCESS"
                or meta["task_group"] != binding["task_group"]
                or meta["expected_runtime_profile"] != binding["runtime_profiles"][meta["condition"]]
                or meta["actual_runtime_profile"] != meta["expected_runtime_profile"]
                or meta["submitted_prompt_matches_prepared"] is not True
                or meta["prepared_prompt_sha256"] != meta["submitted_prompt_sha256"]
                or meta["user_turn_count"] != 1 or meta["prompt_event_count"] != 1
                or meta["prompt_validation_errors"] or meta["validation_errors"]
                or meta["fresh_process"] is not True or meta["resume_used"] is not False
                or meta["process_terminated"] is not True or not meta["process_id"]
                or not meta["kiro_session_id"]):
            errors.append(f"{label}: invalid metadata invariant")

        files = {
            "prompt_sha256": run_dir / "prompt.txt",
            "raw_response_sha256": run_dir / "raw_response.txt",
            "mcp_invocation_log_sha256": run_dir / "mcp-invocations.jsonl",
            "prompt_validation_receipt_sha256": run_dir / "submitted-prompt-validation.json",
            "kiro_agent_config_sha256": ROOT / meta["kiro_agent_config"],
            "kiro_session_file_sha256": Path(meta["kiro_session_file"]),
            "kiro_session_events_file_sha256": Path(meta["kiro_session_events_file"]),
        }
        for field, path in files.items():
            if not path.is_file() or sha256(path) != meta[field]:
                errors.append(f"{label}: missing or changed {field}")

        prompt_receipt = read_json(run_dir / "submitted-prompt-validation.json")
        runtime_receipt = read_json(run_dir / "runtime-identity-receipt.json")
        if (prompt_receipt["passed"] is not True
                or prompt_receipt["session_id"] != meta["kiro_session_id"]
                or runtime_receipt["passed"] is not True
                or runtime_receipt["identity"] != meta["runtime_dataset_identity"]
                or runtime_receipt["runtime_leakage"]["passed"] is not True):
            errors.append(f"{label}: failed receipt")

        parsed = read_json(run_dir / "parsed_result.json")
        if (parsed["output_contract_valid"] != meta["output_contract_valid"]
                or parsed["semantic_json_available"] != meta["semantic_json_available"]
                or parsed["parsed_result"] != meta["semantic_scoring_fields"]):
            errors.append(f"{label}: parsed result mismatch")
        if benchmark[meta["task_id"]]["expected_answer"] != ground_truth[meta["task_id"]]["expected_answer"]:
            errors.append(f"{label}: benchmark and independent truth differ")

        semantic = parsed["parsed_result"]
        outcome = (score_agent_output(benchmark[meta["task_id"]],
                                      AgentOutput.model_validate(semantic, strict=True)).value
                   if semantic is not None else "NO_SEMANTIC_JSON")
        rows.append({
            "task_id": meta["task_id"], "task_group": meta["task_group"],
            "condition": meta["condition"], "repetition": meta["repetition"],
            "directory": str(run_dir.relative_to(ROOT)),
            "start_timestamp": meta["start_timestamp"],
            "session_id": meta["kiro_session_id"],
            "runtime_identity_sha256": meta["runtime_dataset_identity_sha256"],
            "output_contract_valid": meta["output_contract_valid"],
            "semantic_json_available": meta["semantic_json_available"],
            "outcome": outcome, "correct": outcome in CORRECT,
            "mcp_invocation_count": meta["mcp_invocation_count"],
        })

    actual = [(r["task_id"], r["condition"], r["repetition"]) for r in rows]
    duplicate_keys = [key for key, count in Counter(actual).items() if count != 1]
    if len(rows) != 64 or set(actual) != set(expected) or duplicate_keys:
        errors.append(f"matrix mismatch: {len(rows)} valid, duplicates={duplicate_keys}, missing={set(expected)-set(actual)}")
    chronological = [(r["task_id"], r["condition"], r["repetition"])
                     for r in sorted(rows, key=lambda r: r["start_timestamp"])]
    if chronological != expected:
        errors.append("registered execution order differs")
    if len({r["session_id"] for r in rows}) != 64:
        errors.append("session IDs are not unique")
    by_key = {(r["task_id"], r["condition"], r["repetition"]): r for r in rows}
    for task in bindings:
        if task["task_group"] == "control":
            for repetition in (1, 2):
                before = by_key[(task["task_id"], "Before", repetition)]
                ceiling = by_key[(task["task_id"], "Ceiling", repetition)]
                if before["runtime_identity_sha256"] != ceiling["runtime_identity_sha256"]:
                    errors.append(f"{task['task_id']}/r{repetition}: control evidence differs")

    if errors:
        return {"audit_passed": False, "errors": errors, "valid_run_count": len(rows),
                "excluded_attempts": excluded}

    def aggregate(group: str, condition: str) -> dict:
        selected = [r for r in rows if r["task_group"] == group and r["condition"] == condition]
        return {"runs": len(selected), "correct": sum(r["correct"] for r in selected),
                "strict_output_contract": sum(r["output_contract_valid"] for r in selected),
                "correct_and_strict": sum(r["correct"] and r["output_contract_valid"] for r in selected),
                "semantic_json_available": sum(r["semantic_json_available"] for r in selected),
                "outcomes": dict(sorted(Counter(r["outcome"] for r in selected).items()))}

    transitions = {}
    for group in ("treated", "control"):
        pairs = [(by_key[(task["task_id"], "Before", repetition)],
                  by_key[(task["task_id"], "Ceiling", repetition)])
                 for task in bindings if task["task_group"] == group for repetition in (1, 2)]
        transitions[group] = {
            "improved": sum(not before["correct"] and ceiling["correct"] for before, ceiling in pairs),
            "worsened": sum(before["correct"] and not ceiling["correct"] for before, ceiling in pairs),
            "unchanged_correct": sum(before["correct"] and ceiling["correct"] for before, ceiling in pairs),
            "unchanged_incorrect": sum(not before["correct"] and not ceiling["correct"] for before, ceiling in pairs),
        }

    rows.sort(key=lambda r: (r["repetition"], [b["task_id"] for b in bindings].index(r["task_id"]),
                             ("Before", "Ceiling").index(r["condition"])))
    return {"schema_version": "ax-exp-v3-derived-analysis-v1", "audit_passed": True,
            "errors": [], "valid_run_count": len(rows), "excluded_attempts": excluded,
            "unique_session_count": len({r["session_id"] for r in rows}),
            "registered_order_passed": True,
            "groups": {group: {condition: aggregate(group, condition)
                               for condition in ("Before", "Ceiling")}
                       for group in ("treated", "control")},
            "paired_transitions": transitions, "runs": rows}


def main() -> None:
    result = audit()
    output = RUNS / "ANALYSIS.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "runs"}, ensure_ascii=False, indent=2))
    if not result["audit_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
