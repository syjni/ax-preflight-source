"""Record the observed Kiro 2.22.1 automation feasibility decision."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("experiment/v3/automation-feasibility.json")


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _evidence(root: Path, directory: str) -> dict[str, Any]:
    base = root / "artifacts" / directory / "smoke-1"
    return {
        "directory": base.relative_to(root).as_posix(),
        "stdout_sha256": _sha(base / "kiro-stdout.jsonl"),
        "stderr_sha256": _sha(base / "kiro-stderr.txt"),
        "runtime_identity_receipt_exists": (base / "runtime-identity-receipt.json").is_file(),
    }


def create_record(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    return {
        "schema_version": "ax-v3-automation-feasibility-v1",
        "experiment_version": "ax-exp-v3",
        "kiro_cli_version": "kiro-cli-chat 2.22.1",
        "held_out_prompt_submitted": False,
        "held_out_valid_execution_count": 0,
        "tested_methods": [
            {
                "method": "default engine + --no-interactive + --output-format stream-json",
                "result": "UNSUPPORTED",
                "observation": "CLI rejected stream-json on the v1 engine before model execution.",
                "evidence": _evidence(root, "v3_automation_feasibility_2026-09-20"),
            },
            {
                "method": "--agent-engine v2 + --no-interactive + stream-json",
                "result": "FAILED",
                "observation": "runStarted was emitted, then prompt-stage Internal error; no persistent session or runtime receipt.",
                "evidence": _evidence(root, "v3_automation_feasibility_2026-09-20_attempt2"),
            },
            {
                "method": "--agent-engine v2 + --no-interactive + text output",
                "result": "FAILED",
                "observation": "CLI returned Internal error; no reliable session capture.",
                "evidence": _evidence(root, "v3_automation_feasibility_2026-09-20_attempt3"),
            },
            {
                "method": "default engine + --no-interactive + text output",
                "result": "INCONCLUSIVE_AND_UNSAFE",
                "observation": "Sandboxed request reported MCP/profile and network dispatch failure, returned a non-diagnostic exit status, and persisted no session or runtime receipt.",
                "evidence": _evidence(root, "v3_automation_feasibility_2026-09-20_attempt4"),
            },
            {
                "method": "network-enabled repeat of Dev-only non-interactive probe",
                "result": "NOT_RUN_SAFETY_REVIEW_REJECTED",
                "observation": "External runtime data-egress approval was not available; no workaround was attempted.",
                "evidence": None,
            },
        ],
        "deterministic_automated_backend_available": False,
        "decision": "Use SEMI_AUTOMATED_FRESH_PROCESS with authoritative session JSON/JSONL prompt verification.",
        "reason": "No tested non-interactive path provided a successful response, persistent one-turn session, and runtime identity receipt together.",
    }


def main() -> int:
    record = create_record(ROOT)
    output = ROOT / OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
