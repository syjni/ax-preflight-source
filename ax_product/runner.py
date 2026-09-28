"""Opt-in Kiro process runner for one isolated AX product run."""

from __future__ import annotations

import copy
import json
import math
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from .adapter import PRODUCT_TOOL_NAMES
from .request_validation import validate_runner_request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT_TEMPLATE = ROOT / ".kiro" / "agents" / "ax-product.json"
DEFAULT_DATASET_CONFIG = ROOT / "runtime_datasets.json"
DEFAULT_TIMEOUT_SECONDS = 300.0
PRODUCT_SERVER_NAME = "ax-product-tools"
PRODUCT_TOOL_REFS = tuple(f"@{PRODUCT_SERVER_NAME}/{name}" for name in PRODUCT_TOOL_NAMES)


class KiroRunnerError(RuntimeError):
    """Base class for failures of the external Kiro process."""


class KiroProcessError(KiroRunnerError):
    def __init__(self, returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"Kiro exited with status {returncode}: {stderr}")


class KiroTimeoutError(KiroRunnerError):
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Kiro timed out after {timeout_seconds:g} seconds")


def _read_template(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("product agent template must be a JSON object")
    expected = list(PRODUCT_TOOL_REFS)
    if value.get("tools") != expected or value.get("allowedTools") != expected:
        raise ValueError("product agent template must expose exactly the five product tools")
    servers = value.get("mcpServers")
    if not isinstance(servers, dict) or set(servers) != {PRODUCT_SERVER_NAME}:
        raise ValueError("product agent template must contain only ax-product-tools")
    if not isinstance(value.get("prompt"), str) or not value["prompt"]:
        raise ValueError("product agent template prompt must be nonblank")
    return value


def _resolve_executable(override: str | None) -> str:
    if override is not None:
        if not override.strip():
            raise FileNotFoundError("AX_KIRO_CLI must not be blank")
        return override
    executable = shutil.which("kiro-cli") or shutil.which("kiro-cli.exe")
    if executable is None:
        raise FileNotFoundError(
            "kiro-cli executable not found; set AX_KIRO_CLI or add it to PATH"
        )
    return executable


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate Kiro and its MCP descendants after a timeout."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        # Kiro starts the MCP server as its child. taskkill /T is the Windows
        # process-tree primitive; CREATE_NEW_PROCESS_GROUP isolates each run.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            # The direct kill below is still necessary if taskkill itself is
            # unavailable. Surface cleanup trouble through the caller only
            # after the root process has been stopped.
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            return
    if process.poll() is None:
        process.kill()


class KiroProductRunner:
    """Run one fresh Kiro product agent and wait for its MCP server to exit.

    Kiro output is deliberately ignored. The product MCP server is the only
    component allowed to publish the run's DeliveryEnvelope and tool responses.
    """

    def __init__(
        self,
        *,
        project_root: str | Path = ROOT,
        template_path: str | Path = DEFAULT_AGENT_TEMPLATE,
        agents_dir: str | Path | None = None,
        dataset_config: str | Path = DEFAULT_DATASET_CONFIG,
        executable: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        python_executable: str | Path = sys.executable,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        self.project_root = Path(project_root).resolve()
        self.template_path = Path(template_path).resolve()
        self.agents_dir = (
            Path(agents_dir).resolve()
            if agents_dir is not None
            else self.project_root / ".kiro" / "agents"
        )
        self.dataset_config = Path(dataset_config).resolve()
        self.executable = executable
        self.timeout_seconds = float(timeout_seconds)
        self.python_executable = str(Path(python_executable).resolve())

    def _agent_config(
        self, request: Any, *, run_id: str, results_root: Path, agent_name: str
    ) -> dict[str, Any]:
        template = _read_template(self.template_path)
        server_template = template["mcpServers"][PRODUCT_SERVER_NAME]
        if not isinstance(server_template, dict):
            raise ValueError("product MCP server template must be an object")
        args = [
            "-m", "ax_product.server",
            "--run-id", run_id,
            "--model", request.model,
            "--dataset-profile", request.dataset,
            "--dataset-config", str(self.dataset_config),
            "--results-root", str(results_root.resolve()),
        ]
        if request.task_id is not None:
            args.extend(["--task-id", request.task_id])
        server = {
            "command": self.python_executable,
            "args": args,
            "env": {
                "AX_RUNTIME_DATASET": request.dataset,
                "AX_RUNTIME_DATASET_CONFIG": str(self.dataset_config),
                "PYTHONPATH": str(self.project_root),
                "PYTHONIOENCODING": "utf-8",
            },
            "timeout": server_template.get("timeout", 10000),
        }
        # Copy only the product-specific fields. This prevents a future template
        # addition from silently granting another server, resource, or tool.
        return {
            "name": agent_name,
            "description": copy.deepcopy(template.get("description", "")),
            "model": request.model,
            "prompt": template["prompt"],
            "mcpServers": {PRODUCT_SERVER_NAME: server},
            "tools": list(PRODUCT_TOOL_REFS),
            "allowedTools": list(PRODUCT_TOOL_REFS),
            "resources": [],
            "includeMcpJson": False,
        }

    def _write_agent(self, config: dict[str, Any]) -> Path:
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        path = self.agents_dir / f"{config['name']}.json"
        try:
            with path.open("x", encoding="utf-8", newline="\n") as output:
                json.dump(config, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path

    def run(self, request: Any, *, run_id: str, results_root: Path) -> None:
        question = validate_runner_request(request)
        agent_name = f"ax-product-run-{uuid4().hex}"
        config = self._agent_config(
            request, run_id=run_id, results_root=results_root, agent_name=agent_name
        )
        agent_path = self._write_agent(config)
        process: subprocess.Popen[str] | None = None
        try:
            argv = [
                _resolve_executable(self.executable),
                "chat",
                "--agent", agent_name,
                "--require-mcp-startup",
                "--no-interactive",
                "--output-format", "stream-json",
                # Kiro CLI 2.23 rejects stream-json on its default v1 engine.
                "--agent-engine", "v2",
                question,
            ]
            popen_kwargs: dict[str, Any] = {
                "cwd": self.project_root,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "shell": False,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(argv, **popen_kwargs)
            try:
                _stdout, stderr = process.communicate(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _terminate_process_tree(process)
                try:
                    process.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise KiroTimeoutError(self.timeout_seconds) from exc
            except BaseException:
                # An I/O/decoding interruption must not leave Kiro or its MCP
                # child running after the HTTP request has failed.
                _terminate_process_tree(process)
                try:
                    process.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise
            if process.returncode != 0:
                raise KiroProcessError(process.returncode, stderr)
        finally:
            # The MCP server has exited before normal cleanup because communicate
            # waits for the complete process tree's inherited pipes to close.
            agent_path.unlink(missing_ok=True)
