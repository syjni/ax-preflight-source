from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ax_product.access_control import AccessControlStore
from ax_product.api import ROOT, create_app
from ax_product.batches import BatchItem, BatchStatus, BatchStore
from ax_product.local_datasets import LocalDatasetStore
from ax_product.results import ResultStore, RunInProgressError


class NeverCalledRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request, *, run_id: str, results_root: Path) -> None:
        self.calls += 1
        raise AssertionError("startup recovery must never call the runner")


class RuntimeRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runs = ResultStore(self.root / "runs")

    def reserve(self, run_id: str, *, instance: str = "runtime-old") -> None:
        self.runs.reserve(
            run_id=run_id,
            task_id=None,
            model="claude-sonnet-5",
            dataset="mini",
            runtime_instance_id=instance,
        )

    def test_recreating_app_finalizes_an_old_reservation_without_runner_call(self) -> None:
        self.reserve("orphan")
        runner = NeverCalledRunner()

        client = TestClient(create_app(
            results_root=self.runs.root,
            runner=runner,
            runtime_instance_id="runtime-new",
        ))

        recovered = client.get("/api/runs/orphan")
        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(recovered.json()["delivery_status"], "REJECTED")
        self.assertEqual(recovered.json()["reject_reason"], "INTERRUPTED_BY_RESTART")
        self.assertEqual(runner.calls, 0)
        self.assertFalse((self.runs.root / "orphan" / "state.json").exists())

    def test_recovery_is_idempotent_and_releases_the_dataset_reservation(self) -> None:
        self.reserve("orphan-once")
        first = self.runs.reconcile_interrupted("runtime-new")
        second = self.runs.reconcile_interrupted("runtime-new")

        self.assertEqual([item.run_id for item in first.recovered], ["orphan-once"])
        self.assertEqual(second.recovered, [])
        self.assertEqual(self.runs.inventory_for_datasets({"mini"}), (1, 0))
        self.runs.delete_for_datasets({"mini"})
        self.reserve("new-run", instance="runtime-new")
        with self.assertRaises(RunInProgressError):
            self.runs.read("new-run")

    def test_current_instance_reservation_is_not_recovered(self) -> None:
        self.reserve("current", instance="runtime-same")

        result = self.runs.reconcile_interrupted("runtime-same")

        self.assertEqual(result.recovered, [])
        with self.assertRaises(RunInProgressError):
            self.runs.read("current")

    def test_corrupt_reservation_is_quarantined_without_blocking_other_runs(self) -> None:
        self.reserve("healthy")
        self.reserve("corrupt")
        (self.runs.root / "corrupt" / "state.json").write_text(
            "{not-json", encoding="utf-8"
        )

        result = self.runs.reconcile_interrupted("runtime-new")

        self.assertEqual([item.run_id for item in result.recovered], ["healthy"])
        self.assertEqual(len(result.quarantined), 1)
        self.assertEqual(result.quarantined[0].run_id, "corrupt")
        self.assertTrue(result.quarantined[0].quarantine_path.is_dir())

    def test_batch_and_run_are_both_reconciled_conservatively(self) -> None:
        self.reserve("batch-one-t01-r01-a1")
        batches = BatchStore(self.root / "batches")
        batches.create(BatchStatus(
            batch_id="batch-one",
            dataset="mini",
            model="claude-sonnet-5",
            runtime_instance_id="runtime-old",
            state="RUNNING",
            requested_control="RUN",
            repetitions=1,
            max_attempts=2,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            total_items=1,
            completed_items=0,
            succeeded_items=0,
            failed_items=0,
            cancelled_items=0,
            running_items=1,
            queued_items=0,
            progress_percent=0,
            items=[BatchItem(
                item_id="t01-r01",
                task_id="TASK_ONE",
                task_label="승인 업무",
                request_type="VERIFIED_BUSINESS_TASK",
                repetition=1,
                attempt=1,
                status="RUNNING",
                run_id="batch-one-t01-r01-a1",
            )],
        ))

        TestClient(create_app(
            results_root=self.runs.root,
            batch_root=batches.root,
            runner=NeverCalledRunner(),
            runtime_instance_id="runtime-new",
        ))

        delivery = self.runs.read("batch-one-t01-r01-a1")
        batch = batches.read("batch-one")
        self.assertEqual(delivery.reject_reason, "INTERRUPTED_BY_RESTART")
        self.assertEqual(batch.state, "PAUSED")
        self.assertEqual(batch.items[0].status, "FAILED")
        self.assertEqual(batch.items[0].error_code, "INTERRUPTED_BY_RESTART")

    def test_recovery_event_is_recorded_once_and_project_can_be_purged(self) -> None:
        access = AccessControlStore(self.root / "access", secure_cookie=False)
        local = LocalDatasetStore(
            base_config=ROOT / "runtime_datasets.json",
            root=self.root / "local",
            allowed_scan_roots=[self.root],
        )
        source = self.root / "source"
        source.mkdir()
        (source / "policy.txt").write_text("반품은 30일 이내입니다.", encoding="utf-8")
        first = TestClient(create_app(
            results_root=self.runs.root,
            batch_root=self.root / "batches",
            local_dataset_store=local,
            access_control=access,
            runner=NeverCalledRunner(),
            runtime_instance_id="runtime-old",
        ))
        bootstrap = first.post("/api/auth/bootstrap", json={
            "username": "owner",
            "display_name": "Owner",
            "password": "Restart-Recovery!72",
            "project_name": "Recovery Project",
        })
        self.assertEqual(bootstrap.status_code, 201, bootstrap.text)
        headers = {"X-CSRF-Token": bootstrap.json()["csrf_token"]}
        project_id = first.get("/api/projects").json()[0]["project_id"]
        created = first.post("/api/local-datasets", json={
            "source_path": str(source), "project_id": project_id,
        }, headers=headers)
        self.assertEqual(created.status_code, 201, created.text)
        profile = created.json()["dataset"]["profile"]
        self.runs.reserve(
            run_id="project-orphan", task_id=None, model="claude-sonnet-5",
            dataset=profile, project_id=project_id,
            runtime_instance_id="runtime-old",
        )

        second = TestClient(create_app(
            results_root=self.runs.root,
            batch_root=self.root / "batches",
            local_dataset_store=local,
            access_control=access,
            runner=NeverCalledRunner(),
            runtime_instance_id="runtime-new",
        ))
        login = second.post("/api/auth/login", json={
            "username": "owner", "password": "Restart-Recovery!72",
        })
        self.assertEqual(login.status_code, 200, login.text)
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        audit_text = access.audit_path.read_text(encoding="utf-8")
        self.assertEqual(audit_text.count("RUN_INTERRUPTED_BY_RESTART"), 1)
        # A second reconciliation is a no-op and must not duplicate the audit event.
        self.runs.reconcile_interrupted("runtime-new")
        self.assertEqual(
            access.audit_path.read_text(encoding="utf-8").count(
                "RUN_INTERRUPTED_BY_RESTART"
            ),
            1,
        )
        deleted = second.delete(f"/api/local-datasets/{profile}", headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        purged = second.post(
            f"/api/projects/{project_id}/purge",
            json={"confirmation": "Recovery Project"},
            headers=headers,
        )
        self.assertEqual(purged.status_code, 200, purged.text)


if __name__ == "__main__":
    unittest.main()
