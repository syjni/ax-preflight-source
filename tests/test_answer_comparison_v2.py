from __future__ import annotations

import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from ax_agent.tools import AgentToolLayer
from ax_product.findings import (
    FindingType,
    _normalized_answer_v2,
    aggregate_findings,
)
from ax_product.models import SubmitAnswerInput
from ax_product.results import CompositeResultStore


ROOT = Path(__file__).resolve().parents[1]
V4_RUNS = ROOT / "artifacts" / "phase6_product_demo_v4" / "runs"


class AnswerComparisonV2Tests(unittest.TestCase):
    def test_explicit_answer_kinds_make_empty_sets_lists_and_quantities_unambiguous(self) -> None:
        common = {"status": "ANSWERED", "explanation": "근거 확인", "source_ids": ["SRC"]}
        empty = SubmitAnswerInput(**common, answer=[], answer_kind="EMPTY_SET")
        identifiers = SubmitAnswerInput(
            **common, answer=["P005", "P012"], answer_kind="ID_LIST"
        )
        quantity = SubmitAnswerInput(
            **common, answer=30, answer_kind="NUMERIC_QUANTITY", unit="일"
        )

        self.assertEqual(empty.answer, [])
        self.assertEqual(identifiers.answer_kind, "ID_LIST")
        self.assertEqual(quantity.unit, "일")
        with self.assertRaises(ValidationError):
            SubmitAnswerInput(**common, answer="없음", answer_kind="EMPTY_SET")
        with self.assertRaises(ValidationError):
            SubmitAnswerInput(**common, answer="30일", answer_kind="NUMERIC_QUANTITY", unit="일")

    def test_legacy_v4_shapes_use_general_semantic_rules(self) -> None:
        empty_answers = (
            "없음 (해당 품목 없음)",
            "해당 품목 없음 (전 품목이 안전재고 기준을 충족함)",
            "없음 (안전재고 기준보다 부족한 품목 없음)",
        )
        empty_signatures = {_normalized_answer_v2(value, None, None) for value in empty_answers}
        self.assertEqual(empty_signatures, {("empty_set", "[]", None)})

        item_answers = (
            ("유기농 그래놀라 (product_id: P005)", "개(available_qty)"),
            ("유기농 그래놀라 (P005) — 가용재고 281개", "개"),
        )
        item_signatures = {_normalized_answer_v2(value, unit, None) for value, unit in item_answers}
        self.assertEqual(item_signatures, {("id_list", '["p005"]', None)})

        responsibility_answers = (
            "CS01 배송문의: 고객지원팀 / CS02 반품문의: 고객지원팀 / CS03 상품문의: 영업운영팀",
            "배송문의(CS01): 고객지원팀 / 반품문의(CS02): 고객지원팀 / 상품문의(CS03): 영업운영팀",
            "배송문의(CS01) → 고객지원팀 | 반품문의(CS02) → 고객지원팀 | 상품문의(CS03) → 영업운영팀",
        )
        responsibility_signatures = {
            _normalized_answer_v2(value, None, None) for value in responsibility_answers
        }
        self.assertEqual(len(responsibility_signatures), 1)
        changed_assignment = _normalized_answer_v2(
            "CS01 배송문의: 영업운영팀 / CS02 반품문의: 고객지원팀 / CS03 상품문의: 영업운영팀",
            None,
            None,
        )
        self.assertNotIn(changed_assignment, responsibility_signatures)

        deadline_answers = (
            ("매월 세금계산서는 다음 달 5영업일에 마감됩니다.", "영업일 (매월 5일)"),
            ("매월 세금계산서는 다음 달 5번째 영업일에 마감됩니다.", None),
        )
        deadline_signatures = {
            _normalized_answer_v2(value, unit, None) for value, unit in deadline_answers
        }
        self.assertEqual(deadline_signatures, {("number", "5", "business_day_next_month")})

        self.assertNotEqual(
            _normalized_answer_v2("14일", "일", None),
            _normalized_answer_v2("30일", "일", None),
        )

    def test_frozen_runs_are_reclassified_without_reexecution_and_keep_v1_auditable(self) -> None:
        store = CompositeResultStore(ROOT / "_review_v2" / "missing", V4_RUNS)
        before = aggregate_findings(
            store, "portfolio-hidden-conflict-before", comparison_version="v2"
        )
        after = aggregate_findings(
            store, "portfolio-ceiling-after", comparison_version="v2"
        )

        self.assertEqual(
            (before.diagnostics.processable_task_count,
             before.diagnostics.blocked_task_count,
             before.diagnostics.inconclusive_task_count),
            (5, 3, 2),
        )
        self.assertEqual(
            (after.diagnostics.processable_task_count,
             after.diagnostics.blocked_task_count,
             after.diagnostics.inconclusive_task_count),
            (6, 2, 2),
        )
        self.assertEqual(
            (after.legacy_diagnostics.processable_task_count,
             after.legacy_diagnostics.blocked_task_count,
             after.legacy_diagnostics.inconclusive_task_count),
            (2, 4, 4),
        )
        self.assertFalse(any(
            item.finding_type == FindingType.INCONSISTENT_ANSWERS
            for item in after.findings
        ))
        mixed = [
            item for item in after.findings
            if item.finding_type == FindingType.MIXED_OUTCOMES
        ]
        self.assertEqual(
            [item.affected_task_ids[0] for item in mixed],
            ["TASK_ORDER_LATEST", "TASK_ORDER_MONTHLY_AMOUNT"],
        )
        self.assertTrue(all(item.observed_run_count == 3 for item in mixed))
        monthly = next(
            item for item in mixed
            if item.affected_task_ids == ["TASK_ORDER_MONTHLY_AMOUNT"]
        )
        self.assertEqual(
            [(item.answer, item.run_count) for item in monthly.answer_variants],
            [("4,980,700원", 2)],
        )
        self.assertEqual(
            [(item.reason, item.run_count) for item in monthly.abstention_variants],
            [("NOT_FOUND", 1)],
        )
        self.assertTrue(all(
            item.attribution_status == "RETRIEVAL_LIMITATION" for item in mixed
        ))
        self.assertIn("기준월", monthly.recommended_action)
        self.assertIn("검색 결과 상위 목록", monthly.recommended_action)
        latest = next(
            item for item in mixed
            if item.affected_task_ids == ["TASK_ORDER_LATEST"]
        )
        self.assertIn("주문_원장_2026.xlsx", latest.recommended_action)
        self.assertIn("4위", latest.recommended_action)

        structured_evidence = [
            evidence
            for finding in mixed
            for evidence in finding.evidence
            if evidence.tool_name == "query_table"
        ]
        self.assertTrue(structured_evidence)
        for evidence in structured_evidence:
            rows = json.loads(evidence.excerpt or "")
            self.assertIsInstance(rows, list)
            self.assertLessEqual(len(rows), 1)

        approval = next(
            item for item in after.findings
            if item.affected_task_ids == ["TASK_POLICY_APPROVAL_PROCEDURE"]
        )
        self.assertIn("일반 예외 승인 절차는 정의되어 있지 않습니다", approval.recommended_action)

    def test_order_ledger_is_indexed_but_ranked_below_short_top_k_paths(self) -> None:
        layer = AgentToolLayer(
            ROOT / "ceiling_scan_report.json", ROOT / "sample_data" / "ceiling_company"
        )
        record = layer.documents["FILE_950a2b2ed909ef4c"]
        self.assertEqual(record.filename, "주문_원장_2026.xlsx")
        self.assertGreater(record.text_char_count, 0)
        self.assertIn(
            "TABLE_FILE_950a2b2ed909ef4c_Orders", layer.index.tables_by_file[record.file_id][0].table_id
        )

        exact_hits = layer.index.search("주문원장_2026", 10)
        order_rank = next(
            index for index, hit in enumerate(exact_hits, start=1)
            if hit.document_id == record.file_id
        )
        self.assertEqual(order_rank, 4)
        for query in ("가장 최근 주문", "이번 달 주문금액"):
            self.assertNotIn(record.file_id, {
                hit.document_id for hit in layer.index.search(query, 10)
            })


if __name__ == "__main__":
    unittest.main()
