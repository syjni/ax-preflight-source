from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ax_product.api import (
    FROZEN_RESULTS_ROOT_ENV,
    PHASE6_FROZEN_V2_RESULTS_ROOT,
    PHASE6_FROZEN_RESULTS_ROOT,
    app,
    create_app,
    create_app_from_env,
    create_read_only_app_from_env,
)
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.results import ResultStore, ResultStoreConfigurationError


ROOT = Path(__file__).resolve().parents[1]
BEFORE_RUN = "phase6demo-official-official-001-01-before-489834b1"
AFTER_RUN = "phase6demo-official-official-001-02-after-02d170f8"
AFTER_RUNS = (
    AFTER_RUN,
    "phase6demo-official-official-001-04-after-7b4095d7",
    "phase6demo-official-official-001-06-after-233af967",
)
AD_HOC = {
    "dataset": "mini",
    "request_type": "AD_HOC_QUESTION",
    "question": "What is the return window?",
}


def _write_delivery(root: Path, run_id: str, *, dataset: str = "mini") -> dict:
    delivery = DeliveryEnvelope(
        delivery_status="DELIVERED",
        run_id=run_id,
        dataset=dataset,
        model="frozen-model",
        payload=SubmitAnswerInput(
            status="ANSWERED",
            answer="30 days",
            explanation="Frozen answer",
            source_ids=["DOC_FROZEN"],
        ),
        source_link_status="LINKED",
    ).model_dump(mode="json")
    directory = root / run_id
    directory.mkdir(parents=True)
    (directory / "delivery.json").write_text(
        json.dumps(delivery, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return delivery


def _write_evidence(root: Path, run_id: str) -> dict:
    evidence = {
        "schema_version": "ax-evidence-check-v1",
        "run_id": run_id,
        "verdict": "DIRECT_MATCH",
        "delivery_sha256": "0" * 64,
        "cited_source_ids": ["DOC_FROZEN"],
        "matched_source_ids": ["DOC_FROZEN"],
        "unmatched_source_ids": [],
        "evidence": [],
        "derivation": None,
        "limitations": [],
        "unconfirmed_is_not_incorrect": True,
    }
    (root / run_id / "evidence-check.json").write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def _fingerprint(root: Path) -> list[tuple[str, int, str, int]]:
    return [
        (
            path.relative_to(root).as_posix(),
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]


class WritableRunner:
    def __init__(self) -> None:
        self.results_root: Path | None = None

    def run(self, request, *, run_id: str, results_root: Path) -> None:
        self.results_root = results_root
        ResultStore(results_root).write(DeliveryEnvelope(
            delivery_status="DELIVERED",
            run_id=run_id,
            model=request.model,
            payload=SubmitAnswerInput(
                status="ANSWERED",
                answer="30 days",
                explanation="Writable answer",
                source_ids=["DOC_WRITABLE"],
            ),
            source_link_status="LINKED",
        ))


class FrozenResultsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.writable = self.root / "writable"
        self.frozen = self.root / "frozen"
        self.frozen.mkdir()

    def test_frozen_delivery_and_evidence_are_read_without_mutation(self) -> None:
        delivery = _write_delivery(self.frozen, "frozen-run")
        evidence = _write_evidence(self.frozen, "frozen-run")
        before = _fingerprint(self.frozen)
        client = TestClient(create_app(
            results_root=self.writable, frozen_results_root=self.frozen
        ))

        self.assertEqual(client.get("/api/runs/frozen-run").json(), delivery)
        self.assertEqual(
            client.get("/api/runs/frozen-run/evidence-check").json(), evidence
        )
        self.assertFalse(self.writable.exists())
        self.assertEqual(_fingerprint(self.frozen), before)

    def test_post_writes_only_writable_and_rejects_frozen_run_id(self) -> None:
        _write_delivery(self.frozen, "reserved-frozen")
        before = _fingerprint(self.frozen)
        runner = WritableRunner()
        client = TestClient(create_app(
            results_root=self.writable,
            frozen_results_root=self.frozen,
            runner=runner,
        ))

        response = client.post("/api/run", json={**AD_HOC, "run_id": "new-live"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(runner.results_root, self.writable.resolve())
        self.assertTrue((self.writable / "new-live" / "delivery.json").is_file())
        self.assertTrue((self.writable / "new-live" / "evidence-check.json").is_file())

        duplicate = client.post(
            "/api/run", json={**AD_HOC, "run_id": "reserved-frozen"}
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertFalse((self.writable / "reserved-frozen").exists())
        self.assertEqual(_fingerprint(self.frozen), before)

    def test_missing_frozen_evidence_returns_404_without_lazy_generation(self) -> None:
        delivery = _write_delivery(self.frozen, "no-evidence")
        before = _fingerprint(self.frozen)
        client = TestClient(create_app(
            results_root=self.writable, frozen_results_root=self.frozen
        ))

        self.assertEqual(client.get("/api/runs/no-evidence").json(), delivery)
        missing = client.get("/api/runs/no-evidence/evidence-check")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"], "evidence check not found")
        self.assertFalse((self.frozen / "no-evidence" / "evidence-check.json").exists())
        self.assertEqual(_fingerprint(self.frozen), before)

    def test_overlapping_roots_and_duplicate_run_ids_are_configuration_errors(self) -> None:
        with self.assertRaises(ResultStoreConfigurationError):
            create_app(results_root=self.frozen, frozen_results_root=self.frozen)

        nested_frozen = self.root / "outer-writable" / "frozen"
        nested_frozen.mkdir(parents=True)
        with self.assertRaises(ResultStoreConfigurationError):
            create_app(
                results_root=nested_frozen.parent,
                frozen_results_root=nested_frozen,
            )

        nested_writable = self.frozen / "nested-writable"
        nested_writable.mkdir()
        with self.assertRaises(ResultStoreConfigurationError):
            create_app(
                results_root=nested_writable,
                frozen_results_root=self.frozen,
            )

        _write_delivery(self.frozen, "duplicate-run")
        (self.writable / "duplicate-run").mkdir(parents=True)
        with self.assertRaises(ResultStoreConfigurationError):
            create_app(
                results_root=self.writable,
                frozen_results_root=self.frozen,
            )

    def test_default_app_remains_runner_unavailable(self) -> None:
        response = TestClient(app).post(
            "/api/run", json={**AD_HOC, "run_id": "frozen-default-unavailable"}
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "RUNNER_UNAVAILABLE")

    def test_verified_read_only_factory_serves_official_runs_and_rejects_post(self) -> None:
        before = _fingerprint(PHASE6_FROZEN_RESULTS_ROOT)
        with patch.dict(os.environ, {
            FROZEN_RESULTS_ROOT_ENV: str(PHASE6_FROZEN_RESULTS_ROOT),
        }, clear=True):
            client = TestClient(create_read_only_app_from_env())

        datasets = client.get("/api/datasets")
        self.assertEqual(datasets.status_code, 200)
        self.assertEqual(
            [item["profile"] for item in datasets.json()["datasets"]],
            [
                "mini",
                "portfolio-hidden-conflict-before",
                "portfolio-ceiling-after",
                "demo-return-before",
                "demo-return-after",
            ],
        )
        portfolio_before = client.get(
            "/api/findings/portfolio-hidden-conflict-before"
        ).json()
        self.assertEqual(portfolio_before["diagnostics"]["task_count"], 10)
        self.assertEqual(portfolio_before["diagnostics"]["processable_task_count"], 6)
        self.assertEqual(portfolio_before["diagnostics"]["blocked_task_count"], 4)
        portfolio_after = client.get("/api/findings/portfolio-ceiling-after").json()
        self.assertEqual(portfolio_after["diagnostics"]["processable_task_count"], 8)
        self.assertEqual(portfolio_after["diagnostics"]["blocked_task_count"], 2)
        self.assertTrue(any(
            item["comparison_status"] == "NOT_REPRODUCED_AFTER"
            for item in portfolio_after["findings"]
        ))
        self.assertEqual(client.get("/api/readiness/demo-return-before").status_code, 200)
        self.assertEqual(client.get("/api/tasks/demo-return-after").status_code, 200)
        self.assertEqual(client.get(f"/api/runs/{BEFORE_RUN}").status_code, 200)
        mini_findings = client.get("/api/findings/mini").json()
        self.assertEqual(mini_findings["diagnostics"]["observed_run_count"], 0)
        before_findings = client.get("/api/findings/demo-return-before").json()
        self.assertEqual(before_findings["diagnostics"]["blocked_task_count"], 1)
        self.assertEqual(before_findings["diagnostics"]["abstained_run_count"], 3)
        self.assertEqual(len(before_findings["findings"]), 1)
        self.assertEqual(before_findings["findings"][0]["finding_type"], "CONFLICTING_SOURCES")
        self.assertEqual(before_findings["findings"][0]["observed_run_count"], 3)
        self.assertEqual(
            {item["source_title"] for item in before_findings["findings"][0]["evidence"]},
            {"반품_정책_v1.txt", "반품_정책_v2.txt"},
        )
        after_findings = client.get("/api/findings/demo-return-after").json()
        self.assertEqual(after_findings["diagnostics"]["processable_task_count"], 1)
        self.assertEqual(after_findings["diagnostics"]["answered_run_count"], 3)
        self.assertEqual(after_findings["findings"][0]["comparison_status"], "NOT_REPRODUCED_AFTER")
        for run_id in AFTER_RUNS:
            evidence = client.get(f"/api/runs/{run_id}/evidence-check")
            self.assertEqual(evidence.status_code, 200)
            self.assertEqual(evidence.json()["verdict"], "DIRECT_MATCH")
        unavailable = client.post(
            "/api/run", json={**AD_HOC, "run_id": "read-only-post"}
        )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.json()["detail"], "RUNNER_UNAVAILABLE")
        self.assertEqual(_fingerprint(PHASE6_FROZEN_RESULTS_ROOT), before)

    def test_read_only_factory_rejects_unverified_frozen_path(self) -> None:
        with patch.dict(os.environ, {
            FROZEN_RESULTS_ROOT_ENV: str(self.frozen),
        }, clear=True):
            with self.assertRaises(RuntimeError):
                create_read_only_app_from_env()

    def test_read_only_factory_keeps_verified_v2_compatible(self) -> None:
        before = _fingerprint(PHASE6_FROZEN_V2_RESULTS_ROOT)
        with patch.dict(os.environ, {
            FROZEN_RESULTS_ROOT_ENV: str(PHASE6_FROZEN_V2_RESULTS_ROOT),
        }, clear=True):
            client = TestClient(create_read_only_app_from_env())
        self.assertEqual(client.get(f"/api/runs/{BEFORE_RUN}").status_code, 200)
        self.assertEqual(_fingerprint(PHASE6_FROZEN_V2_RESULTS_ROOT), before)

    def test_kiro_environment_factory_can_opt_in_to_frozen_reads(self) -> None:
        before = _fingerprint(PHASE6_FROZEN_RESULTS_ROOT)
        with patch.dict(os.environ, {
            "AX_PRODUCT_RUNNER": "kiro",
            "AX_KIRO_CLI": "kiro-from-env.exe",
            "AX_RUNTIME_DATASET_CONFIG": str(ROOT / "runtime_datasets.json"),
            FROZEN_RESULTS_ROOT_ENV: str(PHASE6_FROZEN_RESULTS_ROOT),
        }, clear=True):
            client = TestClient(create_app_from_env())

        self.assertEqual(client.get(f"/api/runs/{AFTER_RUN}").status_code, 200)
        self.assertEqual(_fingerprint(PHASE6_FROZEN_RESULTS_ROOT), before)


if __name__ == "__main__":
    unittest.main()
