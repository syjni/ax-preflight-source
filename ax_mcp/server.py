from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ax_agent.errors import AgentToolError

from .adapter import AxMcpAdapter
from .runtime_dataset import (
    CONFIG_ENV,
    PROFILE_ENV,
    RuntimeDatasetError,
    resolve_runtime_dataset,
    runtime_identity,
    validate_runtime_resource_leakage,
    write_runtime_identity_receipt,
)
from .telemetry import InvocationLogger


SERVER_NAME = "ax-agent-tools"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
ROOT = Path(__file__).resolve().parents[1]


class AxMcpStdioServer:
    def __init__(self, adapter: AxMcpAdapter):
        self.adapter = adapter

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return self._error(request_id, -32600, "Invalid Request") if request_id is not None else None
        if method.startswith("notifications/"):
            return None
        if request_id is None:
            return None
        try:
            if method == "initialize":
                params = message.get("params") or {}
                protocol = params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION
                return self._result(request_id, {
                    "protocolVersion": protocol,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": "Read-only AX company evidence tools. No filesystem, shell, Python, or SQL tools.",
                })
            if method == "ping":
                return self._result(request_id, {})
            if method == "tools/list":
                return self._result(request_id, {"tools": self.adapter.list_tools()})
            if method == "tools/call":
                return self._result(request_id, self._call_tool(message.get("params") or {}))
            return self._error(request_id, -32601, f"Method not found: {method}")
        except Exception as exc:
            return self._error(request_id, -32603, "Internal error", {"type": type(exc).__name__})

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments")
        try:
            if not isinstance(name, str):
                raise AgentToolError("INVALID_TOOL_NAME", "tools/call requires a string name")
            if arguments is not None and not isinstance(arguments, dict):
                raise AgentToolError("INVALID_ARGUMENTS", "tool arguments must be an object")
            output = self.adapter.call_tool(name, arguments)
            text = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
            return {
                "content": [{"type": "text", "text": text}],
                "structuredContent": output,
                "isError": False,
            }
        except ValidationError as exc:
            error = {"code": "VALIDATION_ERROR", "message": "MCP tool arguments failed AX schema validation",
                     "details": json.loads(exc.json(include_url=False, include_input=False))}
        except AgentToolError as exc:
            error = {"code": exc.code, "message": exc.message}
        text = json.dumps(error, ensure_ascii=False, separators=(",", ":"))
        return {"content": [{"type": "text", "text": text}], "isError": True}

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    def run(self) -> int:
        for raw_line in sys.stdin:
            if not raw_line.strip():
                continue
            try:
                message = json.loads(raw_line)
                response = self.handle(message)
            except (json.JSONDecodeError, TypeError):
                response = self._error(None, -32700, "Parse error")
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the read-only AX Agent Tool MCP server over stdio")
    parser.add_argument("--dataset-profile", help=f"runtime profile; defaults to {PROFILE_ENV}")
    parser.add_argument("--dataset-config", type=Path, help=f"profile config; defaults to {CONFIG_ENV} or runtime_datasets.json")
    parser.add_argument("--scan-report", type=Path, help="legacy explicit scan report; requires --source-root")
    parser.add_argument("--source-root", type=Path, help="legacy explicit source root; requires --scan-report")
    parser.add_argument("--runtime-identity-output", type=Path,
                        help="write the verified startup dataset identity as JSON")
    parser.add_argument("--invocation-log", type=Path,
                        default=Path(os.environ["AX_MCP_INVOCATION_LOG"])
                        if os.environ.get("AX_MCP_INVOCATION_LOG") else None,
                        help="Append invocation diagnostics as JSONL; defaults to stderr")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    selected_profile = args.dataset_profile or os.environ.get(PROFILE_ENV)
    if selected_profile:
        if args.scan_report is not None or args.source_root is not None:
            parser.error("dataset profile selection cannot be combined with --scan-report or --source-root")
        try:
            dataset = resolve_runtime_dataset(selected_profile, args.dataset_config)
            identity = runtime_identity(dataset)
            leakage = validate_runtime_resource_leakage(dataset)
        except RuntimeDatasetError as exc:
            parser.error(str(exc))
        if not leakage["passed"]:
            parser.error(f"runtime resource leakage validation failed: {leakage['violations']}")
        if args.runtime_identity_output is not None:
            write_runtime_identity_receipt(args.runtime_identity_output, identity, leakage)
        scan_report = dataset.scan_report
        source_root = dataset.source_root
    elif args.scan_report is not None and args.source_root is not None:
        if args.runtime_identity_output is not None:
            parser.error("--runtime-identity-output requires an explicit dataset profile")
        scan_report = args.scan_report
        source_root = args.source_root
    else:
        parser.error(
            f"select a runtime dataset with {PROFILE_ENV}/--dataset-profile, "
            "or provide both --scan-report and --source-root"
        )
    logger = InvocationLogger(args.invocation_log)
    return AxMcpStdioServer(AxMcpAdapter(scan_report, source_root, logger)).run()


if __name__ == "__main__":
    raise SystemExit(main())
