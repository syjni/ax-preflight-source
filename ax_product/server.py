"""Standalone product MCP stdio server. One process owns exactly one run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from ax_agent.errors import AgentToolError
from ax_mcp.runtime_dataset import (
    CONFIG_ENV, PROFILE_ENV, RuntimeDatasetError, resolve_runtime_dataset,
    runtime_identity, validate_runtime_resource_leakage,
)
from ax_mcp.server import AxMcpStdioServer, DEFAULT_PROTOCOL_VERSION
from ax_mcp.telemetry import InvocationLogger

from .adapter import ProductMcpAdapter, ProductToolError
from .evidence import EvidenceCheckStore, ToolResponseStore
from .evidence_v3 import check_run_v3
from .models import DeliveryEnvelope
from .results import ResultStore
from .tool_attempts import ToolAttemptStore


class ProductMcpStdioServer(AxMcpStdioServer):
    def __init__(self, adapter: ProductMcpAdapter):
        super().__init__(adapter)
        self.runtime_error_seen = False

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if message.get("method") == "initialize" and message.get("id") is not None:
            params = message.get("params") or {}
            return self._result(message["id"], {
                "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ax-product-tools", "version": "0.1.0"},
                "instructions": (
                    "Four company-evidence tools and submit_answer. "
                    "Only the first valid submit_answer payload is authoritative."
                ),
            })
        response = super().handle(message)
        if response is not None and response.get("error", {}).get("code") == -32603:
            self.runtime_error_seen = True
        return response

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments")
        try:
            if not isinstance(name, str):
                raise AgentToolError("INVALID_TOOL_NAME", "tools/call requires a string name")
            if arguments is not None and not isinstance(arguments, dict):
                raise AgentToolError("INVALID_ARGUMENTS", "tool arguments must be an object")
            output = self.adapter.call_tool(name, arguments)
            return {
                "content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False, separators=(",", ":"))}],
                "structuredContent": output,
                "isError": False,
            }
        except ValidationError as exc:
            error: dict[str, Any] = {
                "code": "VALIDATION_ERROR", "message": "MCP tool arguments failed AX schema validation",
                "details": json.loads(exc.json(include_url=False, include_input=False)),
            }
        except ProductToolError as exc:
            error = {"code": exc.code, "message": exc.message}
            if exc.details is not None:
                error["details"] = exc.details
        except AgentToolError as exc:
            error = {"code": exc.code, "message": exc.message}
        return {
            "content": [{"type": "text", "text": json.dumps(error, ensure_ascii=False, separators=(",", ":"))}],
            "isError": True,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one AX product MCP session over stdio")
    parser.add_argument("--run-id", help="unique run ID; defaults to a generated UUID")
    parser.add_argument("--task-id")
    parser.add_argument("--model", required=True)
    parser.add_argument("--dataset-profile", help=f"runtime profile; defaults to {PROFILE_ENV}")
    parser.add_argument("--dataset-config", type=Path, help=f"defaults to {CONFIG_ENV} or runtime_datasets.json")
    parser.add_argument("--scan-report", type=Path, help="explicit scan report; requires --source-root")
    parser.add_argument("--source-root", type=Path, help="explicit source root; requires --scan-report")
    parser.add_argument("--invocation-log", type=Path, help="data tool diagnostics; defaults to stderr")
    parser.add_argument("--results-root", type=Path,
                        help="result root containing a pre-reserved run directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    selected_profile = args.dataset_profile or os.environ.get(PROFILE_ENV)
    if selected_profile:
        if args.scan_report is not None or args.source_root is not None:
            parser.error("dataset profile cannot be combined with --scan-report or --source-root")
        try:
            dataset = resolve_runtime_dataset(selected_profile, args.dataset_config)
            runtime_identity(dataset)
            leakage = validate_runtime_resource_leakage(dataset)
        except RuntimeDatasetError as exc:
            parser.error(str(exc))
        if not leakage["passed"]:
            parser.error(f"runtime resource leakage validation failed: {leakage['violations']}")
        scan_report, source_root = dataset.scan_report, dataset.source_root
    elif args.scan_report is not None and args.source_root is not None:
        scan_report, source_root = args.scan_report, args.source_root
    else:
        parser.error(
            f"select a runtime dataset with {PROFILE_ENV}/--dataset-profile, "
            "or provide both --scan-report and --source-root"
        )
    run_id = args.run_id or str(uuid4())
    store = ResultStore(args.results_root) if args.results_root is not None else None
    if store is not None and not store.path(run_id).parent.is_dir():
        parser.error("results-root requires a pre-reserved run_id")
    response_store = ToolResponseStore(store.root) if store is not None else None
    attempt_store = ToolAttemptStore(store.root) if store is not None else None
    try:
        adapter = ProductMcpAdapter(
            scan_report, source_root, run_id=run_id,
            task_id=args.task_id, model=args.model,
            invocation_logger=InvocationLogger(args.invocation_log),
            response_store=response_store,
            attempt_store=attempt_store,
        )
    except ValueError as exc:
        parser.error(str(exc))
    completed = False
    server = ProductMcpStdioServer(adapter)
    try:
        exit_code = server.run()
        completed = exit_code == 0 and not server.runtime_error_seen
        return exit_code
    finally:
        if store is not None:
            envelope = adapter.delivery_envelope() if completed else DeliveryEnvelope(
                delivery_status="REJECTED", run_id=adapter.run_id,
                task_id=adapter.task_id, model=adapter.model,
                reject_reason="RUNTIME_ERROR",
            )
            store.write(envelope)
            result = check_run_v3(store.root, adapter.run_id)
            EvidenceCheckStore(store.root).write(result)


if __name__ == "__main__":
    raise SystemExit(main())
