"""Compare Evidence Checker v1 with the already-published 32-run v5 manual audit.

The checker receives only each approved delivered JSON (adapted to the Phase 4
envelope) and structured responses decoded from that run's stream.  The manual
audit trace is loaded only after checking to label the comparison row.  No source
file, manifest expected answer, raw_response.txt, or evaluation answer is passed
to the checker.  This is a post hoc compatibility comparison, not a new Agent
metric and not an update to official v5 results.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from ax_product.evidence import ToolResponseRecord, check_evidence
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from scripts.review_v5_evidence import tool_calls


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "artifacts/heldout_ax-exp-v5"
MANUAL = ROOT / "artifacts/posthoc_ax-exp-v5/EVIDENCE_AUDIT_TRACE.json"
OUTPUT_DIR = ROOT / "artifacts/phase5_evidence_checker_v1"
JSON_OUTPUT = OUTPUT_DIR / "V5_MANUAL_COMPARISON.json"
MD_OUTPUT = OUTPUT_DIR / "V5_MANUAL_COMPARISON.md"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_sha(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def adapted_delivery(row: dict, legacy: dict) -> DeliveryEnvelope:
    status = "ABSTAINED" if legacy["abstain"] else "ANSWERED"
    payload = SubmitAnswerInput(
        status=status,
        answer=None if status == "ABSTAINED" else legacy["final_answer"],
        unit=None if status == "ABSTAINED" else legacy["unit"],
        explanation=legacy["explanation"],
        source_ids=legacy["source_ids"],
        abstention_reason="NOT_FOUND" if status == "ABSTAINED" else None,
    )
    return DeliveryEnvelope(
        delivery_status="DELIVERED",
        run_id=f"{row['task_id']}-r{row['repetition']}",
        dataset="v5-posthoc-comparison", task_id=row["task_id"], model="claude-sonnet-5",
        payload=payload, source_link_status="NOT_CHECKED",
    )


def records_for(delivery: DeliveryEnvelope, run_path: Path) -> list[ToolResponseRecord]:
    records = []
    sequence = 0
    for call in tool_calls(run_path):
        if call["errors"]:
            continue
        for output in call["outputs"]:
            sequence += 1
            records.append(ToolResponseRecord(
                run_id=delivery.run_id, sequence=sequence, tool_name=call["tool"],
                output=output, output_sha256=canonical_sha(output),
            ))
    return records


def write_if_same_or_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    manual = load(MANUAL)
    rows = []
    for manual_row in manual["run_reviews"]:
        run_path = ROOT / manual_row["run_path"]
        legacy = load(run_path / "delivered.json")
        delivery = adapted_delivery(manual_row, legacy)
        checked = check_evidence(delivery, records_for(delivery, run_path))
        manual_verdict = manual_row["posthoc_verdict"]
        expected = (
            "UNCONFIRMED"
            if manual_verdict == "SUPPORTED_SOURCE_ID_MISSING"
            else "CONFIRMED"
        )
        actual = (
            "CONFIRMED"
            if checked.verdict in ("DIRECT_MATCH", "DERIVABLE")
            else checked.verdict
        )
        agreement = actual == expected
        reason = ""
        if not agreement and checked.verdict == "PARTIAL_SUPPORT":
            reason = (
                "Manual audit verified a rate/division; checker v1 found the answer value "
                "but cannot verify the required unit relationship or division."
            )
        elif not agreement and checked.verdict == "UNCONFIRMED":
            reason = (
                "Manual audit derived a rate/division, but checker v1 excludes division and "
                "unit conversion; other unrelated numeric cells no longer create partial support."
            )
        elif agreement and expected == "UNCONFIRMED":
            reason = "Manual audit found content support, but the delivery cited no source ID; checker does not use uncited responses."
        rows.append({
            "task_id": manual_row["task_id"], "repetition": manual_row["repetition"],
            "manual_verdict": manual_verdict, "checker_verdict": checked.verdict,
            "comparison_expectation": expected, "agreement": agreement, "note": reason,
        })
    counts = Counter(row["checker_verdict"] for row in rows)
    mismatches = [row for row in rows if not row["agreement"]]
    payload = {
        "schema_version": "ax-evidence-check-v1-v5-manual-comparison-v1",
        "scope": "posthoc comparison only; not a new Agent performance metric",
        "official_v5_results_modified": False,
        "checker_inputs": ["approved delivered.json", "same-run cited structured tool responses"],
        "checker_excluded_inputs": [
            "raw_response.txt", "assistant final prose", "research expected answers",
            "research source files", "evaluation scores",
        ],
        "runs_compared": len(rows), "agreements": sum(row["agreement"] for row in rows),
        "mismatches": len(mismatches), "by_checker_verdict": dict(sorted(counts.items())),
        "limitations": [
            "The 32 records are two repeats of 16 tasks over four short files, not 32 independent tasks.",
            "Manual auditors allowed division/rate and unit conversion; checker v1 intentionally does not.",
            "UNCONFIRMED means not verified under the checker contract, not an incorrect answer.",
            "This retrospective v5 comparison does not establish production or Agent performance.",
        ],
        "rows": rows,
    }
    json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    md = [
        "# Evidence Checker v1 — v5 수작업 감사 32건 대조\n",
        "이 문서는 사후 호환성 대조다. 새 Agent 성능 지표가 아니며 v5 공식 결과를 수정하지 않는다. "
        "Checker에는 승인된 `delivered.json`과 같은 run의 인용된 구조화 tool 응답만 입력했다.\n",
        f"- 일치: **{payload['agreements']}/32**",
        f"- 불일치: **{payload['mismatches']}/32**",
        "- Checker 판정: " + ", ".join(f"`{key}` {value}" for key, value in sorted(counts.items())),
        "- `UNCONFIRMED`는 오답이 아니라 확인 불가다.\n",
        "| 과제 | 회차 | 수작업 감사 | Checker v1 | 대조 | 메모 |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for row in rows:
        md.append(
            f"| {row['task_id']} | {row['repetition']} | {row['manual_verdict']} | "
            f"{row['checker_verdict']} | {'일치' if row['agreement'] else '불일치'} | {row['note']} |"
        )
    md.extend([
        "\n## 한계\n",
        *[f"- {item}" for item in payload["limitations"]],
        "",
    ])
    write_if_same_or_new(JSON_OUTPUT, json_text)
    write_if_same_or_new(MD_OUTPUT, "\n".join(md))
    print(json.dumps({key: payload[key] for key in (
        "runs_compared", "agreements", "mismatches", "by_checker_verdict"
    )}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
