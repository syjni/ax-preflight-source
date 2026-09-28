from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ax_product.evidence import ToolResponseStore
from ax_product.findings import aggregate_findings
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.results import CompositeResultStore, ResultStore


def _write_answered(
    root: Path,
    run_id: str,
    task_id: str,
    question: str,
    answer: str,
    unit: str,
    source_ids: list[str],
) -> None:
    store = ResultStore(root)
    store.reserve(
        run_id=run_id,
        task_id=None,
        model="test",
        dataset="dataset",
        task_key=task_id,
        task_label=question,
        request_type="TASK_CANDIDATE",
    )
    ToolResponseStore(root).record(
        run_id=run_id,
        tool_name="search_documents",
        output={
            "results": [
                {
                    "document_id": source_id,
                    "title": f"{source_id}.txt",
                    "snippet": f"{answer} 근거",
                    "tables": [],
                }
                for source_id in source_ids
            ],
            "results_returned": len(source_ids),
        },
    )
    store.write(DeliveryEnvelope(
        delivery_status="DELIVERED",
        run_id=run_id,
        model="test",
        payload=SubmitAnswerInput(
            status="ANSWERED",
            answer=answer,
            unit=unit,
            explanation="테스트 실행 결과",
            source_ids=source_ids,
        ),
        source_link_status="NOT_CHECKED",
    ))


class InconsistencyAttributionTests(unittest.TestCase):
    def test_inconsistency_does_not_claim_a_data_cause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_answered(root, "run-a", "TASK", "질문", "14일", "일", ["FILE_A"])
            _write_answered(root, "run-b", "TASK", "질문", "30일", "일", ["FILE_B"])
            response = aggregate_findings(
                CompositeResultStore(root), "dataset"
            )

            finding = next(
                item for item in response.findings
                if item.finding_type.value == "INCONSISTENT_ANSWERS"
            )
            self.assertEqual(finding.attribution_status, "CAUSE_UNCONFIRMED")
            self.assertIn("원인을 문서 데이터에 귀속할 수", finding.summary)
            self.assertIn("문서를 바로 수정하지 말고", finding.recommended_action)


if __name__ == "__main__":
    unittest.main()
