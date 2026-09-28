"""Structural tool-access check for the new v4 candidate corpus; no model call."""

from __future__ import annotations

import json

from ax_agent.tools import AgentToolLayer
from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity, validate_runtime_resource_leakage
from scripts.build_v4_candidate import V4


def validate() -> dict:
    dataset = resolve_runtime_dataset("v4-candidate", V4 / "runtime_datasets.json")
    identity = runtime_identity(dataset)
    leakage = validate_runtime_resource_leakage(dataset)
    layer = AgentToolLayer(dataset.scan_report, dataset.source_root)
    session = layer.start_task("V4_STATIC_ACCESS_CHECK", "cross_file")
    queries = {
        "지역별 검수": "지역별_검수_2027.csv",
        "처리 기한 기준": "처리_기한_기준.txt",
        "접수 필수 항목": "접수_필수_항목.txt",
        "업무 책임팀": "업무_책임팀_2027.txt",
    }
    errors: list[str] = []
    found = {}
    for query, filename in queries.items():
        response = session.search_documents(query, top_k=5)
        hit = next((hit for hit in response.results if hit.title == filename), None)
        if hit is None:
            errors.append(f"source not discoverable: {filename}")
            continue
        found[filename] = hit
        if filename.endswith(".txt"):
            read = session.read_document(hit.document_id)
            if not read.content.strip():
                errors.append(f"source not readable: {filename}")
    table_hit = found.get("지역별_검수_2027.csv")
    if table_hit is None or len(table_hit.tables) != 1:
        errors.append("quality ledger table not registered")
    else:
        result = session.query_table(
            table_hit.tables[0].table_id,
            filters=[{"field": "region", "op": "eq", "value": "북부"}],
            aggregation={"op": "rate", "numerator_field": "defective_qty",
                         "denominator_field": "inspected_qty", "alias": "defect_rate"},
        )
        if len(result.rows) != 1 or abs(float(result.rows[0]["defect_rate"]) - 9 / 130) > 1e-12:
            errors.append("quality rate tool result mismatch")
    if identity["file_count"] != 4 or identity["parsed_file_count"] != 4 or identity["table_count"] != 1:
        errors.append("runtime inventory mismatch")
    if not leakage["passed"]:
        errors.append("runtime resource leakage")
    return {"passed": not errors, "sources_found": len(found), "tables": identity["table_count"],
            "runtime_leakage_passed": leakage["passed"], "errors": errors}


def main() -> int:
    result = validate()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
