"""Independently re-read every v5 candidate source and answer before freeze."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from scripts.build_v5_candidate import EXACT, RATE, ROOT, SET, THRESHOLD, V5


def verify() -> list[str]:
    manifest = json.loads((V5 / "CANDIDATE_MANIFEST.json").read_text(encoding="utf-8"))
    sources = {"ratio": ROOT / RATE, "threshold": ROOT / THRESHOLD,
               "set": ROOT / SET, "exact_or_abstain": ROOT / EXACT}
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with sources["ratio"].open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            totals[row["channel"]][0] += int(row["approved_returns"])
            totals[row["channel"]][1] += int(row["reviewed_returns"])
    threshold_text = sources["threshold"].read_text(encoding="utf-8")
    set_text = sources["set"].read_text(encoding="utf-8")
    exact_text = sources["exact_or_abstain"].read_text(encoding="utf-8")
    errors: list[str] = []
    for task in manifest["tasks"]:
        identifier, stratum, question = task["task_id"], task["stratum"], task["question"]
        if task["required_sources"] != [sources[stratum].relative_to(ROOT).as_posix()]:
            errors.append(f"{identifier}: source inventory mismatch")
            continue
        if stratum == "ratio":
            match = re.search(r"2분기 (.+?) 채널", question)
            if not match or match.group(1) not in totals:
                errors.append(f"{identifier}: unknown channel")
                continue
            numerator, denominator = totals[match.group(1)]
            if denominator == 0 or abs(Decimal(task["expected_answer"]) - Decimal(numerator) / denominator) > Decimal("1e-25"):
                errors.append(f"{identifier}: numeric truth mismatch")
        elif stratum == "threshold":
            match = re.search(r"2028년 (.+?)[은는] 접수 후", question)
            if not match:
                errors.append(f"{identifier}: threshold topic absent")
                continue
            source_match = re.search(re.escape(match.group(1)) + r"[은는] 접수 후 (\d+)시간을 초과", threshold_text)
            if not source_match or int(source_match.group(1)) != task["expected_answer"]:
                errors.append(f"{identifier}: threshold truth mismatch")
        elif stratum == "set":
            match = re.search(r"2028년 (.+?)에 필요한", question)
            if not match:
                errors.append(f"{identifier}: set topic absent")
                continue
            source_match = re.search(re.escape(match.group(1)) + r": (.+?)[을를] 모두 확인한다", set_text)
            if not source_match:
                errors.append(f"{identifier}: set source absent")
                continue
            values = [item.strip() for item in source_match.group(1).split(",")]
            if values != task["expected_answer"]:
                errors.append(f"{identifier}: set truth mismatch")
        else:
            subject = question.removesuffix("의 승인팀은 어디인가요?")
            if subject == question:
                errors.append(f"{identifier}: exact question shape mismatch")
                continue
            positive = re.search(re.escape(subject) + r"의 승인팀은 (.+?)이다", exact_text)
            if task["expects_abstention"]:
                negative = re.search(re.escape(subject) + r"의 승인팀을 정하지 않았다", exact_text)
                if positive or not negative or task["expected_answer"] is not None:
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
