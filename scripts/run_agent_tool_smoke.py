#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ax_agent.errors import AgentBudgetExceeded
from ax_agent.models import AgentOutput, TOOL_BUDGETS, TaskCategory
from ax_agent.tools import AgentToolLayer, tool_call_distribution, tool_schema_catalog


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_table(layer: AgentToolLayer, relative_path: str, sheet_name: str) -> str:
    file_ids = {record.file_id for record in layer.report.files if record.relative_path == relative_path}
    matches = [table.table_id for table in layer.report.tables
               if table.file_id in file_ids and table.sheet_name == sheet_name]
    if len(matches) != 1:
        raise RuntimeError(f"expected one table for {relative_path}/{sheet_name}, found {matches}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reproducible 9/20 Agent Tool experiment")
    parser.add_argument("--report", type=Path, default=ROOT / "scan_report.json")
    parser.add_argument("--source-root", type=Path, default=ROOT / "sample_data" / "mini_company")
    parser.add_argument("--output", type=Path, default=ROOT / "agent_tool_results.json")
    parser.add_argument("--schemas", type=Path, default=ROOT / "agent_tool_schemas.json")
    args = parser.parse_args()

    layer = AgentToolLayer(args.report, args.source_root)
    customers = find_table(layer, "tables/customers.csv", "CSV")
    orders = find_table(layer, "tables/orders.xlsx", "Orders")
    task_records, metrics = [], []

    knowledge = layer.start_task("K_RETURN_POLICY", TaskCategory.KNOWLEDGE)
    search = knowledge.search_documents("현재 반품 기간")
    read = knowledge.read_document(search.results[0].document_id) if search.results else None
    output = AgentOutput(final_answer="30", unit="days", explanation="현재본 반품 정책의 기간입니다.",
                         source_ids=[read.document_id] if read else [], abstain=False)
    metrics.append(knowledge.metrics())
    task_records.append({"task_id": knowledge.task_id, "output": output.model_dump(mode="json"),
                         "metrics": knowledge.metrics().model_dump(mode="json")})

    operations = layer.start_task("O_LAST_ORDER", TaskCategory.OPERATIONS)
    last_order = operations.query_table(orders,
        filters=[{"field": "customer_id", "op": "eq", "value": "C021"}],
        aggregation={"op": "max", "field": "order_date", "alias": "last_order_date"},
        select=["last_order_date"])
    output = AgentOutput(final_answer=last_order.rows[0]["last_order_date"], unit=None,
        explanation="주문 테이블에서 고객별 마지막 주문일을 집계했습니다.",
        source_ids=last_order.source_ids, abstain=False)
    metrics.append(operations.metrics())
    task_records.append({"task_id": operations.task_id, "output": output.model_dump(mode="json"),
                         "metrics": operations.metrics().model_dump(mode="json")})

    cross_file = layer.start_task("C_CUSTOMER_ORDER_SUM", TaskCategory.CROSS_FILE)
    customer = cross_file.lookup_value(customers, "customer_name", "(주) 한빛상사", "customer_id")
    total = cross_file.query_table(orders, filters=[
        {"field": "customer_id", "op": "eq", "value": customer.value},
        {"field": "order_date", "op": "prefix", "value": "2026-08"}],
        aggregation={"op": "sum", "field": "amount", "alias": "total_amount"},
        select=["total_amount"])
    output = AgentOutput(final_answer=total.rows[0]["total_amount"], unit="KRW",
        explanation="정규화된 고객명으로 고객 ID를 찾고 해당 주문액을 합산했습니다.",
        source_ids=[*customer.source_ids, *total.source_ids], abstain=False)
    metrics.append(cross_file.metrics())
    task_records.append({"task_id": cross_file.task_id, "output": output.model_dump(mode="json"),
                         "metrics": cross_file.metrics().model_dump(mode="json")})

    budget_probe = layer.start_task("K_BUDGET_PROBE", TaskCategory.KNOWLEDGE)
    for _ in range(6):
        budget_probe.search_documents("반품")
    rejected_code = None
    try:
        budget_probe.search_documents("반품")
    except AgentBudgetExceeded as exc:
        rejected_code = exc.code

    artifact = {
        "experiment": "9/20 Agent Tools + Context Policy",
        "scanner_contract": {"schema_version": layer.report.scan_metadata.schema_version,
            "scanner_version": layer.report.scan_metadata.scanner_version,
            "report": args.report.name, "scanner_refactored": False,
            "contract_hashes": {
                "scan_report.json": sha256(args.report),
                "scan_report.schema.json": sha256(ROOT / "scan_report.schema.json"),
                "ax_scanner/models.py": sha256(ROOT / "ax_scanner" / "models.py"),
                "ax_scanner/scanner.py": sha256(ROOT / "ax_scanner" / "scanner.py")}},
        "policies": {"search_default_top_k": 5, "search_max_top_k": 10,
            "read_document_max_characters": 2500, "query_table_max_rows": 10,
            "tool_budgets": {category.value: budget for category, budget in TOOL_BUDGETS.items()},
            "model_callable_tools": sorted(tool_schema_catalog())},
        "tasks": task_records,
        "observed_tool_call_distribution": tool_call_distribution(metrics),
        "budget_enforcement_probe": {"category": "knowledge",
            "executed_tool_calls": budget_probe.metrics().tool_calls,
            "rejected_call_error": rejected_code,
            "budget_exceeded": budget_probe.metrics().budget_exceeded},
        "cross_file_assertion": {"customer_input": "(주) 한빛상사",
            "normalized_lookup_result": customer.value, "order_total": total.rows[0]["total_amount"],
            "expected_order_total": 200000,
            "passed": customer.value == "C013" and total.rows[0]["total_amount"] == 200000,
            "actual_tool_calls": cross_file.metrics().tool_calls, "budget": cross_file.metrics().budget},
    }
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.schemas.write_text(json.dumps(tool_schema_catalog(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "schemas": str(args.schemas),
                      "cross_file_passed": artifact["cross_file_assertion"]["passed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
