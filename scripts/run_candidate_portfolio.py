"""Run catalog task candidates through the real product boundary.

This is an exploratory product diagnostic, not a benchmark runner.  It keeps
the same API validation, Kiro runner, write-once result store, evidence check,
and deterministic Finding aggregation used by the console.  Existing final
runs are reused so an interrupted portfolio can be resumed safely.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ax_product.api import create_app
from ax_product.console_contracts import BusinessTaskCatalog
from ax_product.runner import KiroProductRunner


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "business_task_catalog.json"
DEFAULT_CONFIG = ROOT / "runtime_datasets.json"
DEFAULT_MODEL = "claude-sonnet-5"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_").lower()
    if not slug:
        raise ValueError(f"cannot create run-id component from {value!r}")
    return slug


def run_id(
    profile: str, task_id: str, repetition: int, *, namespace: str = "portfolio"
) -> str:
    value = f"{_slug(namespace)}-{_slug(profile)}-{_slug(task_id)}-r{repetition}"
    if len(value) > 128:
        raise ValueError(f"generated run_id is too long: {value}")
    return value


def _executable(override: str | None) -> str:
    if override is not None:
        if not override.strip():
            raise ValueError("--kiro-cli must not be blank")
        return str(Path(override).resolve())
    selected = shutil.which("kiro-cli") or shutil.which("kiro-cli.exe")
    if selected is None:
        raise FileNotFoundError("kiro-cli executable not found; pass --kiro-cli")
    return selected


def _version(executable: str) -> str:
    completed = subprocess.run(
        [executable, "--version"], cwd=ROOT, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        shell=False, check=False, timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"kiro-cli --version failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _select_tasks(catalog_path: Path, task_ids: list[str]) -> list[dict[str, Any]]:
    catalog = BusinessTaskCatalog.model_validate_json(
        catalog_path.read_text(encoding="utf-8")
    )
    by_id = {task.task_id: task for task in catalog.tasks}
    if len(by_id) != len(catalog.tasks):
        raise ValueError("task catalog contains duplicate task IDs")
    selected_ids = task_ids or [task.task_id for task in catalog.tasks]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("--task-id values must be unique")
    unknown = sorted(set(selected_ids) - set(by_id))
    if unknown:
        raise ValueError(f"unknown task IDs: {unknown}")
    return [by_id[task_id].model_dump(mode="json") for task_id in selected_ids]


def _row(
    *, profile: str, task: dict[str, Any], repetition: int, current_run_id: str,
    delivery: dict[str, Any], duration_seconds: float, reused: bool,
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = delivery.get("payload") or {}
    return {
        "dataset": profile,
        "task_id": task["task_id"],
        "category": task["category"],
        "question": task["question"],
        "repetition": repetition,
        "run_id": current_run_id,
        "reused_existing_final": reused,
        "duration_seconds": round(duration_seconds, 3),
        "delivery_status": delivery["delivery_status"],
        "reject_reason": delivery.get("reject_reason"),
        "payload_status": payload.get("status"),
        "abstention_reason": payload.get("abstention_reason"),
        "answer": payload.get("answer"),
        "unit": payload.get("unit"),
        "source_ids": payload.get("source_ids", []),
        "evidence_verdict": None if evidence is None else evidence.get("verdict"),
    }


def _profile_summary(rows: list[dict[str, Any]], findings: dict[str, Any]) -> dict[str, Any]:
    outcomes = Counter(
        row["payload_status"] if row["delivery_status"] == "DELIVERED"
        else "REJECTED"
        for row in rows
    )
    abstentions = Counter(
        row["abstention_reason"] for row in rows if row["abstention_reason"]
    )
    evidence = Counter(
        row["evidence_verdict"] for row in rows if row["evidence_verdict"]
    )
    return {
        "run_count": len(rows),
        "outcomes": dict(sorted(outcomes.items())),
        "abstention_reasons": dict(sorted(abstentions.items())),
        "evidence_verdicts": dict(sorted(evidence.items())),
        "diagnostics": findings["diagnostics"],
        "finding_count": len(findings["findings"]),
        "finding_types": dict(sorted(Counter(
            finding["finding_type"] for finding in findings["findings"]
        ).items())),
    }


def execute(
    *, profiles: list[str], results_root: Path, summary_path: Path,
    dataset_config: Path, catalog_path: Path, task_ids: list[str],
    repetitions: int, model: str, timeout_seconds: float, kiro_cli: str | None,
    run_namespace: str = "portfolio",
) -> dict[str, Any]:
    if not profiles or len(profiles) != len(set(profiles)):
        raise ValueError("at least one unique --dataset is required")
    if repetitions < 1:
        raise ValueError("--repetitions must be at least 1")
    tasks = _select_tasks(catalog_path, task_ids)
    executable = _executable(kiro_cli)
    kiro_version = _version(executable)
    runner = KiroProductRunner(
        project_root=ROOT,
        dataset_config=dataset_config,
        executable=executable,
        timeout_seconds=timeout_seconds,
        python_executable=sys.executable,
    )
    client = TestClient(create_app(
        results_root=results_root,
        dataset_config=dataset_config,
        runner=runner,
        task_catalog_path=catalog_path,
    ))
    readiness = {}
    for profile in profiles:
        response = client.get(f"/api/readiness/{profile}")
        response.raise_for_status()
        readiness[profile] = response.json()

    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "schema_version": "ax-candidate-portfolio-pilot-v1",
        "claim_scope": "EXPLORATORY_PRODUCT_PILOT_NOT_RESEARCH_BENCHMARK",
        "started_at": _utc_now(),
        "completed_at": None,
        "dataset_config": str(dataset_config.resolve()),
        "task_catalog": str(catalog_path.resolve()),
        "model": model,
        "kiro_cli_version": kiro_version,
        "fresh_process_per_new_run": True,
        "profiles": profiles,
        "task_ids": [task["task_id"] for task in tasks],
        "repetitions": repetitions,
        "run_namespace": _slug(run_namespace),
        "readiness": readiness,
        "profile_summaries": {},
        "findings": {},
        "runs": rows,
    }
    _write_json(summary_path, summary)

    for profile in profiles:
        for task in tasks:
            for repetition in range(1, repetitions + 1):
                current_run_id = run_id(
                    profile, task["task_id"], repetition,
                    namespace=run_namespace,
                )
                delivery_path = results_root / current_run_id / "delivery.json"
                started = time.perf_counter()
                if delivery_path.is_file():
                    response = client.get(f"/api/runs/{current_run_id}")
                    reused = True
                else:
                    response = client.post("/api/run", json={
                        "dataset": profile,
                        "request_type": "TASK_CANDIDATE",
                        "task_id": task["task_id"],
                        "question": task["question"],
                        "run_id": current_run_id,
                        "model": model,
                    })
                    reused = False
                duration = time.perf_counter() - started
                response.raise_for_status()
                evidence_response = client.get(
                    f"/api/runs/{current_run_id}/evidence-check"
                )
                evidence = (
                    evidence_response.json()
                    if evidence_response.status_code == 200 else None
                )
                rows.append(_row(
                    profile=profile, task=task, repetition=repetition,
                    current_run_id=current_run_id, delivery=response.json(),
                    duration_seconds=duration, reused=reused, evidence=evidence,
                ))
                _write_json(summary_path, summary)

    for profile in profiles:
        response = client.get(f"/api/findings/{profile}")
        response.raise_for_status()
        findings = response.json()
        summary["findings"][profile] = findings
        summary["profile_summaries"][profile] = _profile_summary(
            [row for row in rows if row["dataset"] == profile], findings
        )
    summary["completed_at"] = _utc_now()
    _write_json(summary_path, summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", dest="profiles", required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--dataset-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--task-catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--kiro-cli")
    parser.add_argument("--run-namespace", default="portfolio")
    return parser


def main() -> int:
    args = _parser().parse_args()
    summary = execute(
        profiles=args.profiles,
        results_root=args.results_root.resolve(),
        summary_path=args.summary.resolve(),
        dataset_config=args.dataset_config.resolve(),
        catalog_path=args.task_catalog.resolve(),
        task_ids=args.task_id,
        repetitions=args.repetitions,
        model=args.model,
        timeout_seconds=args.timeout_seconds,
        kiro_cli=args.kiro_cli,
        run_namespace=args.run_namespace,
    )
    print(json.dumps({
        "summary": str(args.summary.resolve()),
        "profile_summaries": summary["profile_summaries"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
