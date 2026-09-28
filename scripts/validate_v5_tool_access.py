"""Check v5 candidate evidence through the same local AX read tools, without Kiro."""

from __future__ import annotations

import json

from ax_agent.tools import AgentToolLayer
from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity, validate_runtime_resource_leakage
from scripts.build_v5_candidate import V5


def validate() -> dict:
    dataset = resolve_runtime_dataset("v5-candidate", V5 / "runtime_datasets.json")
    identity = runtime_identity(dataset)
    leakage = validate_runtime_resource_leakage(dataset)
    session = AgentToolLayer(dataset.scan_report, dataset.source_root).start_task(
        "V5_STATIC_ACCESS_CHECK", "cross_file")
    queries = {
        "반품심사 2028": "채널별_반품심사_2028.csv",
        "설비 조치 기준": "설비_조치_기준.txt",
        "등록 필수 증빙": "등록_필수_증빙.txt",
        "승인권한 2028": "승인권한_2028.txt",
    }
    errors: list[str] = []
    found = {}
    for query, filename in queries.items():
        response = session.search_documents(query, top_k=5)
        hit = next((value for value in response.results if value.title == filename), None)
        if hit is None:
            errors.append(f"source not discoverable: {filename}")
            continue
        found[filename] = hit
        if filename.endswith(".txt") and not session.read_document(hit.document_id).content.strip():
            errors.append(f"source not readable: {filename}")
    table_hit = found.get("채널별_반품심사_2028.csv")
    if table_hit is None or len(table_hit.tables) != 1:
        errors.append("return review table not registered")
    else:
        result = session.query_table(
            table_hit.tables[0].table_id,
            filters=[{"field": "channel", "op": "eq", "value": "온라인"}],
            aggregation={"op": "rate", "numerator_field": "approved_returns",
                         "denominator_field": "reviewed_returns", "alias": "approval_rate"},
        )
        if len(result.rows) != 1 or abs(float(result.rows[0]["approval_rate"]) - 21 / 250) > 1e-12:
            errors.append("return approval rate tool result mismatch")
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
