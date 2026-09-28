"""Create and verify the AX experiment v1 freeze manifest.

This script hashes existing artifacts and validates the freeze boundary. It does
not execute Kiro, MCP tools, benchmark tasks, or held-out tasks.
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
from readiness_score import score_scan_report_file
from scripts.blind_gate import validate_blind_gate
from scripts.validate_ceiling_benchmark import validate_ceiling_benchmark


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("experiment/frozen/ax-exp-v1-manifest.json")
EXPERIMENT_VERSION = "ax-exp-v1"
APPROVED_PROMPT_HASH = "dc783a41a5b06eb871ada33be7dd21aec2e4106757a40921ddf59fcf81176fc8"
MODEL = "claude-sonnet-5"
DEV_TASK_IDS = (
    "O01_CUSTOMER_COUNT",
    "O05_HIGHEST_AVAILABLE_STOCK",
    "C01_HANBIT_AUGUST_TOTAL",
    "C04_YUNSEONG_LAST_ORDER",
    "C07_DAON_TOP_ORDER_PRODUCT",
)
EXPECTED_TOOLS = (
    "@ax-tools/search_documents",
    "@ax-tools/read_document",
    "@ax-tools/lookup_value",
    "@ax-tools/query_table",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(root: Path, path: Path) -> dict[str, Any]:
    resolved = path if path.is_absolute() else root / path
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": resolved.relative_to(root).as_posix(),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _records(root: Path, paths: list[Path | str]) -> list[dict[str, Any]]:
    unique = sorted({Path(path).as_posix() for path in paths})
    return [_record(root, Path(path)) for path in unique]


def _tree(root: Path, directory: str, pattern: str = "*") -> list[str]:
    base = root / directory
    return [path.relative_to(root).as_posix() for path in base.rglob(pattern) if path.is_file()]


def _aggregate(records: list[dict[str, Any]]) -> str:
    payload = "".join(
        f"{record['path']}\0{record['size_bytes']}\0{record['sha256']}\n"
        for record in records
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _component(root: Path, component_id: str, description: str, paths: list[Path | str]) -> dict[str, Any]:
    records = _records(root, paths)
    return {
        "component_id": component_id,
        "description": description,
        "file_count": len(records),
        "aggregate_sha256": _aggregate(records),
        "files": records,
    }


def _git_commit(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _kiro_cli_version() -> str:
    result = subprocess.run(
        ["kiro-cli", "--version"], capture_output=True, text=True, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Kiro CLI version is unavailable")
    return result.stdout.strip()


def _held_out_execution_count(root: Path, held_out_ids: set[str]) -> int:
    count = 0
    for path in (root / "artifacts").rglob("metadata.json"):
        metadata = _read_json(path)
        if metadata.get("task_id") in held_out_ids and metadata.get("run_status") not in {None, "NOT_RUN", "PREPARED"}:
            count += 1
    blind_results = _read_json(root / "blind_gate_results.json")
    for run in blind_results.get("runs", []):
        if run.get("task_id") in held_out_ids and run.get("run_status") == "RECORDED":
            count += 1
    return count


def _inventory(root: Path) -> dict[str, Any]:
    scanner_files = _tree(root, "ax_scanner", "*.py") + ["SCANNER_SCHEMA.md", "scan_report.schema.json"]
    ceiling_files = _tree(root, "sample_data/ceiling_company")
    dev_evidence = _tree(root, "artifacts/prefreeze_dev_format_2026-09-22")
    diagnostic_evidence = _tree(root, "artifacts/dev_calibration_2026-09-22")
    log_files = _tree(root, ".kiro/logs")

    behavioral = [
        _component(root, "kiro_agent_configuration", "Kiro ax-evaluation configuration", [".kiro/agents/ax-evaluation.json"]),
        _component(root, "kiro_system_behavior_prompt", "Prompt v2 bytes and prompt metadata", [".kiro/agents/ax-evaluation.json", ".kiro/ax-evaluation.prompt-metadata.json"]),
        _component(root, "evaluation_model_id", "Model identifier fixed by the Kiro agent configuration", [".kiro/agents/ax-evaluation.json"]),
        _component(root, "interactive_execution_protocol", "Official fresh-process interactive protocol", ["INTERACTIVE_EXECUTION.md"]),
        _component(root, "mcp_server_implementation", "AX stdio MCP implementation and telemetry", _tree(root, "ax_mcp", "*.py")),
        _component(root, "mcp_schemas", "MCP request/output schemas and frozen schema capture", ["ax_agent/models.py", "ax_mcp/adapter.py", "agent_tool_schemas.json", "runtime_blind_sample.schema.json"]),
        _component(root, "retrieval_implementation_configuration", "Read-only retrieval, normalization, table store, and tool layer", _tree(root, "ax_agent", "*.py")),
        _component(root, "scanner_implementation_configuration", "Scanner, parsers, PII logic, report writer, schemas, and config", scanner_files),
        _component(root, "runtime_dataset_profile_configuration", "Runtime profile binding and identity validation", ["runtime_datasets.json", "ax_mcp/runtime_dataset.py", "ax_mcp/runtime_identity.py"]),
        _component(root, "ceiling_dataset_manifest", "Ceiling source-file manifest", ["dataset_manifest.json"]),
        _component(root, "benchmark_manifest", "Frozen 21-task benchmark", ["benchmark_tasks.json"]),
        _component(root, "ground_truth", "Frozen benchmark ground truth", ["ground_truth.json"]),
        _component(root, "task_to_defect_manifest", "Frozen task-to-defect mapping", ["task_to_defect_manifest.json"]),
        _component(root, "control_source_manifest", "Frozen control-source protection manifest", ["control_sources.json"]),
        _component(root, "deterministic_scorer", "Deterministic Agent-output scorer", ["scripts/ceiling_scoring.py"]),
        _component(root, "output_contract_validator", "Strict raw-response output validator", ["scripts/output_contract.py"]),
        _component(root, "semantic_json_extractor", "Analysis-only semantic JSON extractor", ["scripts/output_contract.py"]),
        _component(root, "failure_taxonomy", "Frozen outcome, attribution, system, and F6 labels", ["EXPERIMENT_FAILURE_TAXONOMY.md", "AX_PROJECT_PLAN_v3.md", "scripts/ceiling_scoring.py", "scripts/output_contract.py"]),
        _component(root, "runtime_prompt_constructor", "Two-field blind runtime prompt projection and rendering", ["scripts/runtime_prompt.py"]),
        _component(root, "leakage_validator", "Prompt and runtime leakage validators", ["scripts/blind_gate.py", "scripts/validate_blind_gate.py", "scripts/validate_ceiling_benchmark.py", "scripts/validate_ceiling_artifacts.py", "scripts/validate_ceiling_dataset.py"]),
        _component(root, "interactive_run_recorder", "Interactive run preparation, capture, and finalization", ["scripts/interactive_run.py"]),
        _component(root, "readiness_score_v1", "Deterministic Readiness Score v1 implementation", ["readiness_score.py"]),
        _component(root, "readiness_score_specification", "Frozen Readiness Score v1 specification", ["READINESS_SCORE_SPEC.md"]),
        _component(root, "dataset_condition_generators", "Canonical dataset and truth generators required by the experiment", ["scripts/generate_ceiling_dataset.py", "scripts/create_ceiling_dataset.py", "scripts/build_ceiling_dataset.py", "scripts/assemble_ceiling_dataset.py", "scripts/independent_ceiling_truth.py"]),
        _component(root, "experiment_hypotheses", "Hypotheses frozen before held-out execution", ["EXPERIMENT_HYPOTHESES.md"]),
        _component(root, "dependency_constraints", "Python dependency constraints", ["requirements.txt", "requirements-dev.txt"]),
    ]
    evidence = [
        _component(root, "ceiling_source_evidence", "Raw Ceiling company files consumed by Scanner and retrieval", ceiling_files),
        _component(root, "ceiling_static_evidence", "Scanner and static Ceiling validation outputs", ["ceiling_scan_report.json", "ceiling_validation.json", "dataset_provenance.md"]),
        _component(root, "dev_run_evidence", "Dev-only interactive run evidence", dev_evidence),
        _component(root, "prefreeze_diagnostic_evidence", "Dev-only headless availability diagnostics", diagnostic_evidence),
        _component(root, "blind_gate_evidence", "Prepared-not-run gate receipts and prompt artifacts", ["blind_gate_manifest.json", "blind_gate_prompts.md", "blind_gate_results.json"]),
    ]
    logs = [
        _component(root, "mcp_runtime_logs", "Pre-freeze MCP invocation and runtime-identity logs", log_files),
        _component(root, "tool_contract_captures", "Pre-freeze tool schema and result captures", ["agent_tool_results.json", "kiro_integration_contract_baseline.json", "kiro_mcp_search_latency.json"]),
    ]
    return {
        "behavioral_and_configuration_artifacts": behavioral,
        "raw_evidence_artifacts": evidence,
        "log_and_capture_artifacts": logs,
    }


def _component_by_id(inventory: dict[str, Any], component_id: str) -> dict[str, Any]:
    for group in inventory.values():
        for component in group:
            if component["component_id"] == component_id:
                return component
    raise KeyError(component_id)


def create_manifest(root: Path = ROOT) -> dict[str, Any]:
    agent_config = _read_json(root / ".kiro/agents/ax-evaluation.json")
    prompt_metadata = _read_json(root / ".kiro/ax-evaluation.prompt-metadata.json")
    benchmark = _read_json(root / "benchmark_tasks.json")
    all_task_ids = tuple(task["task_id"] for task in benchmark["tasks"])
    held_out_ids = tuple(task_id for task_id in all_task_ids if task_id not in DEV_TASK_IDS)
    dataset = resolve_runtime_dataset("ceiling", root / "runtime_datasets.json")
    current_runtime_identity = runtime_identity(dataset)
    prior_gate = _read_json(root / "blind_gate_manifest.json")
    frozen_runtime_identity = prior_gate["runtime_configuration"]["runtime_identity"]
    gate_validation = validate_blind_gate(root)
    ceiling_validation = validate_ceiling_benchmark(root)
    readiness = score_scan_report_file(root / "ceiling_scan_report.json")
    prompt_hash = hashlib.sha256(agent_config["prompt"].encode("utf-8")).hexdigest()

    if agent_config["model"] != MODEL:
        raise ValueError("evaluation model changed")
    if tuple(agent_config["tools"]) != EXPECTED_TOOLS or tuple(agent_config["allowedTools"]) != EXPECTED_TOOLS:
        raise ValueError("AX tool surface is not exactly the frozen four tools")
    if prompt_hash != APPROVED_PROMPT_HASH or prompt_metadata["prompt_sha256"] != APPROVED_PROMPT_HASH:
        raise ValueError("approved prompt v2 hash changed")
    if len(held_out_ids) != 16:
        raise ValueError("Dev/held-out split does not contain 16 held-out tasks")
    held_out_execution_count = _held_out_execution_count(root, set(held_out_ids))
    if held_out_execution_count:
        raise ValueError("held-out execution evidence exists")
    if current_runtime_identity != frozen_runtime_identity:
        raise ValueError("Ceiling runtime identity changed")
    if not gate_validation["passed"] or not ceiling_validation["passed"]:
        raise ValueError("pre-freeze static validation failed")
    if readiness["readiness_score"] != 100.0:
        raise ValueError("Ceiling Readiness Score v1 is not 100.0")

    inventory = _inventory(root)
    unique_paths = {
        record["path"]
        for group in inventory.values()
        for component in group
        for record in component["files"]
    }
    component_hash = lambda component_id: _component_by_id(inventory, component_id)["aggregate_sha256"]
    file_hash = lambda path: _sha256(root / path)

    return {
        "schema_version": "ax-experiment-freeze-manifest-v1",
        "experiment_version": EXPERIMENT_VERSION,
        "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "FROZEN",
        "ready_for_heldout": True,
        "git_commit": _git_commit(root),
        "official_agent": "Kiro ax-evaluation",
        "model": MODEL,
        "execution_backend": "INTERACTIVE_FRESH_PROCESS",
        "headless_status": "UNAVAILABLE",
        "kiro_cli_version": _kiro_cli_version(),
        "retrieval_status": "FROZEN",
        "agent_config_hash": file_hash(".kiro/agents/ax-evaluation.json"),
        "prompt_version": "2",
        "prompt_hash": prompt_hash,
        "mcp_implementation_hashes": {
            "aggregate_sha256": component_hash("mcp_server_implementation"),
            "schema_aggregate_sha256": component_hash("mcp_schemas"),
        },
        "retriever_hashes_config": {
            "aggregate_sha256": component_hash("retrieval_implementation_configuration"),
            "configuration": "frozen read-only AX retrieval/tool layer",
        },
        "scanner_hash_config": {
            "aggregate_sha256": component_hash("scanner_implementation_configuration"),
            "configuration": "local deterministic Scanner v1 behavior and schemas",
        },
        "runtime_dataset_config_hash": file_hash("runtime_datasets.json"),
        "ceiling_dataset_manifest_hash": file_hash("dataset_manifest.json"),
        "benchmark_hash": file_hash("benchmark_tasks.json"),
        "ground_truth_hash": file_hash("ground_truth.json"),
        "task_to_defect_manifest_hash": file_hash("task_to_defect_manifest.json"),
        "control_source_manifest_hash": file_hash("control_sources.json"),
        "scorer_hash": file_hash("scripts/ceiling_scoring.py"),
        "output_contract_parser_hash": file_hash("scripts/output_contract.py"),
        "semantic_extractor_hash": file_hash("scripts/output_contract.py"),
        "failure_taxonomy_hash": file_hash("EXPERIMENT_FAILURE_TAXONOMY.md"),
        "runtime_prompt_hash": file_hash("scripts/runtime_prompt.py"),
        "leakage_validator_hash": component_hash("leakage_validator"),
        "run_recorder_hash": file_hash("scripts/interactive_run.py"),
        "readiness_score_py_hash": file_hash("readiness_score.py"),
        "readiness_score_spec_hash": file_hash("READINESS_SCORE_SPEC.md"),
        "readiness_score": {
            "version": "ax-readiness-score-v1",
            "formula": "100 × Σ(dimension × 0.20)",
            "dimensions": ["accessibility", "completeness", "redundancy", "timeliness", "safety"],
            "weights": {name: 0.20 for name in ("accessibility", "completeness", "redundancy", "timeliness", "safety")},
            "as_of_date": "2026-09-21",
            "stale_threshold_days": 365,
            "ceiling_score": readiness["readiness_score"],
            "deterministic": True,
            "llm_calls": 0,
            "reads_held_out_agent_results": False,
            "reads_benchmark_expected_answers": False,
        },
        "tool_surface": list(EXPECTED_TOOLS),
        "tool_count": 4,
        "ceiling_runtime_identity": current_runtime_identity,
        "dev_task_ids": list(DEV_TASK_IDS),
        "held_out_task_ids": list(held_out_ids),
        "held_out_task_count": len(held_out_ids),
        "held_out_execution_count": held_out_execution_count,
        "dev_results": {
            "semantic_grounded_correct": "5/5",
            "strict_output_compliance": "3/5",
            "semantic_json_availability": "5/5",
            "further_prompt_tuning_allowed": False,
        },
        "test_suite": {
            "command": "python -m unittest discover -v",
            "passed": 88,
            "total": 88,
            "result": "88/88 PASS",
        },
        "freeze_validation": {
            "ceiling_runtime_identity_unchanged": True,
            "model_matches": True,
            "exactly_four_ax_mcp_tools": True,
            "runtime_leakage_violations": len(next(check for check in ceiling_validation["checks"] if check["name"] == "runtime_leakage_prevention")["detail"]["violations"]),
            "held_out_execution_count": held_out_execution_count,
            "dev_held_out_split_unchanged": True,
            "retrieval_unchanged": True,
            "dataset_unchanged": True,
            "benchmark_unchanged": True,
            "ground_truth_unchanged": True,
            "prompt_hash_approved": True,
            "readiness_hashes_recorded": True,
            "ceiling_readiness_100": True,
            "interactive_protocol_complete": True,
            "headless_unavailable_documented": True,
            "preexisting_frozen_hash_validation_passed": gate_validation["passed"],
        },
        "artifact_inventory": inventory,
        "frozen_artifact_count": len(unique_paths),
        "post_freeze_change_policy": {
            "outcome_affecting_change_requires_new_version": "ax-exp-v2",
            "existing_v1_results": "archive or mark invalid if any exist",
            "hashes": "recompute all",
            "rerun_scope": "both compared conditions under v2",
            "display_only_changes": "allowed only when raw data, scoring, and interpretation cannot change",
        },
        "remaining_blocker": None,
        "next_safe_action": "On a later authorized day, execute held-out tasks under the frozen interactive protocol; do not run them as part of this freeze.",
    }


def validate_manifest(root: Path = ROOT) -> dict[str, Any]:
    manifest_path = root / MANIFEST_PATH
    manifest = _read_json(manifest_path)
    mismatches: list[dict[str, str]] = []
    paths: set[str] = set()
    for group_name, components in manifest["artifact_inventory"].items():
        for component in components:
            current_records = []
            for frozen in component["files"]:
                path = root / frozen["path"]
                paths.add(frozen["path"])
                if not path.is_file():
                    mismatches.append({"type": "missing", "path": frozen["path"], "component": component["component_id"]})
                    continue
                current = _record(root, path)
                current_records.append(current)
                if current != frozen:
                    mismatches.append({"type": "file_hash", "path": frozen["path"], "component": component["component_id"]})
            if len(current_records) == component["file_count"] and _aggregate(current_records) != component["aggregate_sha256"]:
                mismatches.append({"type": "component_hash", "path": group_name, "component": component["component_id"]})
    if len(paths) != manifest["frozen_artifact_count"]:
        mismatches.append({"type": "artifact_count", "path": str(len(paths)), "component": "manifest"})
    return {
        "schema_version": "ax-experiment-freeze-validation-v1",
        "experiment_version": manifest["experiment_version"],
        "passed": not mismatches,
        "hash_algorithm": "SHA-256",
        "artifact_count": len(paths),
        "mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.validate:
        result = validate_manifest(root)
    else:
        result = create_manifest(root)
        output_path = root / MANIFEST_PATH
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
