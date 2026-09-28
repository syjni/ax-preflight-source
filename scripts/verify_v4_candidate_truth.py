"""Independently re-read the new v4 candidate sources and check all task answers."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiment/v4/CANDIDATE_MANIFEST.json"


def verify() -> list[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tasks = manifest["tasks"]
    sources = {
        "ratio": ROOT / "experiment/v4/heldout/온담물류/01_품질/지역별_검수_2027.csv",
        "threshold": ROOT / "experiment/v4/heldout/온담물류/02_운영/처리_기한_기준.txt",
        "set": ROOT / "experiment/v4/heldout/온담물류/02_운영/접수_필수_항목.txt",
        "exact_or_abstain": ROOT / "experiment/v4/heldout/온담물류/03_담당/업무_책임팀_2027.txt",
    }
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with sources["ratio"].open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            sums[row["region"]][0] += int(row["defective_qty"])
            sums[row["region"]][1] += int(row["inspected_qty"])
    threshold_text = sources["threshold"].read_text(encoding="utf-8")
    set_text = sources["set"].read_text(encoding="utf-8")
    exact_text = sources["exact_or_abstain"].read_text(encoding="utf-8")
    errors: list[str] = []
    for task in tasks:
        identifier = task["task_id"]
        question = task["question"]
        stratum = task["stratum"]
        if task["required_sources"] != [sources[stratum].relative_to(ROOT).as_posix()]:
            errors.append(f"{identifier}: wrong source")
            continue
        if stratum == "ratio":
            match = re.search(r"1분기 (.+?) 지역", question)
            if not match or match.group(1) not in sums:
                errors.append(f"{identifier}: unknown region")
                continue
            numerator, denominator = sums[match.group(1)]
            if denominator == 0 or abs(Decimal(task["expected_answer"]) - Decimal(numerator) / denominator) > Decimal("1e-25"):
                errors.append(f"{identifier}: rate truth mismatch")
        elif stratum == "threshold":
            match = re.search(r"2027년 (.+?) 건은", question)
            if not match:
                errors.append(f"{identifier}: missing threshold topic")
                continue
            source_match = re.search(re.escape(match.group(1)) + r" 건은 접수 후 (\d+)영업일을 초과", threshold_text)
            if not source_match or task["expected_answer"] != int(source_match.group(1)):
                errors.append(f"{identifier}: threshold truth mismatch")
        elif stratum == "set":
            match = re.search(r"2027년 (.+?) 접수 때", question)
            if not match:
                errors.append(f"{identifier}: missing set topic")
                continue
            source_match = re.search(re.escape(match.group(1)) + r" 접수: (.+?)[을를] 모두 확인", set_text)
            if not source_match:
                errors.append(f"{identifier}: set source missing")
                continue
            expected = [item.strip() for item in source_match.group(1).split(",")]
            if expected != task["expected_answer"]:
                errors.append(f"{identifier}: set truth mismatch")
        else:
            subject = question.removesuffix("의 책임팀은 어디인가요?")
            if subject == question:
                errors.append(f"{identifier}: unexpected exact question")
                continue
            positive = re.search(re.escape(subject) + r"의 책임팀은 (.+?)입니다", exact_text)
            if task["expects_abstention"]:
                if positive or subject not in exact_text or "정보가 없습니다" not in exact_text:
                    errors.append(f"{identifier}: abstention truth mismatch")
            elif not positive or positive.group(1) != task["expected_answer"]:
                errors.append(f"{identifier}: exact truth mismatch")
    return errors


def main() -> int:
    errors = verify()
    print(json.dumps({"passed": not errors, "tasks_checked": 16, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
