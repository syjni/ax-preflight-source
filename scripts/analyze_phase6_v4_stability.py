"""Compare frozen v4 repeat stability without attributing model variance to data.

The script is deliberately post-hoc: it reads the immutable v4 snapshot and the
two source trees, then emits facts for review.  It does not rewrite any run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from ax_product.findings import _normalized_answer


ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "artifacts" / "phase6_product_demo_v4" / "SUMMARY.json"
BEFORE_DATASET = "portfolio-hidden-conflict-before"
AFTER_DATASET = "portfolio-ceiling-after"
SOURCE_ROOTS = {
    BEFORE_DATASET: ROOT / "sample_data" / "product_demo" / "hanbit_portfolio_before",
    AFTER_DATASET: ROOT / "sample_data" / "ceiling_company",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _normalized_signature(run: dict[str, Any]) -> list[str | None] | None:
    if run["payload_status"] != "ANSWERED":
        return None
    kind, value, unit = _normalized_answer(run["answer"], run["unit"])
    return [kind, value, unit]


def _task_state(runs: list[dict[str, Any]]) -> str:
    if len(runs) != 3:
        return "INCOMPLETE"
    if any(run["payload_status"] != "ANSWERED" for run in runs):
        return "BLOCKED"
    signatures = {tuple(_normalized_signature(run) or []) for run in runs}
    return "STABLE" if len(signatures) == 1 else "INCONCLUSIVE"


def _run_fact(run: dict[str, Any], source_index: dict[str, dict[str, str]]) -> dict[str, Any]:
    dataset = run["dataset"]
    source_paths = sorted({
        source_index[dataset][source_id]
        for source_id in run["source_ids"]
        if source_id in source_index[dataset]
    })
    return {
        "run_id": run["run_id"],
        "repetition": run["repetition"],
        "status": run["payload_status"],
        "answer": run["answer"],
        "unit": run["unit"],
        "normalized_signature": _normalized_signature(run),
        "evidence_verdict": run["evidence_verdict"],
        "source_ids": run["source_ids"],
        "source_paths": source_paths,
    }


def analyze(root: Path = ROOT) -> dict[str, Any]:
    # ``root`` is injectable for tests; constants describe the checked-in snapshot.
    summary_path = root / SUMMARY_PATH.relative_to(ROOT)
    runs_root = summary_path.parent / "runs"
    source_roots = {
        BEFORE_DATASET: root / SOURCE_ROOTS[BEFORE_DATASET].relative_to(ROOT),
        AFTER_DATASET: root / SOURCE_ROOTS[AFTER_DATASET].relative_to(ROOT),
    }
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    before_inventory = _inventory(source_roots[BEFORE_DATASET])
    after_inventory = _inventory(source_roots[AFTER_DATASET])
    all_paths = sorted(set(before_inventory) | set(after_inventory))
    changed_files = [
        {
            "relative_path": path,
            "change": (
                "ADDED" if path not in before_inventory
                else "REMOVED" if path not in after_inventory
                else "MODIFIED"
            ),
            "before_sha256": before_inventory.get(path),
            "after_sha256": after_inventory.get(path),
        }
        for path in all_paths
        if before_inventory.get(path) != after_inventory.get(path)
    ]

    # Build the index against the selected root rather than global constants.
    source_index: dict[str, dict[str, str]] = {BEFORE_DATASET: {}, AFTER_DATASET: {}}
    for run_root in sorted(runs_root.iterdir()):
        delivery_path = run_root / "delivery.json"
        if not delivery_path.is_file():
            continue
        dataset = json.loads(delivery_path.read_text(encoding="utf-8"))["dataset"]
        if dataset not in source_index:
            continue
        for response_path in sorted((run_root / "tool-responses").glob("*.json")):
            record = json.loads(response_path.read_text(encoding="utf-8"))
            if record.get("tool_name") != "search_documents":
                continue
            for hit in record.get("output", {}).get("results", []):
                relative_path = hit.get("metadata", {}).get("relative_path")
                if not isinstance(relative_path, str):
                    continue
                relative_path = relative_path.replace("\\", "/")
                if isinstance(hit.get("document_id"), str):
                    source_index[dataset][hit["document_id"]] = relative_path
                for table in hit.get("tables", []):
                    if isinstance(table.get("table_id"), str):
                        source_index[dataset][table["table_id"]] = relative_path

    task_ids = sorted({run["task_id"] for run in summary["runs"]})
    tasks = []
    changed_paths = {item["relative_path"] for item in changed_files}
    for task_id in task_ids:
        by_dataset = {}
        for dataset in (BEFORE_DATASET, AFTER_DATASET):
            selected = sorted(
                (
                    run for run in summary["runs"]
                    if run["task_id"] == task_id and run["dataset"] == dataset
                ),
                key=lambda item: item["repetition"],
            )
            facts = [_run_fact(run, source_index) for run in selected]
            by_dataset[dataset] = {"state": _task_state(selected), "runs": facts}
        cited_paths = sorted({
            path
            for dataset_facts in by_dataset.values()
            for run in dataset_facts["runs"]
            for path in run["source_paths"]
        })
        changed_citations = sorted(set(cited_paths) & changed_paths)
        before_state = by_dataset[BEFORE_DATASET]["state"]
        after_state = by_dataset[AFTER_DATASET]["state"]
        lost_stability = before_state == "STABLE" and after_state != "STABLE"
        tasks.append({
            "task_id": task_id,
            "before": by_dataset[BEFORE_DATASET],
            "after": by_dataset[AFTER_DATASET],
            "lost_stability": lost_stability,
            "cited_paths": cited_paths,
            "changed_cited_paths": changed_citations,
            "attribution": (
                "DATA_CAUSE_NOT_ESTABLISHED"
                if lost_stability and not changed_citations
                else "DATA_CHANGE_POSSIBLE" if lost_stability else "NOT_APPLICABLE"
            ),
        })

    lost = [item for item in tasks if item["lost_stability"]]
    return {
        "schema_version": "ax-phase6-v4-stability-review-v1",
        "snapshot": str(summary_path.relative_to(root)).replace("\\", "/"),
        "before_file_count": len(before_inventory),
        "after_file_count": len(after_inventory),
        "changed_files": changed_files,
        "lost_stability_task_count": len(lost),
        "lost_stability_task_ids": [item["task_id"] for item in lost],
        "all_lost_tasks_exclude_changed_file_from_citations": all(
            not item["changed_cited_paths"] for item in lost
        ),
        "tasks": tasks,
        "interpretation_guardrail": (
            "DATA_CAUSE_NOT_ESTABLISHED means the frozen observations do not justify "
            "attributing the change to source documents; it does not prove a model-only cause."
        ),
    }


def _write_markdown(result: dict[str, Any], path: Path) -> None:
    lines = [
        "# Phase 6 v4 stability facts",
        "",
        "This file is generated from the immutable v4 snapshot and both source trees.",
        "",
        f"- Before files: {result['before_file_count']}",
        f"- After files: {result['after_file_count']}",
        f"- Changed files: {len(result['changed_files'])}",
        f"- Tasks that lost frozen-contract stability: {result['lost_stability_task_count']}",
        "",
        "| Task | Before | After | Changed cited path | Attribution |",
        "|---|---|---|---|---|",
    ]
    for item in result["tasks"]:
        if not item["lost_stability"]:
            continue
        lines.append(
            f"| `{item['task_id']}` | {item['before']['state']} | {item['after']['state']} | "
            f"{', '.join(item['changed_cited_paths']) or 'none'} | {item['attribution']} |"
        )
    lines.extend(["", f"> {result['interpretation_guardrail']}", ""])
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts" / "posthoc_phase6_v4_stability",
    )
    args = parser.parse_args()
    result = analyze()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "ANALYSIS.json"
    md_path = args.output_dir / "FACTS.md"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_markdown(result, md_path)
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
