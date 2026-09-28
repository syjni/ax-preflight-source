from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from ax_agent.errors import AgentToolError
from ax_agent.models import TaskCategory
from ax_agent.tools import AgentToolLayer
from ax_mcp.adapter import AX_MCP_TOOL_NAMES, AxMcpAdapter
from ax_mcp.server import AxMcpStdioServer
from ax_mcp.telemetry import InvocationLogger


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "scan_report.json"
SOURCE_ROOT = ROOT / "sample_data" / "mini_company"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class McpAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.log_stream = io.StringIO()
        cls.adapter = AxMcpAdapter(REPORT, SOURCE_ROOT, InvocationLogger(stream=cls.log_stream))
        file_paths = {record.file_id: record.relative_path for record in cls.adapter.layer.report.files}
        cls.customers = next(table.table_id for table in cls.adapter.layer.report.tables
                             if file_paths[table.file_id] == "tables/customers.csv")
        cls.orders = next(table.table_id for table in cls.adapter.layer.report.tables
                          if file_paths[table.file_id] == "tables/orders.xlsx" and table.sheet_name == "Orders")

    def test_exactly_four_intended_tools_are_exposed(self) -> None:
        tools = self.adapter.list_tools()
        self.assertEqual([tool["name"] for tool in tools], list(AX_MCP_TOOL_NAMES))
        self.assertEqual(set(AX_MCP_TOOL_NAMES),
            {"search_documents", "read_document", "lookup_value", "query_table"})
        serialized = json.dumps(tools)
        for forbidden in ("shell", "python", "sql", "filesystem", "write", "delete", "scanner"):
            self.assertNotIn(f'"name": "{forbidden}', serialized.lower())

    def test_mcp_search_schema_and_descriptions_explain_table_discovery(self) -> None:
        tools = {tool["name"]: tool for tool in self.adapter.list_tools()}
        search_schema = tools["search_documents"]["outputSchema"]
        reference_schema = search_schema["$defs"]["SearchTableReference"]
        self.assertEqual(
            set(reference_schema["properties"]),
            {"table_id", "sheet_name", "column_names"},
        )
        hit_properties = search_schema["$defs"]["SearchHit"]["properties"]
        self.assertEqual(hit_properties["document_type"]["enum"], ["document", "tabular"])
        self.assertIn("SearchTableReference", hit_properties["tables"]["items"]["$ref"])
        for name in ("search_documents", "lookup_value", "query_table"):
            self.assertIn(
                "Never guess a table_id. Obtain it from search_documents metadata.",
                tools[name]["description"],
            )

    def test_mcp_search_to_lookup_to_query_uses_only_returned_table_ids(self) -> None:
        search = self.adapter.call_tool(
            "search_documents", {"query": "customer orders", "top_k": 10})
        customer_reference = next(
            reference
            for hit in search["results"]
            for reference in hit["tables"]
            if {"customer_name", "customer_id"} <= set(reference["column_names"])
        )
        order_reference = next(
            reference
            for hit in search["results"]
            for reference in hit["tables"]
            if {"order_id", "customer_id", "order_date", "amount"}
            <= set(reference["column_names"])
        )

        customer = self.adapter.call_tool("lookup_value", {
            "table_id": customer_reference["table_id"],
            "match_column": "customer_name",
            "value": "한빛상사",
            "return_column": "customer_id",
        })
        orders = self.adapter.call_tool("query_table", {
            "table_id": order_reference["table_id"],
            "filters": [{"field": "customer_id", "op": "eq", "value": customer["value"]}],
            "select": ["order_id", "customer_id"],
        })

        self.assertEqual(customer["source_ids"], [customer_reference["table_id"]])
        self.assertEqual(orders["table_id"], order_reference["table_id"])
        self.assertEqual(orders["source_ids"], [order_reference["table_id"]])
        self.assertLessEqual(orders["rows_returned"], 10)

    def test_mcp_arguments_use_existing_typed_validation(self) -> None:
        with self.assertRaises(ValidationError):
            self.adapter.call_tool("search_documents", {"query": "반품", "top_k": 0})
        with self.assertRaises(ValidationError):
            self.adapter.call_tool("read_document", {"document_id": "FILE_x", "section": -1})
        with self.assertRaises(ValidationError):
            self.adapter.call_tool("query_table", {"table_id": self.orders, "limit": 11})

    def test_mcp_results_match_direct_results_for_all_four_tools(self) -> None:
        direct = AgentToolLayer(REPORT, SOURCE_ROOT)
        search_args = {"query": "현재 반품 기간", "top_k": 5}
        direct_search = direct.start_task("direct-search", TaskCategory.CROSS_FILE).search_documents(
            **search_args).model_dump(mode="json")
        self.assertEqual(self.adapter.call_tool("search_documents", search_args), direct_search)

        document_id = direct_search["results"][0]["document_id"]
        read_args = {"document_id": document_id, "section": None}
        direct_read = direct.start_task("direct-read", TaskCategory.CROSS_FILE).read_document(
            **read_args).model_dump(mode="json")
        self.assertEqual(self.adapter.call_tool("read_document", read_args), direct_read)

        lookup_args = {"table_id": self.customers, "match_column": "customer_name",
                       "value": "주식회사 한빛상사", "return_column": "customer_id"}
        direct_lookup = direct.start_task("direct-lookup", TaskCategory.CROSS_FILE).lookup_value(
            **lookup_args).model_dump(mode="json")
        self.assertEqual(self.adapter.call_tool("lookup_value", lookup_args), direct_lookup)

        query_args = {"table_id": self.orders,
            "filters": [{"field": "customer_id", "op": "eq", "value": "C013"}],
            "select": ["total_amount"],
            "aggregation": {"op": "sum", "field": "amount", "alias": "total_amount"}}
        direct_query = direct.start_task("direct-query", TaskCategory.CROSS_FILE).query_table(
            **query_args).model_dump(mode="json")
        self.assertEqual(self.adapter.call_tool("query_table", query_args), direct_query)

    def test_protocol_returns_validation_error_as_tool_error(self) -> None:
        server = AxMcpStdioServer(self.adapter)
        invalid_requests = [
            {"table_id": self.orders, "limit": 11},
            {"table_id": self.orders, "group_by": ["customer_id"]},
        ]
        for arguments in invalid_requests:
            response = server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {"name": "query_table", "arguments": arguments}})
            self.assertTrue(response["result"]["isError"])
            self.assertIn("VALIDATION_ERROR", response["result"]["content"][0]["text"])

    def test_context_and_row_limits_are_unchanged(self) -> None:
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        payload["files"][0]["text"] = "가" * 6001
        payload["files"][0]["text_char_count"] = 6001
        with tempfile.TemporaryDirectory() as directory:
            temp_report = Path(directory) / "scan_report.json"
            temp_report.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            adapter = AxMcpAdapter(temp_report, SOURCE_ROOT)
            read = adapter.call_tool("read_document", {"document_id": payload["files"][0]["file_id"]})
        self.assertEqual(read["characters_returned"], 2500)
        self.assertEqual(len(read["content"]), 2500)

        adapter = AxMcpAdapter(REPORT, SOURCE_ROOT)
        adapter.layer.table_store.cache[self.orders] = [
            {"order_id": f"O{index}", "customer_id": "C013", "order_date": "2026-08-01",
             "amount": index, "memo": None} for index in range(25)
        ]
        result = adapter.call_tool("query_table", {"table_id": self.orders, "select": ["order_id"]})
        self.assertEqual(result["rows_returned"], 10)
        self.assertTrue(result["truncated"])

    def test_stdio_server_starts_initializes_and_lists_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invocation_log = Path(directory) / "invocations.jsonl"
            process = subprocess.Popen(
                [sys.executable, "-m", "ax_mcp.server", "--invocation-log", str(invocation_log)], cwd=ROOT,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8", "AX_RUNTIME_DATASET": "mini"},
            )
            try:
                requests = [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "unittest", "version": "1"}}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "search_documents",
                                "arguments": {"query": "반품 가능 기간", "top_k": 5}}},
                ]
                responses = []
                for request in requests:
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                    responses.append(json.loads(process.stdout.readline()))
                self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "ax-agent-tools")
                self.assertEqual([tool["name"] for tool in responses[1]["result"]["tools"]],
                                 list(AX_MCP_TOOL_NAMES))
                self.assertFalse(responses[2]["result"]["isError"])
            finally:
                process.stdin.close()
                process.wait(timeout=5)
                stdout_remainder = process.stdout.read()
                stderr = process.stderr.read()
                process.stdout.close()
                process.stderr.close()
            self.assertEqual(stdout_remainder, "")
            self.assertEqual(stderr, "")
            records = [json.loads(line) for line in invocation_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["tool_name"], "search_documents")
            self.assertEqual(records[0]["safe_parameters"], {"query_length": 8, "top_k": 5})

    def test_invocation_log_records_safe_success_and_error_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "invocations.jsonl"
            adapter = AxMcpAdapter(REPORT, SOURCE_ROOT, InvocationLogger(log_path))
            query = "return policy period days"
            adapter.call_tool("search_documents", {"query": query, "top_k": 4})
            with self.assertRaises(ValidationError):
                adapter.call_tool("search_documents", {"query": query, "top_k": 0})

            text = log_path.read_text(encoding="utf-8")
            self.assertNotIn(query, text)
            records = [json.loads(line) for line in text.splitlines()]
            self.assertEqual([record["outcome"] for record in records], ["success", "error"])
            self.assertEqual(records[0]["safe_parameters"], {"query_length": len(query), "top_k": 4})
            self.assertEqual(records[1]["error_code"], "VALIDATION_ERROR")
            for record in records:
                self.assertEqual(record["tool_name"], "search_documents")
                self.assertTrue(record["start_time"].endswith("Z"))
                self.assertTrue(record["end_time"].endswith("Z"))
                self.assertGreaterEqual(record["elapsed_ms"], 0)

    def test_failed_data_call_consumes_the_persistent_cross_file_budget(self) -> None:
        log_stream = io.StringIO()
        adapter = AxMcpAdapter(
            REPORT, SOURCE_ROOT, InvocationLogger(stream=log_stream)
        )
        with self.assertRaises(AgentToolError) as failed:
            adapter.call_tool("read_document", {"document_id": "FILE_DOES_NOT_EXIST"})
        self.assertEqual(failed.exception.code, "DOCUMENT_NOT_FOUND")
        for _ in range(11):
            adapter.call_tool("search_documents", {"query": "반품", "top_k": 1})
        with self.assertRaises(AgentToolError) as exhausted:
            adapter.call_tool("search_documents", {"query": "반품", "top_k": 1})
        self.assertEqual(exhausted.exception.code, "AGENT_BUDGET_EXCEEDED")

        metrics = adapter.session.metrics()
        self.assertEqual(metrics.tool_calls, 12)
        self.assertTrue(metrics.budget_exceeded)
        self.assertFalse(metrics.events[0].success)
        self.assertEqual(metrics.events[0].error_code, "DOCUMENT_NOT_FOUND")
        records = [json.loads(line) for line in log_stream.getvalue().splitlines()]
        self.assertEqual(len(records), 13)
        self.assertEqual(records[0]["error_code"], "DOCUMENT_NOT_FOUND")
        self.assertEqual(records[-1]["error_code"], "AGENT_BUDGET_EXCEEDED")

    def test_stable_contract_hashes_are_unchanged(self) -> None:
        baseline = json.loads((ROOT / "kiro_integration_contract_baseline.json").read_text(encoding="utf-8"))
        observed = {relative: sha256(ROOT / relative) for relative in baseline["sha256"]}
        self.assertEqual(observed, baseline["sha256"])

    def test_kiro_agent_has_fixed_model_and_only_ax_tools(self) -> None:
        config = json.loads((ROOT / ".kiro" / "agents" / "ax-evaluation.json").read_text(encoding="utf-8"))
        expected = [f"@ax-tools/{name}" for name in AX_MCP_TOOL_NAMES]
        self.assertEqual(config["model"], "claude-sonnet-5")
        self.assertEqual(config["tools"], expected)
        self.assertEqual(config["allowedTools"], expected)
        self.assertFalse(config["includeMcpJson"])
        self.assertEqual(config["resources"], [])
        server = config["mcpServers"]["ax-tools"]
        self.assertEqual(server["env"]["AX_RUNTIME_DATASET"], "ceiling")
        self.assertNotIn("--scan-report", server["args"])
        self.assertNotIn("--source-root", server["args"])
        prompt = config["prompt"].lower()
        for forbidden in ("expected_answer", "primary_blocker", "defect ground truth"):
            self.assertNotIn(forbidden, prompt)


if __name__ == "__main__":
    unittest.main()
