from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from ax_agent.errors import AgentBudgetExceeded, AgentToolError
from ax_agent.models import AgentOutput, QueryTableInput, TaskCategory
from ax_agent.tools import AgentToolLayer, tool_schema_catalog


ROOT = Path(__file__).resolve().parents[1]


class AgentToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.layer = AgentToolLayer(ROOT / "scan_report.json", ROOT / "sample_data" / "mini_company")
        file_paths = {record.file_id: record.relative_path for record in cls.layer.report.files}
        cls.customers = next(table.table_id for table in cls.layer.report.tables
                             if file_paths[table.file_id] == "tables/customers.csv")
        cls.orders = next(table.table_id for table in cls.layer.report.tables
                          if file_paths[table.file_id] == "tables/orders.xlsx" and table.sheet_name == "Orders")

    def test_only_four_model_callable_tools(self) -> None:
        self.assertEqual(set(tool_schema_catalog()),
            {"search_documents", "read_document", "lookup_value", "query_table"})

    def test_search_defaults_to_five_and_snippets_are_bounded(self) -> None:
        result = self.layer.start_task("search", TaskCategory.KNOWLEDGE).search_documents("반품 기간")
        self.assertLessEqual(result.results_returned, 5)
        self.assertTrue(result.results)
        self.assertTrue(all(len(hit.snippet) <= 500 for hit in result.results))

    def test_read_document_uses_2500_character_sections(self) -> None:
        payload = json.loads((ROOT / "scan_report.json").read_text(encoding="utf-8"))
        payload["files"][0]["text"] = "가" * 6001
        payload["files"][0]["text_char_count"] = 6001
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            session = AgentToolLayer(report, ROOT / "sample_data" / "mini_company").start_task(
                "read", TaskCategory.KNOWLEDGE)
            first = session.read_document(payload["files"][0]["file_id"])
            second = session.read_document(payload["files"][0]["file_id"], section=1)
        self.assertEqual((first.characters_returned, first.next_section), (2500, 1))
        self.assertEqual(second.characters_returned, 2500)

    def test_lookup_applies_canonical_normalization(self) -> None:
        result = self.layer.start_task("lookup", TaskCategory.CROSS_FILE).lookup_value(
            self.customers, "customer_name", "주식회사 한빛상사", "customer_id")
        self.assertEqual((result.value, result.matched_rows), ("C013", 1))

    def test_cross_file_name_to_id_to_order_sum(self) -> None:
        session = self.layer.start_task("cross", TaskCategory.CROSS_FILE)
        customer = session.lookup_value(self.customers, "customer_name", "(주) 한빛상사", "customer_id")
        total = session.query_table(self.orders, filters=[
            {"field": "customer_id", "op": "eq", "value": customer.value},
            {"field": "order_date", "op": "prefix", "value": "2026-08"}],
            aggregation={"op": "sum", "field": "amount", "alias": "total_amount"},
            select=["total_amount"])
        self.assertEqual(total.rows, [{"total_amount": 200000}])
        self.assertEqual((session.metrics().tool_calls, session.metrics().budget), (2, 12))

    def test_search_discovers_ids_for_lookup_and_query_without_known_table_ids(self) -> None:
        session = self.layer.start_task("discover-tables", TaskCategory.CROSS_FILE)

        search = session.search_documents("customer orders", top_k=10)
        customer_reference = next(
            reference
            for hit in search.results
            for reference in hit.tables
            if {"customer_name", "customer_id"} <= set(reference.column_names)
        )
        customer = session.lookup_value(
            customer_reference.table_id, "customer_name", "한빛상사", "customer_id")
        self.assertGreater(customer.matched_rows, 0)
        self.assertEqual(customer.source_ids, [customer_reference.table_id])

        order_reference = next(
            reference
            for hit in search.results
            for reference in hit.tables
            if {"order_id", "customer_id", "order_date", "amount"} <= set(reference.column_names)
        )
        orders = session.query_table(
            order_reference.table_id,
            filters=[{"field": "customer_id", "op": "eq", "value": customer.value}],
            select=["order_id", "customer_id"],
        )
        self.assertEqual(orders.table_id, order_reference.table_id)
        self.assertEqual(orders.source_ids, [order_reference.table_id])
        self.assertLessEqual(orders.rows_returned, 10)
        self.assertTrue(all(row["customer_id"] == customer.value for row in orders.rows))

    def test_guessed_table_identifiers_are_not_silently_accepted(self) -> None:
        order_file = next(
            record for record in self.layer.report.files
            if record.relative_path == "tables/orders.xlsx"
        )
        guesses = ["orders", order_file.filename, order_file.file_id]
        session = self.layer.start_task("reject-table-guesses", TaskCategory.CROSS_FILE)
        for identifier in guesses:
            with self.subTest(tool="lookup_value", identifier=identifier):
                with self.assertRaises(AgentToolError) as raised:
                    session.lookup_value(identifier, "customer_id", "unknown", "order_id")
                self.assertEqual(raised.exception.code, "TABLE_NOT_FOUND")
            with self.subTest(tool="query_table", identifier=identifier):
                with self.assertRaises(AgentToolError) as raised:
                    session.query_table(identifier, select=["order_id"])
                self.assertEqual(raised.exception.code, "TABLE_NOT_FOUND")

    def test_group_order_limit_dsl(self) -> None:
        result = self.layer.start_task("group", TaskCategory.OPERATIONS).query_table(
            self.orders, aggregation={"op": "sum", "field": "amount", "alias": "total_amount"},
            group_by=["customer_id"], order_by=[{"field": "total_amount", "direction": "desc"}], limit=1)
        self.assertEqual(result.rows, [{"customer_id": "C013", "total_amount": 200000}])
        self.assertEqual(result.result_rows_before_limit, 2)
        self.assertTrue(result.truncated)

    def test_all_supported_aggregations(self) -> None:
        expected = {"sum": 299000, "avg": 299000 / 3, "count": 3, "min": 75000, "max": 125000}
        for operation, value in expected.items():
            spec = {"op": operation, "alias": "answer"}
            if operation != "count":
                spec["field"] = "amount"
            result = self.layer.start_task(operation, TaskCategory.OPERATIONS).query_table(
                self.orders, aggregation=spec)
            self.assertAlmostEqual(result.rows[0]["answer"], value)
        rate = self.layer.start_task("rate", TaskCategory.OPERATIONS).query_table(self.orders,
            aggregation={"op": "rate", "numerator_field": "amount",
                         "denominator_field": "amount", "alias": "rate"})
        self.assertEqual(rate.rows, [{"rate": 1.0}])

    def test_limit_above_ten_is_rejected_not_clamped(self) -> None:
        with self.assertRaises(ValidationError):
            QueryTableInput(table_id=self.orders, limit=11)

    def test_default_query_output_is_hard_capped_at_ten_rows(self) -> None:
        layer = AgentToolLayer(ROOT / "scan_report.json", ROOT / "sample_data" / "mini_company")
        layer.table_store.cache[self.orders] = [
            {"order_id": f"O{index}", "customer_id": "C013", "order_date": "2026-08-01",
             "amount": index, "memo": None}
            for index in range(25)
        ]
        result = layer.start_task("cap", TaskCategory.OPERATIONS).query_table(
            self.orders, select=["order_id"])
        self.assertEqual(result.rows_returned, 10)
        self.assertEqual(result.result_rows_before_limit, 25)
        self.assertTrue(result.truncated)

    def test_unknown_column_is_reported(self) -> None:
        with self.assertRaisesRegex(AgentToolError, "unknown columns"):
            self.layer.start_task("bad", TaskCategory.OPERATIONS).query_table(
                self.orders, select=["secret_column"])

    def test_budget_is_enforced_without_relaxation(self) -> None:
        session = self.layer.start_task("budget", TaskCategory.KNOWLEDGE)
        for _ in range(6):
            session.search_documents("반품")
        with self.assertRaises(AgentBudgetExceeded) as raised:
            session.search_documents("반품")
        self.assertEqual(raised.exception.code, "AGENT_BUDGET_EXCEEDED")
        self.assertEqual(session.metrics().tool_calls, 6)
        self.assertTrue(session.metrics().budget_exceeded)

    def test_structured_output_abstention_invariant(self) -> None:
        self.assertTrue(AgentOutput(final_answer=None, unit=None,
            explanation="자료에 필요한 정보가 없습니다.", source_ids=[], abstain=True).abstain)
        with self.assertRaises(ValidationError):
            AgentOutput(final_answer="guess", explanation="", source_ids=[], abstain=True)

    def test_table_output_masks_pii(self) -> None:
        result = self.layer.start_task("pii", TaskCategory.OPERATIONS).query_table(
            self.customers, select=["customer_id", "email"], limit=2)
        self.assertEqual(result.rows[0]["email"], "[EMAIL_MASKED]")


if __name__ == "__main__":
    unittest.main()
