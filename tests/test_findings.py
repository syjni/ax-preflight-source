from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from ax_product.evidence import ToolResponseStore
from ax_product.findings import FindingType, aggregate_findings
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.results import CompositeResultStore, ResultStore


class FindingAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "runs"
        self.store = ResultStore(self.root)

    def write_run(
        self,
        run_id: str,
        *,
        dataset: str = "mini",
        task_key: str | None = "TASK_RETURN_WINDOW",
        task_label: str = "현재 반품 가능 기간은 며칠인가요?",
        status: str = "ABSTAINED",
        reason: str | None = "CONFLICTING_EVIDENCE",
        source_ids: list[str] | None = None,
        answer: Any = None,
        unit: str | None = None,
    ) -> None:
        sources = ["DOC_OLD", "DOC_NEW"] if source_ids is None else source_ids
        self.store.reserve(
            run_id=run_id, task_id=None, model="test", dataset=dataset,
            task_key=task_key, task_label=task_label if task_key else None,
            request_type="AD_HOC_QUESTION" if task_key else None,
        )
        if sources:
            ToolResponseStore(self.root).record(
                run_id=run_id,
                tool_name="search_documents",
                output={
                    "results": [
                        {
                            "document_id": source_id,
                            "title": f"{source_id}.txt",
                            "snippet": f"{source_id}에서 실제 반환된 근거 문장입니다.",
                            "tables": [],
                        }
                        for source_id in sources
                    ],
                    "results_returned": len(sources),
                },
            )
        payload = SubmitAnswerInput(
            status=status,
            answer=answer,
            unit=unit,
            explanation="테스트 실행 결과",
            source_ids=sources,
            abstention_reason=reason,
        )
        self.store.write(DeliveryEnvelope(
            delivery_status="DELIVERED", run_id=run_id, model="test",
            payload=payload, source_link_status="NOT_CHECKED",
        ))

    def response(self, dataset: str = "mini"):
        return aggregate_findings(
            CompositeResultStore(self.root), dataset,
            comparison_config=Path(self.temporary.name) / "missing-comparisons.json",
        )

    def test_conflicts_group_by_type_and_sorted_sources_without_inflating_tasks(self) -> None:
        self.write_run("repeat-1", source_ids=["DOC_NEW", "DOC_OLD"])
        self.write_run("repeat-2", source_ids=["DOC_OLD", "DOC_NEW"])

        response = self.response()

        self.assertEqual(response.diagnostics.task_count, 1)
        self.assertEqual(response.diagnostics.blocked_task_count, 1)
        self.assertEqual(response.diagnostics.abstained_run_count, 2)
        self.assertEqual(len(response.findings), 1)
        finding = response.findings[0]
        self.assertEqual(finding.finding_type, FindingType.CONFLICTING_SOURCES)
        self.assertEqual(finding.source_ids, ["DOC_NEW", "DOC_OLD"])
        self.assertEqual(finding.affected_task_count, 1)
        self.assertEqual(finding.observed_run_count, 2)
        self.assertEqual(finding.affected_run_ids, ["repeat-1", "repeat-2"])
        self.assertEqual([item.source_title for item in finding.evidence], [
            "DOC_NEW.txt", "DOC_OLD.txt",
        ])
        self.assertTrue(all(item.excerpt for item in finding.evidence))
        self.assertIn("DOC_NEW.txt", finding.recommended_action)
        self.assertIn("DOC_OLD.txt", finding.recommended_action)
        self.assertIn("폐기 또는 대체 표시", finding.recommended_action)

    def test_not_found_is_task_scoped_and_never_invents_source_evidence(self) -> None:
        self.write_run(
            "missing-1", task_key="TASK_OWNER", task_label="승인 책임자는 누구인가요?",
            reason="NOT_FOUND", source_ids=[],
        )
        self.write_run(
            "missing-2", task_key="TASK_OWNER", task_label="승인 책임자는 누구인가요?",
            reason="NOT_FOUND", source_ids=[],
        )
        self.write_run(
            "missing-3", task_key="TASK_LIMIT", task_label="승인 한도는 얼마인가요?",
            reason="NOT_FOUND", source_ids=[],
        )

        findings = self.response().findings

        self.assertEqual(len(findings), 2)
        owner = next(item for item in findings if item.affected_task_ids == ["TASK_OWNER"])
        self.assertEqual(owner.finding_type, FindingType.MISSING_INFORMATION)
        self.assertEqual(owner.source_ids, [])
        self.assertEqual(owner.evidence, [])
        self.assertEqual(owner.observed_run_count, 2)
        self.assertIn("승인 책임자는 누구인가요?", owner.recommended_action)
        self.assertIn("담당 부서", owner.recommended_action)

    def test_insufficient_evidence_recommends_specific_document_fields(self) -> None:
        self.write_run(
            "insufficient-1",
            reason="INSUFFICIENT_EVIDENCE",
            source_ids=["DOC_POLICY"],
        )

        finding = self.response().findings[0]

        self.assertEqual(finding.finding_type, FindingType.INSUFFICIENT_EVIDENCE)
        self.assertIn("DOC_POLICY.txt", finding.recommended_action)
        self.assertIn("수치·기한·적용 조건", finding.recommended_action)

    def test_legacy_runs_without_task_identity_do_not_inflate_task_count(self) -> None:
        self.write_run("legacy-1", task_key=None)
        self.write_run("legacy-2", task_key=None)

        response = self.response()

        self.assertEqual(response.diagnostics.task_count, 0)
        self.assertEqual(len(response.findings), 1)
        self.assertEqual(response.findings[0].affected_task_count, 0)
        self.assertEqual(response.findings[0].observed_run_count, 2)

    def test_repeated_answered_runs_normalize_value_and_unit(self) -> None:
        for run_id, answer, unit in (
            ("stable-1", "4,980,700원", "KRW"),
            ("stable-2", "4980700 원", "원"),
            ("stable-3", 4980700, "krw"),
        ):
            self.write_run(
                run_id, status="ANSWERED", reason=None, answer=answer, unit=unit,
                source_ids=["TABLE_ORDERS"],
            )

        response = self.response()

        self.assertEqual(response.diagnostics.processable_task_count, 1)
        self.assertEqual(response.diagnostics.inconclusive_task_count, 0)
        self.assertFalse(any(
            item.finding_type == FindingType.INCONSISTENT_ANSWERS
            for item in response.findings
        ))

    def test_repeated_answered_runs_normalize_count_suffix_and_identifier_detail(self) -> None:
        cases = (
            ("count-1", "10곳", "거래처 수", "TABLE_CUSTOMERS"),
            ("count-2", 10, "거래처", "TABLE_CUSTOMERS"),
            ("item-1", "P005", "개", "TABLE_INVENTORY"),
            (
                "item-2", "P005 (WH-SEOUL 창고, 가용재고 281)",
                "available_qty", "TABLE_INVENTORY",
            ),
        )
        for run_id, answer, unit, source_id in cases:
            task_key = "TASK_COUNT" if run_id.startswith("count") else "TASK_ITEM"
            self.write_run(
                run_id, task_key=task_key, status="ANSWERED", reason=None,
                answer=answer, unit=unit, source_ids=[source_id],
            )

        response = self.response()

        self.assertEqual(response.diagnostics.processable_task_count, 2)
        self.assertFalse(any(
            item.finding_type == FindingType.INCONSISTENT_ANSWERS
            for item in response.findings
        ))

    def test_repeated_answered_runs_extract_typed_value_from_prose(self) -> None:
        for run_id, answer, unit in (
            (
                "deadline-1",
                "매월 세금계산서는 익월 5영업일까지 마감합니다.",
                "business_day_of_next_month",
            ),
            (
                "deadline-2",
                "월별 세금계산서는 익월 5번째 영업일에 마감합니다.",
                "영업일 (익월 5일)",
            ),
        ):
            self.write_run(
                run_id, status="ANSWERED", reason=None, answer=answer, unit=unit,
                source_ids=["DOC_BILLING"],
            )

        response = self.response()

        self.assertEqual(response.diagnostics.processable_task_count, 1)
        self.assertFalse(any(
            item.finding_type == FindingType.INCONSISTENT_ANSWERS
            for item in response.findings
        ))

    def test_inconsistent_answer_values_create_finding_without_inflating_tasks(self) -> None:
        for run_id, answer in (
            ("vary-1", "14일"), ("vary-2", 30), ("vary-3", "30 days"),
        ):
            self.write_run(
                run_id, status="ANSWERED", reason=None, answer=answer, unit="일",
                source_ids=["DOC_POLICY"],
            )

        response = self.response()
        finding = next(
            item for item in response.findings
            if item.finding_type == FindingType.INCONSISTENT_ANSWERS
        )

        self.assertEqual(response.diagnostics.task_count, 1)
        self.assertEqual(response.diagnostics.processable_task_count, 0)
        self.assertEqual(response.diagnostics.inconclusive_task_count, 1)
        self.assertEqual(finding.affected_task_count, 1)
        self.assertEqual(finding.observed_run_count, 3)
        self.assertEqual(len(finding.answer_variants), 2)
        self.assertEqual(sorted(item.run_count for item in finding.answer_variants), [1, 2])
        self.assertIn("다시 3회 실행", finding.recommended_action)

    def test_same_answer_with_different_cited_source_set_is_inconsistent(self) -> None:
        self.write_run(
            "sources-1", status="ANSWERED", reason=None, answer="30일", unit="days",
            source_ids=["DOC_CURRENT"],
        )
        self.write_run(
            "sources-2", status="ANSWERED", reason=None, answer=30, unit="일",
            source_ids=["DOC_CURRENT", "DOC_OLD"],
        )
        self.write_run(
            "sources-3", status="ANSWERED", reason=None, answer="30 days", unit="day",
            source_ids=["DOC_CURRENT"],
        )

        response = self.response()
        finding = next(
            item for item in response.findings
            if item.finding_type == FindingType.INCONSISTENT_ANSWERS
        )

        self.assertEqual(response.diagnostics.processable_task_count, 1)
        self.assertEqual(finding.source_ids, ["DOC_CURRENT", "DOC_OLD"])
        self.assertEqual(len(finding.answer_variants), 2)
        self.assertEqual(finding.observed_run_count, 3)

    def test_after_comparison_uses_conservative_not_reproduced_language(self) -> None:
        self.write_run("before-1", dataset="before")
        self.write_run("before-2", dataset="before")
        self.write_run(
            "after-1", dataset="after", status="ANSWERED", reason=None,
            source_ids=["DOC_CURRENT"], answer="30일",
        )
        self.write_run(
            "after-2", dataset="after", status="ANSWERED", reason=None,
            source_ids=["DOC_CURRENT"], answer="30일",
        )
        config = Path(self.temporary.name) / "comparisons.json"
        config.write_text(json.dumps({
            "schema_version": "ax-finding-comparisons-v1",
            "comparisons": [{
                "before_dataset": "before",
                "after_dataset": "after",
                "task_id": "TASK_RETURN_WINDOW",
                "task_label": "현재 반품 가능 기간은 며칠인가요?",
            }],
        }, ensure_ascii=False), encoding="utf-8")

        response = aggregate_findings(
            CompositeResultStore(self.root), "after", comparison_config=config
        )

        self.assertEqual(response.diagnostics.processable_task_count, 1)
        self.assertEqual(len(response.findings), 1)
        finding = response.findings[0]
        self.assertEqual(finding.comparison_status, "NOT_REPRODUCED_AFTER")
        self.assertEqual(finding.comparison.before_abstained_run_count, 2)
        self.assertEqual(finding.comparison.before_observed_run_count, 2)
        self.assertEqual(finding.comparison.after_answered_run_count, 2)
        self.assertEqual(finding.comparison.after_observed_run_count, 2)


if __name__ == "__main__":
    unittest.main()
