"""Read-only post hoc review of v5 gate preservation and paired repeats."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from scripts.v4_contract import extract_unique_output, gate_response, strict_output
from scripts.v5_preflight import ROOT


RUNS = ROOT / "artifacts" / "heldout_ax-exp-v5"
FROZEN = ROOT / "experiment" / "frozen" / "ax-exp-v5-manifest.json"
OUTPUT = ROOT / "artifacts" / "posthoc_ax-exp-v5" / "GATE_AND_REPEAT_REVIEW.json"
FIELDS = ("final_answer", "unit", "explanation", "source_ids", "abstain")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def object_span(raw: str) -> tuple[int, int, dict]:
    decoder = json.JSONDecoder(parse_float=Decimal, parse_int=Decimal)
    matches = []
    for start, character in enumerate(raw):
        if character != "{":
            continue
        try:
            value, length = decoder.raw_decode(raw[start:])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict) and strict_output(raw[start:start + length]) is not None:
            matches.append((start, start + length, value))
    if len(matches) != 1:
        raise ValueError(f"expected one schema-valid object, got {len(matches)}")
    return matches[0]


def main() -> int:
    audit = read(RUNS / "AUDIT.json")
    if audit.get("passed") is not True or audit.get("valid_slots") != 32:
        raise ValueError("official v5 audit must pass before post hoc review")
    analysis = read(RUNS / "ANALYSIS.json")
    manifest = read(FROZEN)
    task_map = {task["task_id"]: task for task in manifest["tasks"]}
    scan = read(ROOT / "experiment" / "v5" / "candidate_scan_report.json")
    file_sources = {
        record["file_id"]: "experiment/v5/heldout/해솔제조/" + record["relative_path"]
        for record in scan["files"]
    }
    source_map = dict(file_sources)
    source_map.update({table["table_id"]: file_sources[table["file_id"]]
                       for table in scan["tables"]})
    records = []
    problems = []
    for task in manifest["tasks"]:
        task_id = task["task_id"]
        for repetition in (1, 2):
            path = RUNS / task_id / f"r{repetition}"
            raw = (path / "raw_response.txt").read_text(encoding="utf-8")
            delivered_text = (path / "delivered.json").read_text(encoding="utf-8")
            evaluation = read(path / "evaluation.json")
            gate = gate_response(raw)
            if gate.delivered_json != delivered_text:
                problems.append(f"{task_id} r{repetition}: gate replay differs from saved delivered JSON")
            start, end, raw_object = object_span(raw)
            delivered = json.loads(delivered_text, parse_float=Decimal, parse_int=Decimal)
            fields_preserved = {field: raw_object[field] == delivered[field] for field in FIELDS}
            if not all(fields_preserved.values()):
                problems.append(f"{task_id} r{repetition}: one or more semantic fields changed")
            if extract_unique_output(raw) is None:
                problems.append(f"{task_id} r{repetition}: no unique raw object")
            prefix, suffix = raw[:start], raw[end:]
            source_ids = delivered["source_ids"]
            mapped = [source_map.get(identifier) for identifier in source_ids]
            record = {
                "task_id": task_id, "repetition": repetition, "stratum": task["stratum"],
                "native_strict": evaluation["native_strict"],
                "gate_decision": evaluation["gate_decision"],
                "fields_preserved": fields_preserved,
                "raw_answer": raw_object["final_answer"],
                "delivered_answer": delivered["final_answer"],
                "unit": delivered["unit"], "abstain": delivered["abstain"],
                "source_ids": source_ids,
                "source_paths": mapped,
                "source_paths_match_required": (set(mapped) == set(task["required_sources"])),
                "prefix_length": len(prefix), "suffix_length": len(suffix),
                "prefix_excerpt": prefix[:180], "suffix_excerpt": suffix[:180],
                "has_markdown_fence": "```" in prefix + suffix,
                "has_nonwhitespace_prefix": bool(prefix.strip()),
                "has_nonwhitespace_suffix": bool(suffix.strip()),
            }
            if not evaluation["native_strict"] and evaluation["gate_decision"] != "NORMALIZED_WRAPPER":
                problems.append(f"{task_id} r{repetition}: non-strict case was not normalized")
            records.append(record)
    # Decimal values are retained for exact comparisons above; convert for JSON output.
    def serializable(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, list):
            return [serializable(item) for item in value]
        return value

    for record in records:
        record["raw_answer"] = serializable(record["raw_answer"])
        record["delivered_answer"] = serializable(record["delivered_answer"])
    non_strict = [record for record in records if not record["native_strict"]]
    pairs = []
    for task in manifest["tasks"]:
        first, second = [record for record in records if record["task_id"] == task["task_id"]]
        answer_equal = first["delivered_answer"] == second["delivered_answer"]
        if task["stratum"] == "set":
            concept_equal = (set(first["delivered_answer"]) == set(second["delivered_answer"]))
        else:
            concept_equal = answer_equal
        pairs.append({"task_id": task["task_id"], "stratum": task["stratum"],
                      "answer_exact_equal": answer_equal,
                      "answer_set_equal": concept_equal,
                      "unit_equal": first["unit"] == second["unit"],
                      "source_ids_equal": first["source_ids"] == second["source_ids"],
                      "abstain_equal": first["abstain"] == second["abstain"],
                      "native_strict_equal": first["native_strict"] == second["native_strict"],
                      "r1_answer": first["delivered_answer"], "r1_unit": first["unit"],
                      "r2_answer": second["delivered_answer"], "r2_unit": second["unit"]})
    summary = {
        "schema_version": "ax-v5-posthoc-gate-repeat-review-v1",
        "official_scores_unchanged": True,
        "run_count": len(records), "non_strict_count": len(non_strict),
        "non_strict_all_fields_preserved": sum(all(r["fields_preserved"].values()) for r in non_strict),
        "non_strict_fenced": sum(r["has_markdown_fence"] for r in non_strict),
        "non_strict_prefix": sum(r["has_nonwhitespace_prefix"] for r in non_strict),
        "non_strict_suffix": sum(r["has_nonwhitespace_suffix"] for r in non_strict),
        "source_paths_match_required_count": sum(r["source_paths_match_required"] for r in records),
        "pairs": len(pairs),
        "pair_exact_answer_equal": sum(p["answer_exact_equal"] for p in pairs),
        "pair_answer_set_equal": sum(p["answer_set_equal"] for p in pairs),
        "pair_unit_equal": sum(p["unit_equal"] for p in pairs),
        "pair_source_ids_equal": sum(p["source_ids_equal"] for p in pairs),
        "pair_abstain_equal": sum(p["abstain_equal"] for p in pairs),
        "pair_native_strict_equal": sum(p["native_strict_equal"] for p in pairs),
    }
    if summary["run_count"] != 32 or summary["non_strict_count"] != 17:
        problems.append("run or non-strict count differs from official analysis")
    if summary["non_strict_all_fields_preserved"] != summary["non_strict_count"]:
        problems.append("a normalized response changed semantic fields")
    if analysis["overall"]["native_strict"] != 32 - summary["non_strict_count"]:
        problems.append("official native count differs")
    payload = {"summary": summary, "problems": problems,
               "non_strict_records": non_strict, "paired_records": pairs}
    if problems:
        print(json.dumps({"summary": summary, "problems": problems}, ensure_ascii=False))
        return 1
    if OUTPUT.exists():
        if read(OUTPUT) != payload:
            raise ValueError(f"existing post hoc review differs; refusing to overwrite: {OUTPUT}")
        print(json.dumps({"summary": summary, "problems": problems,
                          "existing_review_verified": True}, ensure_ascii=False))
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "problems": problems}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
