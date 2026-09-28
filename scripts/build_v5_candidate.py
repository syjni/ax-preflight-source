"""Prepare new AX v5 held-out tasks without sending them to Kiro."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V5 = ROOT / "experiment" / "v5"
CORPUS = V5 / "heldout" / "해솔제조"
RATE = "experiment/v5/heldout/해솔제조/01_고객지원/채널별_반품심사_2028.csv"
THRESHOLD = "experiment/v5/heldout/해솔제조/02_설비/설비_조치_기준.txt"
SET = "experiment/v5/heldout/해솔제조/03_관리/등록_필수_증빙.txt"
EXACT = "experiment/v5/heldout/해솔제조/04_담당/승인권한_2028.txt"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def base(identifier: str, stratum: str, category: str, question: str, source: str) -> dict:
    return {"task_id": identifier, "stratum": stratum, "category": category,
            "question": question, "required_sources": [source], "expects_abstention": False}


def tasks() -> list[dict]:
    result: list[dict] = []
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with (ROOT / RATE).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            totals[row["channel"]][0] += int(row["approved_returns"])
            totals[row["channel"]][1] += int(row["reviewed_returns"])
    for number, (channel, label) in enumerate(
        [("온라인", "ONLINE"), ("대리점", "DEALER"), ("직영", "DIRECT"), ("기업", "BUSINESS")], 1
    ):
        approved, reviewed = totals[channel]
        task = base(
            f"V5_R{number:02d}_{label}_RETURN_APPROVAL_RATE", "ratio", "operations",
            f"2028년 2분기 {channel} 채널 반품 심사에서 approved_returns 총합을 reviewed_returns 총합으로 나눈 승인률은 얼마인가요?",
            RATE)
        task["expected_answer"] = str(Decimal(approved) / Decimal(reviewed))
        task["scoring_method"] = {"type": "numeric_quantity", "accepted_units": {
            "ratio": {"scale_to_canonical": "1", "absolute_tolerance_canonical": "0.00005"},
            "percent": {"scale_to_canonical": "0.01", "absolute_tolerance_canonical": "0.00005"}}}
        result.append(task)

    thresholds = [
        ("COOLANT_PRESSURE", "냉각수 압력 경고", 2),
        ("PACKER_SENSOR", "포장기 센서 오류", 4),
        ("FILLING_LEAK", "충전라인 누출 의심", 1),
        ("SHIPPING_LABEL", "출하 라벨 인쇄 오류", 3),
    ]
    for number, (label, topic, value) in enumerate(thresholds, 1):
        particle = "은" if topic.endswith("의심") else "는"
        task = base(f"V5_T{number:02d}_{label}_NOTICE_THRESHOLD", "threshold", "knowledge",
                    f"2028년 {topic}{particle} 접수 후 몇 시간을 초과하면 당직 관리자에게 통보하나요? 최초 통보 대상 시각이 아닌 초과 기준값을 답하세요.",
                    THRESHOLD)
        task["expected_answer"] = value
        task["scoring_method"] = {"type": "numeric_quantity", "accepted_units": {
            "hours_threshold": {"scale_to_canonical": "1", "absolute_tolerance_canonical": "0"}}}
        result.append(task)

    sets = [
        ("SAFETY_INSPECTION", "정기 안전점검 등록", ["점검 일지", "설비 번호", "점검자 서명"],
         {"점검 일지": ["안전점검 일지"], "설비 번호": ["설비번호"], "점검자 서명": ["점검 담당자 서명"]}),
        ("VENDOR_VISIT", "협력사 출입 신청", ["방문 목적", "방문자 명단", "안전교육 확인"],
         {"방문 목적": [], "방문자 명단": ["방문 인원 명단"], "안전교육 확인": ["안전교육 이수 확인"]}),
        ("TEST_MATERIAL", "시험 자재 반입", ["반입 목록", "보관 위치", "책임자 승인"],
         {"반입 목록": ["반입 자재 목록"], "보관 위치": ["보관 장소"], "책임자 승인": ["담당 책임자 승인"]}),
        ("PROCESS_CHANGE", "공정 변경 신청", ["변경 사유", "영향 평가서", "시행 예정일"],
         {"변경 사유": [], "영향 평가서": ["변경 영향 평가서"], "시행 예정일": ["예정 시행일"]}),
    ]
    for number, (label, topic, expected, forms) in enumerate(sets, 1):
        task = base(f"V5_S{number:02d}_{label}_EVIDENCE", "set", "knowledge",
                    f"2028년 {topic}에 필요한 증빙 항목을 모두 답하세요.", SET)
        task["expected_answer"] = expected
        task["scoring_method"] = {"type": "set_items", "accepted_forms": forms}
        result.append(task)

    exacts = [
        ("MAINTENANCE_PLAN", "2028년 하반기 설비 예방정비 계획의 승인팀은 어디인가요?", "설비기술팀"),
        ("VENDOR_REGISTRATION", "신규 협력사 등록 심사의 승인팀은 어디인가요?", "구매관리팀"),
        ("OVERSEAS_PLANT", "2029년 해외 제2공장 착공 계획의 승인팀은 어디인가요?", None),
        ("AI_INSPECTION", "2028년 4분기 AI 검사 장비 도입의 승인팀은 어디인가요?", None),
    ]
    for number, (label, question, expected) in enumerate(exacts, 1):
        task = base(f"V5_E{number:02d}_{label}_APPROVER", "exact_or_abstain", "knowledge",
                    question, EXACT)
        task["expects_abstention"] = expected is None
        task["expected_answer"] = expected
        task["scoring_method"] = {"type": "exact_text",
                                  "accepted_forms": [] if expected is None else [expected]}
        result.append(task)
    return result


FROZEN_PATHS = [
    "scripts/v4_contract.py", "scripts/v4_scoring.py", "scripts/v4_prompt.py",
    "scripts/v4_evaluation.py", "scripts/session_prompt_validation.py",
    "scripts/stream_response_validation.py", "scripts/v5_official_runner.py",
    "scripts/v5_preflight.py", "scripts/build_v5_candidate.py",
    "scripts/verify_v5_candidate_truth.py", "scripts/validate_v5_tool_access.py",
    "scripts/validate_v5_development.py", "scripts/v5_dev_runner_probe.py",
    "scripts/freeze_v5.py", "experiment/v5/AGENT_PROMPT.txt",
    "experiment/v5/PREREGISTRATION.md", "experiment/v5/RUNBOOK.md",
    "experiment/v5/ROOT_CAUSE.md", "experiment/v5/DEV_VALIDATION.md",
    "tests/test_stream_response_validation.py", "tests/test_v5_preflight.py",
    "experiment/v5/runtime_datasets.json",
    "experiment/v5/candidate_scan_report.json", "experiment/v5/candidate_dataset_manifest.json",
]


def build() -> dict:
    files = sorted(path for path in CORPUS.rglob("*") if path.is_file())
    dataset = {"schema_version": "ax-v5-candidate-dataset-manifest-v1",
               "dataset_id": "haesol-manufacturing-2028-v5-candidate",
               "source_root": "experiment/v5/heldout/해솔제조",
               "file_count": len(files),
               "files": [{"relative_path": path.relative_to(CORPUS).as_posix(),
                          "sha256": sha(path)} for path in files]}
    write(V5 / "candidate_dataset_manifest.json", dataset)
    return {"schema_version": "ax-exp-v5-preregistration-v1",
            "experiment_id": "ax-exp-v5", "status": "DRAFT", "model": "claude-sonnet-5",
            "kiro_cli_version": "kiro-cli-chat 2.23.0",
            "backend": "AUTOMATED_FRESH_PROCESS_V2_AGGREGATE_VALIDATED",
            "runtime_profile": "v5-candidate", "repetitions": 2,
            "dataset_files": [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)}
                              for path in files],
            "frozen_files": [{"path": path, "sha256": sha(ROOT / path)} for path in FROZEN_PATHS],
            "tasks": tasks()}


def main() -> None:
    result = build()
    target = V5 / "CANDIDATE_MANIFEST.json"
    write(target, result)
    print(json.dumps({"path": str(target), "tasks": len(result["tasks"]),
                      "dataset_files": len(result["dataset_files"]),
                      "status": result["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
