"""Build the unexecuted v4 candidate task and data inventory.

This is preparation only. It does not freeze v4 or run a model.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "experiment" / "v4"
CORPUS = V4 / "heldout" / "온담물류"
RATE_SOURCE = "experiment/v4/heldout/온담물류/01_품질/지역별_검수_2027.csv"
THRESHOLD_SOURCE = "experiment/v4/heldout/온담물류/02_운영/처리_기한_기준.txt"
SET_SOURCE = "experiment/v4/heldout/온담물류/02_운영/접수_필수_항목.txt"
EXACT_SOURCE = "experiment/v4/heldout/온담물류/03_담당/업무_책임팀_2027.txt"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _base(identifier: str, stratum: str, category: str, question: str, source: str) -> dict:
    return {
        "task_id": identifier,
        "stratum": stratum,
        "category": category,
        "question": question,
        "required_sources": [source],
        "expects_abstention": False,
    }


def _tasks() -> list[dict]:
    tasks: list[dict] = []
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with (ROOT / RATE_SOURCE).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            sums[row["region"]][0] += int(row["defective_qty"])
            sums[row["region"]][1] += int(row["inspected_qty"])
    for number, (region, label) in enumerate(
        [("북부", "NORTH"), ("남부", "SOUTH"), ("서부", "WEST"), ("동부", "EAST")], 1
    ):
        numerator, denominator = sums[region]
        task = _base(
            f"V4_R{number:02d}_{label}_DEFECT_RATE", "ratio", "operations",
            f"2027년 1분기 {region} 지역 검수 기록에서 defective_qty 합계를 inspected_qty 합계로 나눈 불량률은 얼마인가요?",
            RATE_SOURCE,
        )
        task["expected_answer"] = str(Decimal(numerator) / Decimal(denominator))
        task["scoring_method"] = {
            "type": "numeric_quantity",
            "accepted_units": {
                "ratio": {"scale_to_canonical": "1", "absolute_tolerance_canonical": "0.00005"},
                "percent": {"scale_to_canonical": "0.01", "absolute_tolerance_canonical": "0.00005"},
            },
        }
        tasks.append(task)

    for number, (topic, threshold, label) in enumerate(
        [("상품 재검수", 2, "REINSPECTION"), ("정산 이의", 5, "SETTLEMENT"),
         ("긴급 배송 조정", 1, "URGENT_DELIVERY"), ("계약 검토 회신", 4, "CONTRACT_REPLY")], 1
    ):
        task = _base(
            f"V4_T{number:02d}_{label}_THRESHOLD", "threshold", "knowledge",
            f"2027년 {topic} 건은 접수 후 몇 영업일을 초과하면 에스컬레이션하나요? 최초 대상 일차가 아닌 초과 기준값을 답하세요.",
            THRESHOLD_SOURCE,
        )
        task["expected_answer"] = threshold
        task["scoring_method"] = {
            "type": "numeric_quantity",
            "accepted_units": {
                "business_days_threshold": {
                    "scale_to_canonical": "1", "absolute_tolerance_canonical": "0"
                },
            },
        }
        tasks.append(task)

    set_specs = [
        ("WARRANTY_REPAIR", "보증 수리", ["제품 식별번호", "구매 증빙", "증상 설명"],
         {"제품 식별번호": ["제품 ID"], "구매 증빙": ["구매 증빙 서류"], "증상 설명": ["고장 증상 설명"]}),
        ("CORPORATE_ACCOUNT", "법인 고객 신규 계정", ["사업자등록증", "담당자 연락처", "세금계산서 수신 이메일"],
         {"사업자등록증": ["사업자 등록증"], "담당자 연락처": [], "세금계산서 수신 이메일": ["세금계산서 받을 이메일"]}),
        ("BULK_DELIVERY", "대량 배송 변경", ["원주문 번호", "변경 배송지", "요청자 승인"],
         {"원주문 번호": ["기존 주문 번호"], "변경 배송지": ["변경할 배송지"], "요청자 승인": ["요청자의 승인"]}),
        ("INBOUND_DISCREPANCY", "입고 오차 신고", ["납품서", "실측 수량", "로트 번호"],
         {"납품서": [], "실측 수량": ["실제로 측정한 수량"], "로트 번호": ["로트번호"]}),
    ]
    for number, (label, topic, expected, aliases) in enumerate(set_specs, 1):
        task = _base(
            f"V4_S{number:02d}_{label}_ITEMS", "set", "knowledge",
            f"2027년 {topic} 접수 때 확인해야 하는 필수 항목을 모두 답하세요.", SET_SOURCE,
        )
        task["expected_answer"] = expected
        task["scoring_method"] = {"type": "set_items", "accepted_forms": aliases}
        tasks.append(task)

    exact_specs = [
        ("Q2_STOCKTAKE", "2027년 2분기 창고 재고 조사의 책임팀은 어디인가요?", "운영관리팀"),
        ("EXPORT_DOCS", "해외 발송 서류 검토의 책임팀은 어디인가요?", "통관지원팀"),
        ("FUTURE_MOVE", "2028년 창고 이전 프로젝트의 책임팀은 어디인가요?", None),
        ("Q4_TRAINING", "2027년 4분기 신규 서비스 교육의 책임팀은 어디인가요?", None),
    ]
    for number, (label, question, expected) in enumerate(exact_specs, 1):
        task = _base(f"V4_E{number:02d}_{label}_OWNER", "exact_or_abstain", "knowledge",
                     question, EXACT_SOURCE)
        task["expects_abstention"] = expected is None
        task["expected_answer"] = expected
        task["scoring_method"] = {"type": "exact_text", "accepted_forms": [] if expected is None else [expected]}
        tasks.append(task)
    return tasks


def build() -> dict:
    data_files = sorted(path for path in CORPUS.rglob("*") if path.is_file())
    dataset_files = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha(path)} for path in data_files
    ]
    dataset_manifest = {
        "schema_version": "ax-v4-candidate-dataset-manifest-v1",
        "dataset_id": "ondam-logistics-2027-v4-candidate",
        "source_root": "experiment/v4/heldout/온담물류",
        "file_count": len(data_files),
        "files": [
            {"relative_path": path.relative_to(CORPUS).as_posix(), "sha256": _sha(path)}
            for path in data_files
        ],
    }
    _write(V4 / "candidate_dataset_manifest.json", dataset_manifest)
    frozen_paths = [
        "scripts/v4_contract.py", "scripts/v4_scoring.py", "scripts/v4_prompt.py",
        "scripts/v4_evaluation.py",
        "scripts/v4_official_runner.py",
        "scripts/v4_preflight.py", "scripts/build_v4_candidate.py",
        "scripts/verify_v4_candidate_truth.py",
        "scripts/validate_v4_tool_access.py",
        "scripts/freeze_v4.py",
        "experiment/v4/AGENT_PROMPT.txt", "experiment/v4/PREREGISTRATION.md",
        "experiment/v4/DEV_VALIDATION.md",
        "experiment/v4/runtime_datasets.json", "experiment/v4/candidate_scan_report.json",
        "experiment/v4/candidate_dataset_manifest.json",
    ]
    return {
        "schema_version": "ax-exp-v4-preregistration-v1",
        "experiment_id": "ax-exp-v4",
        "status": "DRAFT",
        "model": "claude-sonnet-5",
        "kiro_cli_version": "kiro-cli-chat 2.23.0",
        "backend": "AUTOMATED_FRESH_PROCESS_V2",
        "runtime_profile": "v4-candidate",
        "repetitions": 2,
        "dataset_files": dataset_files,
        "frozen_files": [{"path": path, "sha256": _sha(ROOT / path)} for path in frozen_paths],
        "tasks": _tasks(),
    }


def main() -> None:
    result = build()
    target = V4 / "CANDIDATE_MANIFEST.json"
    _write(target, result)
    print(json.dumps({"path": str(target), "tasks": len(result["tasks"]),
                      "dataset_files": len(result["dataset_files"]),
                      "status": result["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
