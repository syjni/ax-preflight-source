from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ax_mcp.adapter import AxMcpAdapter
from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity, validate_runtime_resource_leakage
from ax_mcp.telemetry import InvocationLogger


ROOT = Path(__file__).resolve().parents[1]


class RuntimeDatasetProfileTests(unittest.TestCase):
    def test_mini_and_ceiling_profiles_are_distinct_verified_corpora(self) -> None:
        mini = resolve_runtime_dataset("mini")
        ceiling = resolve_runtime_dataset("ceiling")
        mini_identity = runtime_identity(mini)
        ceiling_identity = runtime_identity(ceiling)
        self.assertNotEqual(mini.source_root, ceiling.source_root)
        self.assertNotEqual(mini.scan_report, ceiling.scan_report)
        self.assertEqual(mini_identity["source_root_name"], "mini_company")
        self.assertEqual(ceiling_identity["source_root_name"], "ceiling_company")
        self.assertEqual(mini_identity["file_count"], 10)
        self.assertEqual(ceiling_identity["file_count"], 30)
        self.assertNotEqual(mini_identity["corpus_registry_sha256"], ceiling_identity["corpus_registry_sha256"])
        self.assertIsNone(mini_identity["dataset_manifest_sha256"])
        self.assertIsNotNone(ceiling_identity["dataset_manifest_sha256"])

    def test_ceiling_runtime_contains_customer_order_and_inventory_sources(self) -> None:
        dataset = resolve_runtime_dataset("ceiling")
        adapter = AxMcpAdapter(dataset.scan_report, dataset.source_root, InvocationLogger(stream=io.StringIO()))
        file_paths = {record.file_id: record.relative_path for record in adapter.layer.report.files}
        expected = {
            "03_영업/거래처_마스터.xlsx",
            "04_주문/주문_원장_2026.xlsx",
            "05_물류/재고_현황_2026-09.xlsx",
        }
        self.assertTrue(expected <= set(file_paths.values()))

        tables_by_path = {}
        for table in adapter.layer.report.tables:
            tables_by_path.setdefault(file_paths[table.file_id], []).append(table)
        customer_table = next(table for table in tables_by_path["03_영업/거래처_마스터.xlsx"]
                              if {"customer_id", "customer_name"} <= set(table.column_names))
        customer_rows = adapter.call_tool("query_table", {
            "table_id": customer_table.table_id,
            "select": ["customer_id", "customer_name"],
            "limit": 10,
        })["rows"]
        self.assertEqual(len(customer_rows), 10)
        self.assertTrue({"윤성마트", "다온유통"} <= {row["customer_name"] for row in customer_rows})
        self.assertTrue({"C013", "C021"}.isdisjoint({row["customer_id"] for row in customer_rows}))
        self.assertTrue(tables_by_path["04_주문/주문_원장_2026.xlsx"])
        self.assertTrue(tables_by_path["05_물류/재고_현황_2026-09.xlsx"])

    def test_ceiling_selection_does_not_fall_back_to_mini(self) -> None:
        selected = resolve_runtime_dataset(environ={"AX_RUNTIME_DATASET": "ceiling"})
        self.assertEqual(selected.profile, "ceiling")
        self.assertEqual(selected.source_root, (ROOT / "sample_data" / "ceiling_company").resolve())
        self.assertEqual(selected.scan_report, (ROOT / "ceiling_scan_report.json").resolve())

        env = {key: value for key, value in os.environ.items()
               if key not in {"AX_RUNTIME_DATASET", "AX_RUNTIME_DATASET_CONFIG"}}
        process = subprocess.run(
            [sys.executable, "-m", "ax_mcp.server"],
            cwd=ROOT,
            input="",
            text=True,
            capture_output=True,
            env=env,
            timeout=10,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("runtime dataset", process.stderr)

    def test_profiled_mcp_startup_writes_actual_runtime_identity_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "runtime-identity.json"
            process = subprocess.run(
                [sys.executable, "-m", "ax_mcp.server", "--dataset-profile", "ceiling",
                 "--runtime-identity-output", str(receipt)],
                cwd=ROOT,
                input="",
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["identity"]["dataset_profile"], "ceiling")
            self.assertEqual(payload["identity"]["source_root_name"], "ceiling_company")
            self.assertEqual(payload["identity"]["file_count"], 30)

    def test_ceiling_runtime_resources_and_visible_metadata_have_no_benchmark_leakage(self) -> None:
        dataset = resolve_runtime_dataset("ceiling")
        leakage = validate_runtime_resource_leakage(dataset)
        self.assertTrue(leakage["passed"], leakage)

        adapter = AxMcpAdapter(dataset.scan_report, dataset.source_root, InvocationLogger(stream=io.StringIO()))
        visible = json.dumps({
            "identity": runtime_identity(dataset),
            "tools": adapter.list_tools(),
            "search": adapter.call_tool("search_documents", {"query": "거래처 주문 재고", "top_k": 5}),
        }, ensure_ascii=False).casefold()
        for marker in leakage["forbidden_markers"]:
            self.assertNotIn(marker.casefold(), visible)


if __name__ == "__main__":
    unittest.main()
