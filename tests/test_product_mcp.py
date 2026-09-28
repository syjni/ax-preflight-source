from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ax_agent.errors import AgentToolError
from ax_mcp.adapter import AX_MCP_TOOL_NAMES, AxMcpAdapter
from ax_mcp.telemetry import InvocationLogger
from ax_product.adapter import PRODUCT_TOOL_NAMES, ProductMcpAdapter, ProductToolError
from ax_product.evidence import ToolResponseStore
from ax_product.models import SubmitAnswerInput
from ax_product.results import ResultStore
from ax_product.server import ProductMcpStdioServer


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "scan_report.json"
SOURCE_ROOT = ROOT / "sample_data" / "mini_company"
ANSWER = {
    "status": "ANSWERED", "answer": "30일", "unit": None,
    "explanation": "회사 문서에서 확인했습니다.", "source_ids": ["DOC_1"],
    "abstention_reason": None,
}


def adapter(run_id: str) -> ProductMcpAdapter:
    return ProductMcpAdapter(
        REPORT, SOURCE_ROOT, run_id=run_id, task_id="task-1", model="test-model",
        invocation_logger=InvocationLogger(stream=io.StringIO()),
    )


def call(server: ProductMcpStdioServer, name: str, arguments: dict) -> dict:
    response = server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    return response["result"]


