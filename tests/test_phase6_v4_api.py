from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ax_product.api import (
    FROZEN_RESULTS_ROOT_ENV,
    PHASE6_FROZEN_V4_RESULTS_ROOT,
    create_read_only_app_from_env,
)


def fingerprint(root: Path) -> list[tuple[str, int, str]]:
    return [
        (
            path.relative_to(root).as_posix(),
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def test_v4_read_only_api_exposes_repeated_findings_without_writes() -> None:
    before = fingerprint(PHASE6_FROZEN_V4_RESULTS_ROOT)
    with patch.dict(os.environ, {
        FROZEN_RESULTS_ROOT_ENV: str(PHASE6_FROZEN_V4_RESULTS_ROOT),
    }, clear=True):
        client = TestClient(create_read_only_app_from_env())

    before_findings = client.get(
        "/api/findings/portfolio-hidden-conflict-before"
    ).json()
    after_findings = client.get(
        "/api/findings/portfolio-ceiling-after"
    ).json()

    assert before_findings["diagnostics"]["observed_run_count"] == 30
    assert after_findings["diagnostics"]["observed_run_count"] == 30
    assert before_findings["comparison_version"] == "v2"
    assert before_findings["legacy_diagnostics"]["inconclusive_task_count"] == 1
    assert any(
        item["finding_type"] == "MIXED_OUTCOMES"
        for item in before_findings["findings"]
    )
    assert any(
        item["finding_type"] == "CONFLICTING_SOURCES"
        and item["comparison_status"] == "NOT_REPRODUCED_AFTER"
        for item in after_findings["findings"]
    )
    run_id = "phase6v4-portfolio-ceiling-after-task_policy_return_window-r1"
    assert client.get(f"/api/runs/{run_id}/evidence-check").json()["verdict"] == "DIRECT_MATCH"
    assert client.post("/api/run", json={
        "dataset": "portfolio-ceiling-after",
        "request_type": "AD_HOC_QUESTION",
        "question": "현재 반품 가능 기간은 며칠인가요?",
        "run_id": "v4-read-only-must-not-write",
        "model": "test-model",
    }).status_code == 503
    assert fingerprint(PHASE6_FROZEN_V4_RESULTS_ROOT) == before


def test_v4_read_only_api_exposes_only_the_verified_featured_journey() -> None:
    with patch.dict(os.environ, {
        FROZEN_RESULTS_ROOT_ENV: str(PHASE6_FROZEN_V4_RESULTS_ROOT),
    }, clear=True):
        client = TestClient(create_read_only_app_from_env())

    response = client.get("/api/featured-cases")

    assert response.status_code == 200
    assert response.json()["schema_version"] == "ax-featured-cases-response-v1"
    cases = response.json()["featured_cases"]
    assert len(cases) == 1
    case = cases[0]
    assert case["before"]["run_id"] == (
        "phase6v4-portfolio-hidden-conflict-before-"
        "task_policy_return_window-r1"
    )
    assert case["after"]["run_id"] == (
        "phase6v4-portfolio-ceiling-after-task_policy_return_window-r1"
    )
    assert case["after"]["result"] == "3 / 3 답변"
    walkthrough = case["walkthrough"]
    assert walkthrough["label"] == "검증된 동결 예시"
    assert walkthrough["read_only"] is True
    assert walkthrough["snapshot_id"] == "phase6-v4"
    assert walkthrough["recommendation"] == "CONDITIONAL_GO"
    assert walkthrough["approved_task_id"] == "TASK_POLICY_RETURN_WINDOW"
    assert walkthrough["successful_runs"] == 3
    assert walkthrough["direct_evidence_runs"] == 3
    assert walkthrough["direct_evidence_ratio"] == 1.0
    assert walkthrough["cited_source_ids"]
    assert {item["code"] for item in walkthrough["gates"]} >= {
        "EXECUTION_SAMPLE", "DIRECT_EVIDENCE", "MODEL_BOUNDARY",
        "COST_CONTROL", "AUDIT_RETENTION",
    }
    assert client.get(f"/api/runs/{case['before']['run_id']}").status_code == 200
    assert client.get(f"/api/runs/{case['after']['run_id']}").status_code == 200
