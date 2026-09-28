"""Run-bound product MCP adapter with a persistent final-answer slot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ax_agent.errors import AgentToolError
from ax_mcp.adapter import AX_MCP_TOOL_NAMES, AxMcpAdapter
from ax_mcp.telemetry import InvocationLogger

from .delivery import SubmitAnswerSession
from .evidence import ToolResponseStore
from .models import DeliveryEnvelope, SubmitAnswerInput
from .tool_attempts import ToolAttemptStore


PRODUCT_TOOL_NAMES = (*AX_MCP_TOOL_NAMES, "submit_answer")


class ProductToolError(AgentToolError):
    def __init__(self, code: str, message: str, details: list[dict[str, str]] | None = None):
        super().__init__(code, message)
        self.details = details


class ProductMcpAdapter:
    """One instance per run; four data calls delegate to the existing adapter."""

    def __init__(
        self, scan_report: str | Path, source_root: str | Path, *,
        run_id: str, model: str, task_id: str | None = None,
        invocation_logger: InvocationLogger | None = None,
        response_store: ToolResponseStore | None = None,
        attempt_store: ToolAttemptStore | None = None,
    ) -> None:
        if not run_id.strip() or not model.strip() or (task_id is not None and not task_id.strip()):
            raise ValueError("run_id, model, and any task_id must be nonblank")
        self.run_id = run_id
        self.model = model
        self.task_id = task_id
        self.data_adapter = AxMcpAdapter(scan_report, source_root, invocation_logger)
        self.response_store = response_store
        self.attempt_store = attempt_store
        self.submission = SubmitAnswerSession()

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            *self.data_adapter.list_tools(),
            {
                "name": "submit_answer",
                "description": (
                    "Submit the final product answer. The first schema-valid submission wins. "
                    "On VALIDATION_ERROR, correct the listed fields and retry. "
                    "A later call returns ALREADY_SUBMITTED."
                ),
                "inputSchema": SubmitAnswerInput.model_json_schema(),
                "outputSchema": DeliveryEnvelope.model_json_schema(),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        if name in AX_MCP_TOOL_NAMES:
            try:
                output = self.data_adapter.call_tool(name, arguments)
                if self.response_store is not None:
                    self.response_store.record(
                        run_id=self.run_id, tool_name=name, output=output
                    )
            except Exception as exc:
                if self.attempt_store is not None:
                    error_code = (
                        "VALIDATION_ERROR"
                        if isinstance(exc, ValidationError)
                        else exc.code
                        if isinstance(exc, AgentToolError)
                        else "RUNTIME_ERROR"
                    )
                    self.attempt_store.record(
                        run_id=self.run_id,
                        tool_name=name,
                        arguments=arguments,
                        status="ERROR",
                        error_code=error_code,
                    )
                raise
            if self.attempt_store is not None:
                self.attempt_store.record(
                    run_id=self.run_id,
                    tool_name=name,
                    arguments=arguments,
                    status="SUCCESS",
                )
            return output
        if name != "submit_answer":
            raise ProductToolError("TOOL_NOT_FOUND", f"unknown product MCP tool: {name}")
        attempt = self.submission.submit(arguments)
        if attempt.error_code == "VALIDATION_ERROR":
            details = [
                {"field": field or "$", "message": message}
                for field, message in attempt.validation_errors
            ]
            raise ProductToolError(
                "VALIDATION_ERROR", "submit_answer failed AX product schema validation; correct and retry",
                details,
            )
        if attempt.error_code == "ALREADY_SUBMITTED":
            raise ProductToolError("ALREADY_SUBMITTED", "this run already has an accepted submission")
        return self.delivery_envelope().model_dump(mode="json")

    def delivery_envelope(self) -> DeliveryEnvelope:
        """Only this envelope, never assistant prose, is the product result."""
        return self.submission.envelope(
            run_id=self.run_id, task_id=self.task_id, model=self.model
        )