class ProductAdapterTests(unittest.TestCase):
    def test_product_lists_four_existing_data_tools_and_submit_answer(self) -> None:
        product = adapter("run-1")
        tools = product.list_tools()
        self.assertEqual([tool["name"] for tool in tools], list(PRODUCT_TOOL_NAMES))
        self.assertEqual([tool["name"] for tool in tools[:4]], list(AX_MCP_TOOL_NAMES))
        self.assertEqual(tools[4]["inputSchema"], SubmitAnswerInput.model_json_schema())
        self.assertFalse(tools[4]["annotations"]["readOnlyHint"])
        research = AxMcpAdapter(REPORT, SOURCE_ROOT, InvocationLogger(stream=io.StringIO()))
        self.assertEqual(tools[:4], research.list_tools())

    def test_all_four_data_tools_delegate_unchanged(self) -> None:
        product = adapter("run-data")
        research = AxMcpAdapter(REPORT, SOURCE_ROOT, InvocationLogger(stream=io.StringIO()))
        search_args = {"query": "현재 반품 기간", "top_k": 5}
        search = product.call_tool("search_documents", search_args)
        self.assertEqual(search, research.call_tool("search_documents", search_args))
        read_args = {"document_id": search["results"][0]["document_id"]}
        self.assertEqual(product.call_tool("read_document", read_args),
                         research.call_tool("read_document", read_args))
        report = research.layer.report
        file_paths = {record.file_id: record.relative_path for record in report.files}
        customers = next(table.table_id for table in report.tables
                         if file_paths[table.file_id] == "tables/customers.csv")
        orders = next(table.table_id for table in report.tables
                      if file_paths[table.file_id] == "tables/orders.xlsx" and table.sheet_name == "Orders")
        lookup_args = {"table_id": customers, "match_column": "customer_name",
                       "value": "주식회사 한빛상사", "return_column": "customer_id"}
        query_args = {"table_id": orders, "select": ["order_id"], "limit": 2}
        self.assertEqual(product.call_tool("lookup_value", lookup_args),
                         research.call_tool("lookup_value", lookup_args))
        self.assertEqual(product.call_tool("query_table", query_args),
                         research.call_tool("query_table", query_args))
        self.assertEqual(product.submission.state, "UNSUBMITTED")

    def test_successful_data_response_is_recorded_under_its_run_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ResultStore(root).reserve(
                run_id="recorded-run", task_id=None, model="test-model", dataset="mini")
            response_store = ToolResponseStore(root)
            product = ProductMcpAdapter(
                REPORT, SOURCE_ROOT, run_id="recorded-run", model="test-model",
                invocation_logger=InvocationLogger(stream=io.StringIO()),
                response_store=response_store,
            )
            output = product.call_tool("search_documents", {"query": "현재 반품 기간"})
            records = response_store.read("recorded-run")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].run_id, "recorded-run")
            self.assertEqual(records[0].tool_name, "search_documents")
            self.assertEqual(records[0].output, output)
            product.call_tool("submit_answer", ANSWER)
            self.assertEqual(len(response_store.read("recorded-run")), 1)

    def test_four_data_tools_share_budget_but_submit_answer_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ResultStore(root).reserve(
                run_id="budgeted-run", task_id=None, model="test-model", dataset="mini"
            )
            response_store = ToolResponseStore(root)
            log_stream = io.StringIO()
            product = ProductMcpAdapter(
                REPORT,
                SOURCE_ROOT,
                run_id="budgeted-run",
                model="test-model",
                invocation_logger=InvocationLogger(stream=log_stream),
                response_store=response_store,
            )
            report = product.data_adapter.layer.report
            file_paths = {record.file_id: record.relative_path for record in report.files}
            customers = next(
                table.table_id
                for table in report.tables
                if file_paths[table.file_id] == "tables/customers.csv"
            )
            orders = next(
                table.table_id
                for table in report.tables
                if file_paths[table.file_id] == "tables/orders.xlsx"
                and table.sheet_name == "Orders"
            )

            search = product.call_tool(
                "search_documents", {"query": "현재 반품 기간", "top_k": 5}
            )
            product.call_tool(
                "read_document", {"document_id": search["results"][0]["document_id"]}
            )
            product.call_tool(
                "lookup_value",
                {
                    "table_id": customers,
                    "match_column": "customer_name",
                    "value": "주식회사 한빛상사",
                    "return_column": "customer_id",
                },
            )
            product.call_tool(
                "query_table", {"table_id": orders, "select": ["order_id"], "limit": 1}
            )
            for _ in range(8):
                product.call_tool(
                    "search_documents", {"query": "현재 반품 기간", "top_k": 1}
                )

            submitted = product.call_tool("submit_answer", ANSWER)
            self.assertEqual(submitted["delivery_status"], "DELIVERED")
            with self.assertRaises(AgentToolError) as exhausted:
                product.call_tool(
                    "search_documents", {"query": "현재 반품 기간", "top_k": 1}
                )
            self.assertEqual(exhausted.exception.code, "AGENT_BUDGET_EXCEEDED")
            self.assertEqual(product.data_adapter.session.metrics().tool_calls, 12)
            self.assertEqual(len(response_store.read("budgeted-run")), 12)
            records = [json.loads(line) for line in log_stream.getvalue().splitlines()]
            self.assertEqual(len(records), 13)
            self.assertEqual(records[-1]["error_code"], "AGENT_BUDGET_EXCEEDED")

    def test_invalid_retry_first_valid_and_later_rejection(self) -> None:
        product = adapter("run-1")
        server = ProductMcpStdioServer(product)
        invalid = call(server, "submit_answer", {**ANSWER, "source_ids": []})
        self.assertTrue(invalid["isError"])
        error = json.loads(invalid["content"][0]["text"])
        self.assertEqual(error["code"], "VALIDATION_ERROR")
        self.assertTrue(error["details"])
        self.assertEqual(product.submission.state, "UNSUBMITTED")
        delivered = call(server, "submit_answer", ANSWER)
        self.assertFalse(delivered["isError"])
        envelope = delivered["structuredContent"]
        self.assertEqual(envelope["delivery_status"], "DELIVERED")
        self.assertEqual(envelope["payload"]["answer"], "30일")
        self.assertEqual(envelope["source_link_status"], "NOT_CHECKED")
        self.assertEqual(envelope["run_id"], "run-1")
        self.assertNotIn("raw_model_prose", json.dumps(envelope))
        self.assertEqual(product.delivery_envelope().model_dump(mode="json"), envelope)
        later = call(server, "submit_answer", {**ANSWER, "answer": "다른 답"})
        self.assertEqual(json.loads(later["content"][0]["text"])["code"], "ALREADY_SUBMITTED")
        self.assertEqual(product.delivery_envelope().model_dump(mode="json"), envelope)

    def test_runs_have_distinct_submission_slots(self) -> None:
        first, second = adapter("run-A"), adapter("run-B")
        first.call_tool("submit_answer", ANSWER)
        self.assertEqual(first.delivery_envelope().delivery_status, "DELIVERED")
        self.assertEqual(second.delivery_envelope().reject_reason, "NO_SUBMISSION")
        second.call_tool("submit_answer", {**ANSWER, "answer": "B"})
        self.assertEqual(first.delivery_envelope().payload.answer, "30일")
        self.assertEqual(second.delivery_envelope().payload.answer, "B")
        with self.assertRaises(ProductToolError) as caught:
            first.call_tool("submit_answer", ANSWER)
        self.assertEqual(caught.exception.code, "ALREADY_SUBMITTED")

    def test_product_server_identity_and_no_submission_envelope(self) -> None:
        product = adapter("run-empty")
        server = ProductMcpStdioServer(product)
        response = server.handle({
            "jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {},
        })
        self.assertEqual(response["result"]["serverInfo"]["name"], "ax-product-tools")
        listed = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
        self.assertEqual([tool["name"] for tool in listed["result"]["tools"]],
                         list(PRODUCT_TOOL_NAMES))
        self.assertEqual(product.delivery_envelope().reject_reason, "NO_SUBMISSION")

    def test_product_and_evaluation_configs_are_separate(self) -> None:
        product = json.loads((ROOT / ".kiro/agents/ax-product.json").read_text(encoding="utf-8"))
        research = json.loads((ROOT / ".kiro/agents/ax-evaluation.json").read_text(encoding="utf-8"))
        expected = [f"@ax-product-tools/{name}" for name in PRODUCT_TOOL_NAMES]
        self.assertEqual(product["name"], "ax-product")
        self.assertEqual(product["tools"], expected)
        self.assertEqual(product["allowedTools"], expected)
        self.assertEqual(product["mcpServers"]["ax-product-tools"]["args"][:2],
                         ["-m", "ax_product.server"])
        self.assertEqual(product["mcpServers"]["ax-product-tools"]["env"]["AX_RUNTIME_DATASET"], "mini")
        research_expected = [f"@ax-tools/{name}" for name in AX_MCP_TOOL_NAMES]
        self.assertEqual(research["tools"], research_expected)
        self.assertEqual(research["allowedTools"], research_expected)
        self.assertEqual(research["mcpServers"]["ax-tools"]["args"][:2],
                         ["-m", "ax_mcp.server"])

    def test_stdio_process_keeps_submission_state_across_calls(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-m", "ax_product.server", "--run-id", "stdio-run", "--model", "test-model"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
            env={**os.environ, "AX_RUNTIME_DATASET": "mini", "PYTHONIOENCODING": "utf-8"},
        )
        try:
            def exchange(request_id: int, name: str, arguments: dict) -> dict:
                request = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}}
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
                return json.loads(process.stdout.readline())["result"]

            invalid = exchange(1, "submit_answer", {**ANSWER, "source_ids": []})
            valid = exchange(2, "submit_answer", ANSWER)
            repeated = exchange(3, "submit_answer", ANSWER)
            self.assertEqual(json.loads(invalid["content"][0]["text"])["code"], "VALIDATION_ERROR")
            self.assertEqual(valid["structuredContent"]["run_id"], "stdio-run")
            self.assertEqual(valid["structuredContent"]["payload"]["answer"], "30일")
            self.assertEqual(json.loads(repeated["content"][0]["text"])["code"], "ALREADY_SUBMITTED")
        finally:
            process.stdin.close()
            process.wait(timeout=5)
            remainder = process.stdout.read()
            stderr = process.stderr.read()
            process.stdout.close()
            process.stderr.close()
        self.assertEqual(remainder, "")
        self.assertEqual(stderr, "")


if __name__ == "__main__":
    unittest.main()
