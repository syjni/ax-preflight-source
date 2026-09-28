"""Classify frozen v3 Evidence Checker gaps without modifying the snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from ax_product.evidence import ToolResponseStore
from ax_product.evidence_v2 import check_run_v2, evidence_v2_reason
from ax_product.models import DeliveryEnvelope
from ax_product.results import ResultStore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = ROOT / "artifacts" / "phase6_product_demo_v3" / "runs"
DEFAULT_OUTPUT = ROOT / "artifacts" / "posthoc_phase6_evidence_checker_v3"
FROZEN_MANIFEST = (
    ROOT / "artifacts" / "phase6_product_demo_v3" / "FROZEN_MANIFEST.v3.json"
)


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _unconfirmed_reason(delivery: DeliveryEnvelope) -> str:
    payload = delivery.payload
    if payload is None:
        return "NO_APPROVED_PAYLOAD"
    if payload.status == "ABSTAINED":
        if not payload.source_ids:
            return "UNCITED_ABSTENTION"
        return "ABSTENTION_EXPLANATION_NOT_LEXICALLY_PRESENT"
    answer = _normalize(str(payload.answer))
    if answer.startswith("없음") or "모든 " in answer:
        return "COMPARATIVE_ASSERTION_REQUIRES_PREDICATE"
    return "CROSS_LANGUAGE_OR_SEMANTIC_PARAPHRASE"


def analyze(runs_root: Path = DEFAULT_RUNS) -> dict[str, Any]:
    root = Path(runs_root).resolve()
    result_store = ResultStore(root)
    response_store = ToolResponseStore(root)
    rows: list[dict[str, Any]] = []
    for delivery_path in sorted(root.glob("portfolio-*/delivery.json")):
        stored = json.loads(
            (delivery_path.parent / "evidence-check.json").read_text(encoding="utf-8")
        )
        if stored["verdict"] != "UNCONFIRMED":
            continue
        run_id = delivery_path.parent.name
        delivery = result_store.read(run_id)
        records = response_store.read(run_id)
        current = check_run_v2(root, run_id)
        if current.verdict == "DIRECT_MATCH":
            cause = evidence_v2_reason(delivery, records) or "V1_DIRECT_MATCH"
        else:
            cause = _unconfirmed_reason(delivery)
        rows.append({
            "run_id": run_id,
            "dataset": delivery.dataset,
            "task_id": delivery.task_id,
            "payload_status": delivery.payload.status if delivery.payload else None,
            "stored_verdict": stored["verdict"],
            "current_verdict": current.verdict,
            "root_cause": cause,
        })

    current_counts = Counter(row["current_verdict"] for row in rows)
    cause_counts = Counter(row["root_cause"] for row in rows)
    manifest_sha = hashlib.sha256(FROZEN_MANIFEST.read_bytes()).hexdigest()
    return {
        "schema_version": "ax-phase6-evidence-gap-analysis-v1",
        "scope": "POSTHOC_FROZEN_V3_ANALYSIS_NOT_AGENT_PERFORMANCE_METRIC",
        "source_snapshot": "artifacts/phase6_product_demo_v3",
        "source_manifest_sha256": manifest_sha,
        "source_snapshot_modified": False,
        "stored_unconfirmed_run_count": len(rows),
        "current_verdicts_for_stored_unconfirmed": dict(sorted(current_counts.items())),
        "newly_direct_match_count": current_counts["DIRECT_MATCH"],
        "remaining_unconfirmed_count": current_counts["UNCONFIRMED"],
        "root_cause_counts": dict(sorted(cause_counts.items())),
        "rows": rows,
        "limitations": [
            "UNCONFIRMED means the checker did not verify the claim, not that the answer is incorrect.",
            "The analysis reuses frozen deliveries and same-run structured responses; it does not rerun the model.",
            "Cross-language and broader semantic entailment remain outside the deterministic checker.",
        ],
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 6 broad demo Evidence Checker 원인 분류",
        "",
        "frozen v3 파일은 수정하지 않고, 당시 `UNCONFIRMED` 19건을 현재의 결정론적 규칙으로 다시 검사했다.",
        "",
        f"- 새 `DIRECT_MATCH`: **{payload['newly_direct_match_count']} / {payload['stored_unconfirmed_run_count']}**",
        f"- 남은 `UNCONFIRMED`: **{payload['remaining_unconfirmed_count']} / {payload['stored_unconfirmed_run_count']}**",
        f"- frozen v3 수정: **{str(payload['source_snapshot_modified']).lower()}**",
        "",
        "## 원인별 집계",
        "",
    ]
    lines.extend(
        f"- `{cause}`: {count}건"
        for cause, count in payload["root_cause_counts"].items()
    )
    lines.extend([
        "",
        "## Run별 판정",
        "",
        "| Run | Dataset | Task | 현재 판정 | 원인 |",
        "| --- | --- | --- | --- | --- |",
    ])
    lines.extend(
        f"| `{row['run_id']}` | `{row['dataset']}` | `{row['task_id']}` | "
        f"`{row['current_verdict']}` | `{row['root_cause']}` |"
        for row in payload["rows"]
    )
    lines.extend(["", "`UNCONFIRMED`는 오답 판정이 아니다.", ""])
    return "\n".join(lines)


def write_analysis(payload: dict[str, Any], output_dir: Path) -> list[Path]:
    selected = Path(output_dir)
    selected.mkdir(parents=True, exist_ok=True)
    json_path = selected / "ROOT_CAUSES.json"
    markdown_path = selected / "ROOT_CAUSES.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    markdown_path.write_text(_markdown(payload), encoding="utf-8", newline="\n")
    return [json_path, markdown_path]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = analyze(args.runs_root)
    paths = write_analysis(payload, args.output_dir)
    print(json.dumps({
        "stored_unconfirmed": payload["stored_unconfirmed_run_count"],
        "newly_direct": payload["newly_direct_match_count"],
        "remaining_unconfirmed": payload["remaining_unconfirmed_count"],
        "outputs": [path.relative_to(ROOT).as_posix() for path in paths],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
