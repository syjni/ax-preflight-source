"""Exercise the v5 runner on development-only evidence, never on v5 candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.v5_official_runner import ROOT, run_one


DEV_TASK = {
    "task_id": "DEV_V5_MULTI_01",
    "category": "knowledge",
    "question": "개발용 한울상점 메모에서 2027년 시범 매장 재고 점검의 책임팀을 알려주세요. 먼저 자료를 검색하고 중간 확인 내용을 짧게 말한 다음, 원문 문서를 읽어 최종 JSON으로 답하세요.",
    "expected_answer": "시설운영팀",
    "scoring_method": {"type": "exact_text", "accepted_forms": ["시설운영팀"]},
    "expects_abstention": False,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("development Kiro run requires --execute")
    manifest_path = ROOT / "experiment" / "v5" / "DEV_RUNNER_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = run_one(DEV_TASK, 1, manifest,
                      artifact_root=ROOT / "artifacts" / "v5_development" / "runner_probe",
                      manifest_path=manifest_path)
    run_dir = ROOT / "artifacts" / "v5_development" / "runner_probe" / DEV_TASK["task_id"] / "r1"
    stream_receipt = json.loads((run_dir / "stream-response-validation.json").read_text(encoding="utf-8"))
    summary = {"development_only": True, "validity_status": receipt["validity_status"],
               "validation_errors": receipt["validation_errors"],
               "stream_validation_passed": stream_receipt["passed"],
               "assistant_message_count": stream_receipt["assistant_message_count"],
               "aggregate_differs_from_final": (stream_receipt["aggregate_sha256"]
                                                != stream_receipt["final_response_sha256"]),
               "outcome": receipt.get("outcome"),
               "delivered_valid": receipt.get("delivered_valid")}
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if receipt["validity_status"] == "VALID" and stream_receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
