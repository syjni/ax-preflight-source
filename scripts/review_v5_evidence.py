"""Post hoc, read-only evidence trace for all 32 official v5 responses.

The source facts are recalculated from the frozen corpus, not copied from the
manifest's expected answers. This does not update official scores or runs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

from scripts.v4_contract import gate_response, strict_output


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiment/frozen/ax-exp-v5-manifest.json"
SCAN = ROOT / "experiment/v5/candidate_scan_report.json"
RUNS = ROOT / "artifacts/heldout_ax-exp-v5"
OUTPUT = ROOT / "artifacts/posthoc_ax-exp-v5/EVIDENCE_AUDIT_TRACE.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def has_number(text: str, value: int) -> bool:
    return re.search(rf"(?<!\d){value}(?!\d)", text) is not None


def topic_for(task: dict) -> str:
    question = task["question"]
    if task["stratum"] == "threshold":
        match = re.search(r"2028년 (.+?)[은는] 접수 후", question)
    elif task["stratum"] == "set":
        match = re.search(r"2028년 (.+?)에 필요한", question)
    else:
        match = None
    if task["stratum"] == "exact_or_abstain":
        return question.removesuffix("의 승인팀은 어디인가요?")
    if match is None:
        raise ValueError(f"cannot identify topic: {task['task_id']}")
    return match.group(1)


def tool_calls(path: Path) -> list[dict]:
    calls = []
    for line_number, line in enumerate((path / "stream.jsonl").read_text(encoding="utf-8").splitlines(), 1):
        event = json.loads(line)
        update = event.get("data", {}).get("update", {})
        if update.get("sessionUpdate") != "tool_call_update" or update.get("status") != "completed":
            continue
        tool = update.get("title", "").split("/")[-1]
        outputs = []
        errors = []
        for item in update.get("rawOutput", {}).get("items", []):
            value = item.get("Json", {})
            if value.get("isError") is not False:
                errors.append("tool output marked error")
            for block in value.get("content", []):
                if block.get("type") == "text":
                    try:
                        outputs.append(json.loads(block["text"]))
                    except json.JSONDecodeError:
                        errors.append("tool output text is not JSON")
        if not outputs:
            errors.append("completed tool has no decoded output")
        calls.append({"tool": tool, "input": update.get("rawInput", {}),
                      "outputs": outputs, "errors": errors, "stream_line": line_number})
    return calls


def evidence_for(task: dict, delivered: dict, calls: list[dict], source_path: Path,
                 expected_id: str) -> tuple[dict, list[str]]:
    issues = []
    source_text = source_path.read_text(encoding="utf-8-sig")
    explanation = delivered["explanation"]
    tool_ids = set()
    matching_evidence = []
    result = {}

    if task["stratum"] == "ratio":
        match = re.search(r"2분기 (.+?) 채널", task["question"])
        if match is None:
            raise ValueError(f"missing channel in {task['task_id']}")
        channel = match.group(1)
        with source_path.open(encoding="utf-8-sig", newline="") as stream:
            rows = [row for row in csv.DictReader(stream)
                    if row["channel"] == channel and "2028-04-01" <= row["review_date"] <= "2028-06-30"]
        numerator = sum(int(row["approved_returns"]) for row in rows)
        denominator = sum(int(row["reviewed_returns"]) for row in rows)
        unit = delivered["unit"]
        scale = {"ratio": Decimal(1), "percent": Decimal("0.01")}.get(unit)
        answer_matches = (scale is not None and isinstance(delivered["final_answer"], (int, float))
                          and not isinstance(delivered["final_answer"], bool)
                          and abs(Decimal(str(delivered["final_answer"])) * scale
                                  - Decimal(numerator) / Decimal(denominator)) <= Decimal("0.00005"))
        explanation_matches = (channel in explanation and has_number(explanation, numerator)
                               and has_number(explanation, denominator))
        for call in calls:
            if call["tool"] != "query_table":
                continue
            arg = call["input"]
            filters = {(f.get("field"), f.get("op"), f.get("value")) for f in arg.get("filters", [])}
            expected_filters = {("channel", "eq", channel),
                                ("review_date", "gte", "2028-04-01"),
                                ("review_date", "lte", "2028-06-30")}
            if arg.get("table_id") != expected_id or filters != expected_filters:
                issues.append(f"query_table line {call['stream_line']}: wrong table or filters")
            for output in call["outputs"]:
                tool_ids.update(output.get("source_ids", []))
                if output.get("table_id") != expected_id or output.get("truncated") is not False:
                    issues.append(f"query_table line {call['stream_line']}: wrong table or truncated")
                    continue
                if output.get("source_rows_matched") != len(rows):
                    issues.append(f"query_table line {call['stream_line']}: wrong matched row count")
                aggregation = arg.get("aggregation")
                returned = output.get("rows", [])
                if aggregation is None:
                    if returned == rows and output.get("rows_returned") == len(rows):
                        matching_evidence.append(f"query_table:{call['stream_line']}:exact_rows")
                    else:
                        issues.append(f"query_table line {call['stream_line']}: rows differ from CSV")
                elif aggregation.get("op") == "sum":
                    field = aggregation.get("field")
                    alias = aggregation.get("alias", "sum_" + str(field))
                    expected = {"approved_returns": numerator,
                                "reviewed_returns": denominator}.get(field)
                    if expected is None or returned != [{alias: expected}]:
                        issues.append(f"query_table line {call['stream_line']}: aggregate differs from CSV")
                elif aggregation.get("op") == "rate":
                    expected = Decimal(numerator) / Decimal(denominator)
                    if (aggregation.get("numerator_field") != "approved_returns"
                            or aggregation.get("denominator_field") != "reviewed_returns"
                            or len(returned) != 1 or "rate" not in returned[0]
                            or abs(Decimal(str(returned[0]["rate"])) - expected) > Decimal("1e-9")):
                        issues.append(f"query_table line {call['stream_line']}: rate differs from CSV")
                else:
                    issues.append(f"query_table line {call['stream_line']}: unexpected aggregation")
        result = {"channel": channel, "source_row_ids": [row["review_id"] for row in rows],
                  "approved_total": numerator, "reviewed_total": denominator,
                  "canonical_ratio": str(Decimal(numerator) / Decimal(denominator))}
    else:
        topic = topic_for(task)
        matching_lines = [line for line in source_text.splitlines() if topic in line]
        if len(matching_lines) != 1:
            raise ValueError(f"expected one source line for {task['task_id']}, got {len(matching_lines)}")
        source_line = matching_lines[0]
        if task["stratum"] == "threshold":
            match = re.search(r"접수 후 (\d+)시간을 초과", source_line)
            if match is None:
                raise ValueError(f"no threshold in source for {task['task_id']}")
            threshold = int(match.group(1))
            answer_matches = (delivered["final_answer"] == threshold
                              and delivered["unit"] == "hours_threshold" and not delivered["abstain"])
            explanation_matches = (topic in explanation and has_number(explanation, threshold)
                                   and "초과" in explanation)
            result = {"topic": topic, "source_line": source_line, "threshold_hours": threshold}
        elif task["stratum"] == "set":
            value_text = source_line.split(":", 1)[1].split(" 모두 확인한다", 1)[0]
            value_text = re.sub(r"[을를]$", "", value_text)
            items = [item.strip() for item in value_text.split(",")]
            answer_matches = (delivered["final_answer"] == items and delivered["unit"] is None
                              and not delivered["abstain"])
            explanation_matches = topic in explanation and all(item in explanation for item in items)
            result = {"topic": topic, "source_line": source_line, "required_items": items}
        else:
            negative = "승인팀을 정하지 않았다" in source_line
            if negative:
                answer_matches = (delivered["abstain"] is True and delivered["final_answer"] is None
                                  and delivered["unit"] is None)
                explanation_matches = (topic in explanation and "정하지 않았다" in explanation)
                result = {"topic": topic, "source_line": source_line, "source_has_no_approver": True}
            else:
                match = re.search(r"승인팀은 (.+?)이다", source_line)
                if match is None:
                    raise ValueError(f"no approver in source for {task['task_id']}")
                team = match.group(1)
                answer_matches = (delivered["final_answer"] == team and delivered["unit"] is None
                                  and not delivered["abstain"])
                explanation_matches = topic in explanation and team in explanation
                result = {"topic": topic, "source_line": source_line, "approver": team}
        for call in calls:
            for output in call["outputs"]:
                if call["tool"] == "search_documents":
                    for hit in output.get("results", []):
                        tool_ids.add(hit.get("document_id"))
                        if hit.get("document_id") == expected_id and source_line in hit.get("snippet", ""):
                            matching_evidence.append(f"search_documents:{call['stream_line']}:source_line")
                elif call["tool"] == "read_document":
                    tool_ids.add(output.get("document_id"))
                    if output.get("document_id") == expected_id and source_line in output.get("content", ""):
                        matching_evidence.append(f"read_document:{call['stream_line']}:source_line")

    for call in calls:
        issues.extend(f"{call['tool']} line {call['stream_line']}: {error}" for error in call["errors"])
    result.update({"answer_and_unit_match_source": bool(answer_matches),
                   "explanation_key_facts_present": bool(explanation_matches),
                   "tool_evidence_refs": matching_evidence,
                   "expected_source_id_seen_in_tool_output": expected_id in tool_ids})
    if not answer_matches:
        issues.append("answer or unit differs from source")
    if not explanation_matches:
        issues.append("explanation lacks key source facts")
    if not matching_evidence:
        issues.append("no relevant source line or CSV rows in tool response")
    return result, issues


def main() -> int:
    manifest = load(MANIFEST)
    audit = load(RUNS / "AUDIT.json")
    if audit.get("passed") is not True or audit.get("valid_slots") != 32 or audit.get("manifest_sha256") != sha(MANIFEST):
        raise ValueError("official v5 audit/manifest mismatch")
    scan = load(SCAN)
    file_by_path = {"experiment/v5/heldout/해솔제조/" + item["relative_path"]: item
                    for item in scan["files"]}
    table_by_file = {item["file_id"]: item["table_id"] for item in scan["tables"]}
    rows = []
    hard_issues = []
    for task in manifest["tasks"]:
        source_label = task["required_sources"][0]
        source_path = ROOT / source_label
        source_record = file_by_path[source_label]
        if sha(source_path) != source_record["sha256"] or sha(source_path) != next(
                item["sha256"] for item in manifest["dataset_files"] if item["path"] == source_label):
            raise ValueError(f"source hash mismatch: {source_label}")
        expected_id = (table_by_file[source_record["file_id"]]
                       if task["stratum"] == "ratio" else source_record["file_id"])
        for repetition in (1, 2):
            path = RUNS / task["task_id"] / f"r{repetition}"
            raw = (path / "raw_response.txt").read_text(encoding="utf-8")
            delivered_text = (path / "delivered.json").read_text(encoding="utf-8")
            delivered = json.loads(delivered_text)
            evaluation = load(path / "evaluation.json")
            calls = tool_calls(path)
            log = [json.loads(line) for line in (path / "mcp-invocations-live.jsonl").read_text(encoding="utf-8").splitlines()
                   if line.strip()]
            issues = []
            if strict_output(delivered_text) is None or gate_response(raw).delivered_json != delivered_text:
                issues.append("saved delivery differs from gate or schema")
            if evaluation.get("delivered_json") != delivered_text:
                issues.append("evaluation receipt differs from delivery")
            if len(calls) != len(log) or any(entry.get("outcome") != "success" for entry in log):
                issues.append("MCP call count or outcome differs")
            source_facts, evidence_issues = evidence_for(task, delivered, calls, source_path, expected_id)
            issues.extend(evidence_issues)
            source_ids = delivered["source_ids"]
            cited = source_ids == [expected_id] and source_facts["expected_source_id_seen_in_tool_output"]
            if source_ids and not cited:
                issues.append("source_ids do not point to the observed required source")
            verdict = ("SUPPORTED_AND_CITED" if not issues and cited else
                       "SUPPORTED_SOURCE_ID_MISSING" if not issues and source_ids == [] else
                       "INSUFFICIENT_OR_CONFLICTING")
            findings = (["delivered source_ids empty although tool returned the supporting source"]
                        if verdict == "SUPPORTED_SOURCE_ID_MISSING" else [])
            row = {"task_id": task["task_id"], "repetition": repetition,
                   "stratum": task["stratum"], "run_path": path.relative_to(ROOT).as_posix(),
                   "source_path": source_label, "source_sha256": sha(source_path),
                   "expected_source_id_from_scan": expected_id,
                   "delivered_source_ids": source_ids,
                   "delivered_answer": delivered["final_answer"],
                   "delivered_unit": delivered["unit"], "delivered_abstain": delivered["abstain"],
                   "tool_counts": dict(Counter(call["tool"] for call in calls)),
                   "source_facts": source_facts, "findings": findings,
                   "issues": issues, "posthoc_verdict": verdict}
            rows.append(row)
            if verdict == "INSUFFICIENT_OR_CONFLICTING":
                hard_issues.append(f"{task['task_id']} r{repetition}: {issues}")
    if len(rows) != 32:
        hard_issues.append(f"expected 32 reviews, got {len(rows)}")
    summary = {"schema_version": "ax-v5-posthoc-evidence-audit-v1",
               "official_scores_unchanged": True, "runs_reviewed": len(rows),
               "by_verdict": dict(Counter(row["posthoc_verdict"] for row in rows)),
               "source_ids_present": sum(bool(row["delivered_source_ids"]) for row in rows),
               "source_ids_missing": sum(not row["delivered_source_ids"] for row in rows),
               "all_answer_unit_match_source": sum(row["source_facts"]["answer_and_unit_match_source"] for row in rows),
               "all_explanation_key_facts_present": sum(row["source_facts"]["explanation_key_facts_present"] for row in rows),
               "all_tool_evidence_present": sum(bool(row["source_facts"]["tool_evidence_refs"]) for row in rows)}
    payload = {"summary": summary, "hard_issues": hard_issues, "run_reviews": rows}
    if OUTPUT.exists():
        if load(OUTPUT) != payload:
            raise ValueError(f"existing post hoc trace differs; refusing to overwrite: {OUTPUT}")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "hard_issues": hard_issues}, ensure_ascii=False))
    return 0 if not hard_issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
