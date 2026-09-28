from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from ax_mcp.runtime_dataset import resolve_runtime_dataset
from ax_product.api import RunRequest, create_app
from ax_product.console_contracts import BusinessTaskCatalog
from ax_product.onboarding import assess_onboarding


ROOT = Path(__file__).resolve().parents[1]
CATALOG = BusinessTaskCatalog.model_validate_json(
    (ROOT / "business_task_catalog.json").read_text(encoding="utf-8")
)


def test_valid_dataset_is_runnable_but_requires_task_review() -> None:
    assessment = assess_onboarding(resolve_runtime_dataset("mini"), CATALOG)

    assert assessment.status == "REVIEW_REQUIRED"
    assert assessment.can_run is True
    assert assessment.blocker_count == 0
    assert assessment.warning_count >= 1
    assert [check.code for check in assessment.checks] == [
        "DATASET_INTEGRITY",
        "PARSE_COVERAGE",
        "RETRIEVAL_SURFACE",
        "RUNTIME_RESOURCE_LEAKAGE",
        "BUSINESS_TASK_REVIEW",
    ]
    assert assessment.checks[-1].observed == 0
    assert assessment.checks[-1].total == len(CATALOG.tasks)
    assert assessment.checks[-1].status == "WARN"


def test_integrity_failure_blocks_api_run_before_runner(tmp_path: Path) -> None:
    source_root = tmp_path / "customer-data"
    shutil.copytree(ROOT / "sample_data" / "mini_company", source_root)
    scan_report = tmp_path / "scan-report.json"
    shutil.copyfile(ROOT / "scan_report.json", scan_report)
    config = tmp_path / "runtime-datasets.json"
    config.write_text(json.dumps({
        "schema_version": "ax-runtime-datasets-v1",
        "profiles": {
            "mini": {
                "dataset_name": "tampered-customer-data",
                "source_root": "customer-data",
                "scan_report": "scan-report.json",
                "dataset_manifest": None,
            },
        },
    }), encoding="utf-8")
    source = next(path for path in source_root.rglob("*") if path.is_file())
    source.write_bytes(source.read_bytes() + b"\nchanged-after-scan")

    class ForbiddenRunner:
        def run(
            self, request: RunRequest, *, run_id: str, results_root: Path
        ) -> None:
            raise AssertionError("blocked onboarding must not invoke the runner")

    client = TestClient(create_app(
        results_root=tmp_path / "results",
        dataset_config=config,
        runner=ForbiddenRunner(),
    ))
    onboarding = client.get("/api/onboarding/mini")
    assert onboarding.status_code == 200
    assert onboarding.json()["status"] == "BLOCKED"
    assert onboarding.json()["can_run"] is False
    assert onboarding.json()["blocker_count"] >= 1
    assert str(tmp_path) not in onboarding.text

    run = client.post("/api/run", json={
        "dataset": "mini",
        "request_type": "AD_HOC_QUESTION",
        "question": "반품 기간은 며칠인가요?",
    })
    assert run.status_code == 409
    assert run.json()["detail"] == "ONBOARDING_BLOCKED"
    assert not (tmp_path / "results").exists()
