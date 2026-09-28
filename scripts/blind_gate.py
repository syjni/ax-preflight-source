"""Prepare and verify the blind Kiro runtime-feasibility gate.

This module never invokes Kiro or an AX tool.  Preparation hashes the frozen
Ceiling inputs before it writes the prompt and empty result artifacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity

from .runtime_prompt import construct_runtime_prompt, project_runtime_prompt


ROOT = Path(__file__).resolve().parents[1]
STRESS_TASK_IDS = (
    "O01_CUSTOMER_COUNT",
    "O05_HIGHEST_AVAILABLE_STOCK",
    "C01_HANBIT_AUGUST_TOTAL",
    "C04_YUNSEONG_LAST_ORDER",
    "C07_DAON_TOP_ORDER_PRODUCT",
)
REPETITIONS_PER_TASK = 2
BENCHMARK_CRITICAL_ARTIFACTS = (
    "benchmark_tasks.json",
    "ceiling_scan_report.json",
    "ceiling_validation.json",
    "control_sources.json",
    "dataset_manifest.json",
    "ground_truth.json",
    "runtime_blind_sample.schema.json",
    "runtime_blind_samples.json",
    "task_to_defect_manifest.json",
)
PROMPT_PATH_ARTIFACTS = (
    "scripts/runtime_prompt.py",
)
KIRO_AGENT_CONFIG = ".kiro/agents/ax-evaluation.json"
FORBIDDEN_FIELD_MARKERS = (
    "expected_answer",
    "primary_blocker",
    "required_sources",
    "tool_plan",
    "table_id",
    "table ids",
    "source ids",
    "defect ground truth",
    "defect_ground_truth",
    "filters",
    "intermediate_ids",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _aggregate_sha256(records: list[dict[str, Any]]) -> str:
    canonical = "".join(
        f"{record['path']}\0{record['size_bytes']}\0{record['sha256']}\n"
        for record in records
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _tasks(root: Path) -> list[dict[str, Any]]:
    benchmark = _read_json(root / "benchmark_tasks.json")
    by_id = {task["task_id"]: task for task in benchmark["tasks"]}
    missing = [task_id for task_id in STRESS_TASK_IDS if task_id not in by_id]
    if missing:
        raise ValueError(f"missing predeclared stress tasks: {missing}")
    return [by_id[task_id] for task_id in STRESS_TASK_IDS]


def _runtime_prompts(root: Path) -> list[str]:
    return [construct_runtime_prompt(project_runtime_prompt(task)) for task in _tasks(root)]


def render_prompt_markdown(root: Path = ROOT) -> str:
    lines = [
        "# Blind Kiro Runtime Gate Prompts",
        "",
        "Submit each fenced prompt verbatim in the numbered order. Use each prompt for both predeclared repetitions.",
        "",
    ]
    for index, prompt in enumerate(_runtime_prompts(root), start=1):
        lines.extend((f"## Prompt {index:02d}", "", "```text", prompt, "```", ""))
    return "\n".join(lines)


def _initial_results(root: Path) -> dict[str, Any]:
    runs = []
    for task in _tasks(root):
        for repetition in range(1, REPETITIONS_PER_TASK + 1):
            runs.append({
                "task_id": task["task_id"],
                "repetition": repetition,
                "raw_final_output": None,
                "parsed_final_answer": None,
                "source_ids": [],
                "abstain": None,
                "tool_sequence": [],
                "tool_call_count": None,
                "system_failure": None,
                "scoring_result": "NOT_RUN",
                "retrieval_outcome": "NOT_RUN",
                "notes": "",
                "run_status": "NOT_RUN",
            })
    return {
        "schema_version": "ax-blind-kiro-runtime-gate-results-v1",
        "dataset_id": _read_json(root / "dataset_manifest.json")["dataset_id"],
        "execution_status": "NOT_RUN",
        "repetitions_per_task": REPETITIONS_PER_TASK,
        "run_count": len(runs),
        "recording_enums": {
            "execution_status": ["NOT_RUN", "IN_PROGRESS", "COMPLETE"],
            "run_status": ["NOT_RUN", "RECORDED"],
            "scoring_result": [
                "NOT_RUN", "CORRECT_SUPPORTED", "INCORRECT_SUPPORTED", "CORRECT_ABSTENTION",
                "UNJUSTIFIED_ABSTENTION", "HALLUCINATION", "INVALID_OUTPUT", "SYSTEM_FAILURE",
            ],
            "retrieval_outcome": [
                "NOT_RUN", "REQUIRED_SOURCES_RETRIEVED", "PARTIAL_REQUIRED_SOURCES_RETRIEVED",
                "NO_REQUIRED_SOURCES_RETRIEVED", "NOT_OBSERVABLE",
            ],
        },
        "runs": runs,
    }


def _frozen_records(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = _read_json(root / "dataset_manifest.json")
    source_root = root / manifest["source_root"]
    dataset_paths = [source_root / entry["relative_path"] for entry in manifest["files"]]
    critical_paths = [root / relative for relative in BENCHMARK_CRITICAL_ARTIFACTS]
    prompt_paths = [root / relative for relative in PROMPT_PATH_ARTIFACTS]
    missing = [str(path) for path in dataset_paths + critical_paths + prompt_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"cannot freeze missing artifacts: {missing}")
    return (
        [_file_record(root, path) for path in dataset_paths],
        [_file_record(root, path) for path in critical_paths],
        [_file_record(root, path) for path in prompt_paths],
    )


def _runtime_configuration(root: Path) -> dict[str, Any]:
    path = root / KIRO_AGENT_CONFIG
    config = _read_json(path)
    server = config["mcpServers"]["ax-tools"]
    args = server["args"]
    env = server.get("env", {})
    profile = env.get("AX_RUNTIME_DATASET")
    config_path = env.get("AX_RUNTIME_DATASET_CONFIG")
    if profile != "ceiling" or not config_path:
        raise ValueError("Kiro agent must explicitly select AX_RUNTIME_DATASET=ceiling")
    dataset = resolve_runtime_dataset(profile, config_path)
    if dataset.scan_report != (root / "ceiling_scan_report.json").resolve():
        raise ValueError("Kiro Ceiling profile is not bound to ceiling_scan_report.json")
    if dataset.source_root != (root / "sample_data" / "ceiling_company").resolve():
        raise ValueError("Kiro Ceiling profile is not bound to sample_data/ceiling_company")
    return {
        "agent_config": _file_record(root, path),
        "agent_prompt_sha256": hashlib.sha256(config["prompt"].encode("utf-8")).hexdigest(),
        "model": config["model"],
        "tools": config["tools"],
        "mcp_args": args,
        "dataset_profile": profile,
        "dataset_config": str(Path(config_path).resolve()),
        "dataset_config_artifact": _file_record(root, Path(config_path).resolve()),
        "runtime_identity": runtime_identity(dataset),
    }


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _walk_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _walk_strings(child)]
    if value is None:
        return []
    return [str(value)]


def validate_prompt_leakage(root: Path = ROOT) -> dict[str, Any]:
    prompt_path = root / "blind_gate_prompts.md"
    actual = prompt_path.read_text(encoding="utf-8")
    expected = render_prompt_markdown(root)
    prompts = re.findall(r"```text\n(.*?)\n```", actual, flags=re.DOTALL)
    expected_prompts = _runtime_prompts(root)
    violations: list[dict[str, str]] = []

    if actual != expected:
        violations.append({"type": "noncanonical_markdown", "detail": "file is not the exact canonical renderer output"})
    if prompts != expected_prompts:
        violations.append({"type": "prompt_constructor_mismatch", "detail": "fenced prompts differ from runtime_prompt.py output"})

    folded = actual.casefold()
    for marker in FORBIDDEN_FIELD_MARKERS:
        if marker.casefold() in folded:
            violations.append({"type": "forbidden_field_marker", "detail": marker})

    tasks = _tasks(root)
    allowed = {value.casefold() for prompt in expected_prompts for value in (prompt,)}
    hidden_literals: set[str] = set()
    for task in tasks:
        for field in ("expected_answer", "primary_blocker", "required_sources", "tool_plan"):
            hidden_literals.update(value.strip() for value in _walk_strings(task.get(field)) if len(value.strip()) >= 3)
    scan = _read_json(root / "ceiling_scan_report.json")
    for value in _walk_strings(scan):
        if re.fullmatch(r"(?:TABLE|SRC|DOC)[-_A-Za-z0-9]+", value, flags=re.IGNORECASE):
            hidden_literals.add(value)
    for literal in sorted(hidden_literals, key=str.casefold):
        folded_literal = literal.casefold()
        if folded_literal in folded and not any(folded_literal in item for item in allowed):
            violations.append({"type": "hidden_literal", "detail": literal})

    return {
        "name": "blind_gate_prompt_leakage_validation",
        "passed": not violations,
        "prompt_count": len(prompts),
        "canonical_constructor_match": actual == expected and prompts == expected_prompts,
        "forbidden_field_markers_checked": list(FORBIDDEN_FIELD_MARKERS),
        "hidden_literals_checked": len(hidden_literals),
        "violations": violations,
    }


def prepare_blind_gate(root: Path = ROOT) -> dict[str, Any]:
    # Freeze the current bytes before generating any gate artifacts.
    dataset_records, critical_records, prompt_path_records = _frozen_records(root)
    runtime_configuration = _runtime_configuration(root)
    prompt_path = root / "blind_gate_prompts.md"
    results_path = root / "blind_gate_results.json"
    manifest_path = root / "blind_gate_manifest.json"

    prompt_path.write_text(render_prompt_markdown(root), encoding="utf-8")
    _write_json(results_path, _initial_results(root))
    leakage = validate_prompt_leakage(root)
    if not leakage["passed"]:
        raise ValueError(f"refusing to create a leaky gate: {leakage['violations']}")

    tasks = _tasks(root)
    prompt_record = {**_file_record(root, prompt_path), "mutable_after_first_run": False}
    results_record = {**_file_record(root, results_path), "mutable_after_first_run": True}
    generated_records = [prompt_record, results_record]
    manifest = {
        "schema_version": "ax-blind-kiro-runtime-gate-manifest-v1",
        "dataset_id": _read_json(root / "dataset_manifest.json")["dataset_id"],
        "gate_status": "PREPARED_NOT_RUN",
        "purpose": "Blind Kiro runtime-feasibility gate only; not the 9/22 Before/After/Ceiling experiment.",
        "hash_algorithm": "SHA-256",
        "stress_subset": [
            {"prompt_number": index, "task_id": task["task_id"], "category": task["category"]}
            for index, task in enumerate(tasks, start=1)
        ],
        "repetitions_per_task": REPETITIONS_PER_TASK,
        "planned_run_count": len(tasks) * REPETITIONS_PER_TASK,
        "prompt_construction": {
            "function_chain": ["scripts.runtime_prompt.project_runtime_prompt", "scripts.runtime_prompt.construct_runtime_prompt"],
            "allowed_projected_fields": ["category", "question"],
            "artifacts": prompt_path_records,
        },
        "runtime_configuration": runtime_configuration,
        "frozen_artifacts": {
            "dataset": {
                "root": _read_json(root / "dataset_manifest.json")["source_root"],
                "file_count": len(dataset_records),
                "aggregate_sha256": _aggregate_sha256(dataset_records),
                "files": dataset_records,
            },
            "benchmark": {
                "file_count": len(critical_records),
                "aggregate_sha256": _aggregate_sha256(critical_records),
                "files": critical_records,
            },
        },
        "generated_gate_artifacts": generated_records,
        "recording_protocol": {
            "results_file_is_mutable_after_first_run": True,
            "one_fresh_kiro_session_per_run": True,
            "prompt_submission": "verbatim fenced prompt only",
            "score_only_after_raw_output_and_tool_trace_are_captured": True,
        },
        "leakage_validation": leakage,
    }
    _write_json(manifest_path, manifest)
    return validate_blind_gate(root)


def validate_blind_gate(root: Path = ROOT) -> dict[str, Any]:
    manifest = _read_json(root / "blind_gate_manifest.json")
    violations: list[dict[str, str]] = []
    for group_name in ("dataset", "benchmark"):
        group = manifest["frozen_artifacts"][group_name]
        current_records = []
        for frozen in group["files"]:
            path = root / frozen["path"]
            if not path.is_file():
                violations.append({"type": "missing_frozen_artifact", "detail": frozen["path"]})
                continue
            current = _file_record(root, path)
            current_records.append(current)
            if current != frozen:
                violations.append({"type": "frozen_artifact_changed", "detail": frozen["path"]})
        if len(current_records) == len(group["files"]) and _aggregate_sha256(current_records) != group["aggregate_sha256"]:
            violations.append({"type": "aggregate_hash_mismatch", "detail": group_name})

    immutable_gate_artifacts = [
        frozen for frozen in manifest["generated_gate_artifacts"]
        if not frozen.get("mutable_after_first_run")
    ]
    for frozen in manifest["prompt_construction"]["artifacts"] + immutable_gate_artifacts:
        path = root / frozen["path"]
        expected = {key: frozen[key] for key in ("path", "size_bytes", "sha256")}
        if not path.is_file() or _file_record(root, path) != expected:
            violations.append({"type": "gate_artifact_changed", "detail": frozen["path"]})

    runtime_configuration = manifest["runtime_configuration"]
    frozen_config = runtime_configuration["agent_config"]
    config_path = root / frozen_config["path"]
    if not config_path.is_file() or _file_record(root, config_path) != frozen_config:
        violations.append({"type": "runtime_configuration_changed", "detail": frozen_config["path"]})
    else:
        config = _read_json(config_path)
        prompt_hash = hashlib.sha256(config["prompt"].encode("utf-8")).hexdigest()
        if prompt_hash != runtime_configuration["agent_prompt_sha256"]:
            violations.append({"type": "kiro_prompt_changed", "detail": frozen_config["path"]})
    frozen_dataset_config = runtime_configuration["dataset_config_artifact"]
    dataset_config_path = root / frozen_dataset_config["path"]
    if not dataset_config_path.is_file() or _file_record(root, dataset_config_path) != frozen_dataset_config:
        violations.append({"type": "runtime_dataset_config_changed", "detail": frozen_dataset_config["path"]})

    results = _read_json(root / "blind_gate_results.json")
    execution_status = results.get("execution_status")
    recording_enums = results.get("recording_enums", {})
    if execution_status not in set(recording_enums.get("execution_status", [])):
        violations.append({"type": "unexpected_execution_status", "detail": str(results.get("execution_status"))})
    expected_runs = len(STRESS_TASK_IDS) * REPETITIONS_PER_TASK
    if len(results.get("runs", [])) != expected_runs:
        violations.append({"type": "run_count_mismatch", "detail": str(len(results.get("runs", [])))})
    recorded_count = 0
    for run in results.get("runs", []):
        label = f"{run.get('task_id')} repetition {run.get('repetition')}"
        if run.get("run_status") == "NOT_RUN":
            if run.get("scoring_result") != "NOT_RUN" or run.get("retrieval_outcome") != "NOT_RUN":
                violations.append({"type": "inconsistent_not_run_record", "detail": label})
        elif run.get("run_status") == "RECORDED":
            recorded_count += 1
            if run.get("scoring_result") == "NOT_RUN" or run.get("retrieval_outcome") == "NOT_RUN":
                violations.append({"type": "incomplete_recorded_run", "detail": label})
            if run.get("scoring_result") not in set(recording_enums.get("scoring_result", [])):
                violations.append({"type": "invalid_scoring_result", "detail": label})
            if run.get("retrieval_outcome") not in set(recording_enums.get("retrieval_outcome", [])):
                violations.append({"type": "invalid_retrieval_outcome", "detail": label})
            if not isinstance(run.get("tool_sequence"), list) or run.get("tool_call_count") != len(run.get("tool_sequence", [])):
                violations.append({"type": "tool_trace_count_mismatch", "detail": label})
        else:
            violations.append({"type": "invalid_run_status", "detail": label})
    if execution_status == "NOT_RUN" and recorded_count:
        violations.append({"type": "execution_status_mismatch", "detail": "NOT_RUN with recorded runs"})
    if execution_status == "IN_PROGRESS" and not 0 < recorded_count < expected_runs:
        violations.append({"type": "execution_status_mismatch", "detail": "IN_PROGRESS requires a partial set of recorded runs"})
    if execution_status == "COMPLETE" and recorded_count != expected_runs:
        violations.append({"type": "execution_status_mismatch", "detail": "COMPLETE requires every run to be recorded"})

    leakage = validate_prompt_leakage(root)
    violations.extend({"type": "prompt_leakage", "detail": json.dumps(item, ensure_ascii=False)} for item in leakage["violations"])
    return {
        "schema_version": "ax-blind-kiro-runtime-gate-validation-v1",
        "passed": not violations,
        "gate_status": manifest["gate_status"],
        "frozen_dataset_files_checked": len(manifest["frozen_artifacts"]["dataset"]["files"]),
        "frozen_benchmark_files_checked": len(manifest["frozen_artifacts"]["benchmark"]["files"]),
        "leakage_validation": leakage,
        "violations": violations,
    }
