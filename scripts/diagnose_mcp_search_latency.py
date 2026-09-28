from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ax_agent.models import TaskCategory
from ax_agent.tools import AgentToolLayer
from ax_mcp.adapter import AxMcpAdapter
from ax_mcp.telemetry import InvocationLogger


QUERIES = ("반품 가능 기간", "return policy period days")


def measure(operation: Callable[[], dict], iterations: int) -> tuple[list[float], dict]:
    samples: list[float] = []
    last_result: dict = {}
    for _ in range(iterations):
        started = time.perf_counter_ns()
        last_result = operation()
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return samples, last_result


def summarize(samples: list[float]) -> dict[str, float | int]:
    ordered = sorted(samples)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return {
        "iterations": len(samples),
        "min_ms": round(ordered[0], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_nearest_rank_ms": round(ordered[rank - 1], 3),
        "max_ms": round(ordered[-1], 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare direct and MCP-adapter search latency")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--output", type=Path, default=ROOT / "kiro_mcp_search_latency.json")
    args = parser.parse_args()
    if args.iterations < 1 or args.warmup < 0:
        parser.error("iterations must be positive and warmup must be non-negative")

    report = ROOT / "scan_report.json"
    source_root = ROOT / "sample_data" / "mini_company"
    direct = AgentToolLayer(report, source_root)
    comparisons: list[dict] = []
    with tempfile.TemporaryDirectory() as directory:
        adapter = AxMcpAdapter(report, source_root,
                               InvocationLogger(Path(directory) / "adapter-invocations.jsonl"))
        for query_index, query in enumerate(QUERIES):
            def direct_call() -> dict:
                session = direct.start_task(f"diagnostic-direct-{query_index}", TaskCategory.CROSS_FILE)
                return session.search_documents(query=query, top_k=5).model_dump(mode="json")

            def adapter_call() -> dict:
                return adapter.call_tool("search_documents", {"query": query, "top_k": 5})

            for _ in range(args.warmup):
                direct_call()
                adapter_call()
            direct_samples, direct_result = measure(direct_call, args.iterations)
            adapter_samples, adapter_result = measure(adapter_call, args.iterations)
            comparisons.append({
                "query": query,
                "query_length": len(query),
                "top_k": 5,
                "direct": summarize(direct_samples),
                "mcp_adapter": summarize(adapter_samples),
                "adapter_minus_direct_mean_ms": round(
                    statistics.fmean(adapter_samples) - statistics.fmean(direct_samples), 3),
                "results_identical": direct_result == adapter_result,
            })

    artifact = {
        "measured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "clock": "time.perf_counter_ns",
        "scope": "in-process direct ToolSession call versus AxMcpAdapter.call_tool",
        "adapter_logging": "JSONL file sink enabled",
        "iterations": args.iterations,
        "warmup": args.warmup,
        "comparisons": comparisons,
        "interpretation_limit": (
            "Does not include Kiro model inference, scheduling, pre-dispatch stdio waiting, "
            "or client rendering after the MCP response."
        ),
    }
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
