import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ax_product.access_control import AccessControlStore
from ax_product.api import ROOT, create_app
from ax_product.local_datasets import LocalDatasetStore
from ax_product.models import DeliveryEnvelope
from ax_product.results import ResultStore


class FailOnceAfterStage:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.triggered = False

    def __call__(self, _operation_id: str, stage: str, phase: str) -> None:
        if not self.triggered and stage == self.stage and phase == "after":
            self.triggered = True
            raise OSError(f"injected deletion failure after {stage}")


class DeletionLifecycleTests(unittest.TestCase):
    PROJECT_STAGES = (
        "AUDIT_REQUEST_RECORDED",
        "VALIDATED",
        "RUN_RESULTS_REMOVED",
        "BATCH_RESULTS_REMOVED",
        "MANAGED_DATA_REMOVED",
        "ACCESS_RECORDS_REMOVED",
        "VERIFIED",
    )

    def make_fixture(self, failure_stage: str | None = None):
        test_root = ROOT / ".test-tmp"
        test_root.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=test_root)
        root = Path(temporary.name)
        source = root / "customer-source"
        source.mkdir()
        (source / "policy.txt").write_text("반품은 30일 이내입니다.", encoding="utf-8")
        local_store = LocalDatasetStore(
            base_config=ROOT / "runtime_datasets.json",
            root=root / "local",
            allowed_scan_roots=[root],
        )
        access_store = AccessControlStore(root / "access", secure_cookie=False)
        failure = FailOnceAfterStage(failure_stage) if failure_stage else None
        app = create_app(
            results_root=root / "runs",
            batch_root=root / "batches",
            local_dataset_store=local_store,
            access_control=access_store,
            deletion_failure_injector=failure,
        )
        client = TestClient(app)
        bootstrap = client.post("/api/auth/bootstrap", json={
            "username": "delete.owner",
            "display_name": "삭제 책임자",
            "password": "Deletion-Lifecycle!72",
            "project_name": "삭제 복구 PoC",
        })
        self.assertEqual(bootstrap.status_code, 201, bootstrap.text)
        headers = {"X-CSRF-Token": bootstrap.json()["csrf_token"]}
        project_id = client.get("/api/projects").json()[0]["project_id"]
        scan = client.post(
            "/api/local-datasets",
            json={"source_path": str(source), "project_id": project_id},
            headers=headers,
        )
        self.assertEqual(scan.status_code, 201, scan.text)
        profile = scan.json()["dataset"]["profile"]
        return temporary, client, headers, source, project_id, profile

    def test_project_purge_recovers_from_failure_after_every_stage(self) -> None:
        for stage in self.PROJECT_STAGES:
            with self.subTest(stage=stage):
                temporary, client, headers, source, project_id, _profile = (
                    self.make_fixture(stage)
                )
                try:
                    partial = client.post(
                        f"/api/projects/{project_id}/purge",
                        json={"confirmation": "삭제 복구 PoC"},
                        headers=headers,
                    )
                    self.assertEqual(partial.status_code, 200, partial.text)
                    receipt = partial.json()
                    self.assertEqual(receipt["deletion_status"], "PARTIAL_FAILURE")
                    self.assertEqual(
                        receipt["project_deleted"],
                        stage in {"ACCESS_RECORDS_REMOVED", "VERIFIED"},
                    )
                    self.assertIn(stage, receipt["remaining_stages"])
                    self.assertTrue(receipt["remaining_records"])
                    self.assertFalse(receipt["source_files_deleted"])
                    self.assertTrue((source / "policy.txt").is_file())

                    resumed = client.post(
                        f"/api/projects/{project_id}/purge",
                        json={
                            "confirmation": "삭제 복구 PoC",
                            "operation_id": receipt["operation_id"],
                        },
                        headers=headers,
                    )
                    self.assertEqual(resumed.status_code, 200, resumed.text)
                    completed = resumed.json()
                    self.assertEqual(completed["deletion_status"], "COMPLETED")
                    self.assertTrue(completed["project_deleted"])
                    self.assertEqual(completed["remaining_stages"], [])
                    self.assertEqual(completed["operation_id"], receipt["operation_id"])
                    self.assertTrue((source / "policy.txt").is_file())

                    duplicate = client.post(
                        f"/api/projects/{project_id}/purge",
                        json={
                            "confirmation": "삭제 복구 PoC",
                            "operation_id": receipt["operation_id"],
                        },
                        headers=headers,
                    )
                    self.assertEqual(duplicate.status_code, 200, duplicate.text)
                    self.assertEqual(duplicate.json(), completed)
                    status = client.get(
                        f"/api/deletions/{receipt['operation_id']}"
                    )
                    self.assertEqual(status.status_code, 200, status.text)
                    self.assertEqual(status.json()["deletion_status"], "COMPLETED")
                finally:
                    client.close()
                    temporary.cleanup()

    def test_dataset_delete_returns_partial_receipt_and_resumes_without_source_loss(self) -> None:
        temporary, client, headers, source, project_id, profile = self.make_fixture(
            "MANAGED_DATA_REMOVED"
        )
        try:
            partial = client.delete(
                f"/api/local-datasets/{profile}", headers=headers
            )
            self.assertEqual(partial.status_code, 200, partial.text)
            receipt = partial.json()
            self.assertEqual(receipt["deletion_status"], "PARTIAL_FAILURE")
            # The registry removal succeeded, but verification/receipt finalization
            # still has to resume; the receipt reports both facts independently.
            self.assertTrue(receipt["deleted"])
            self.assertTrue((source / "policy.txt").is_file())

            cookies = [(cookie.name, cookie.value) for cookie in client.cookies.jar]
            restarted_app = create_app(
                results_root=source.parent / "runs",
                batch_root=source.parent / "batches",
                local_dataset_store=client.app.state.local_dataset_store,
                access_control=client.app.state.access_control,
            )
            restarted = TestClient(restarted_app)
            for name, value in cookies:
                restarted.cookies.set(name, value)
            resumed = restarted.delete(
                f"/api/local-datasets/{profile}",
                params={"operation_id": receipt["operation_id"]},
                headers=headers,
            )
            self.assertEqual(resumed.status_code, 200, resumed.text)
            completed = resumed.json()
            self.assertEqual(completed["deletion_status"], "COMPLETED")
            self.assertTrue(completed["deleted"])
            self.assertFalse(completed["source_files_deleted"])
            self.assertTrue((source / "policy.txt").is_file())
            self.assertFalse(restarted.app.state.local_dataset_store.contains(profile))
            self.assertTrue(restarted.app.state.access_control.project_exists(project_id))
            duplicate = restarted.delete(
                f"/api/local-datasets/{profile}",
                params={"operation_id": receipt["operation_id"]},
                headers=headers,
            )
            self.assertEqual(duplicate.status_code, 200, duplicate.text)
            self.assertEqual(duplicate.json(), completed)
            restarted.close()
        finally:
            client.close()
            temporary.cleanup()

    def test_dataset_delete_respects_legal_hold_and_running_state(self) -> None:
        temporary, client, headers, source, project_id, profile = self.make_fixture()
        try:
            hold = client.put(
                f"/api/projects/{project_id}/retention-policy",
                json={
                    "managed_data_days": 90,
                    "audit_event_days": 365,
                    "legal_hold": True,
                },
                headers=headers,
            )
            self.assertEqual(hold.status_code, 200, hold.text)
            held = client.delete(f"/api/local-datasets/{profile}", headers=headers)
            self.assertEqual(held.status_code, 409, held.text)
            self.assertEqual(held.json()["detail"], "PROJECT_LEGAL_HOLD")

            release = client.put(
                f"/api/projects/{project_id}/retention-policy",
                json={
                    "managed_data_days": 90,
                    "audit_event_days": 365,
                    "legal_hold": False,
                },
                headers=headers,
            )
            self.assertEqual(release.status_code, 200, release.text)
            writable = ResultStore(source.parent / "runs")
            writable.reserve(
                run_id="active-delete-run",
                task_id=None,
                model="test",
                dataset=profile,
                project_id=project_id,
            )
            in_use = client.delete(f"/api/local-datasets/{profile}", headers=headers)
            self.assertEqual(in_use.status_code, 409, in_use.text)
            self.assertEqual(in_use.json()["detail"], "DATASET_IN_USE")
            writable.write(DeliveryEnvelope(
                delivery_status="REJECTED",
                run_id="active-delete-run",
                model="test",
                dataset=profile,
                reject_reason="RUNTIME_ERROR",
            ))
            deleted = client.delete(f"/api/local-datasets/{profile}", headers=headers)
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertEqual(deleted.json()["deletion_status"], "COMPLETED")
            self.assertTrue((source / "policy.txt").is_file())
        finally:
            client.close()
            temporary.cleanup()

    def test_project_purge_never_removes_another_projects_dataset(self) -> None:
        temporary, client, headers, source, project_id, _profile = self.make_fixture()
        try:
            other_source = source.parent / "other-source"
            other_source.mkdir()
            (other_source / "other.txt").write_text("다른 프로젝트", encoding="utf-8")
            other_project = client.post(
                "/api/projects", json={"name": "유지 프로젝트"}, headers=headers
            )
            self.assertEqual(other_project.status_code, 201, other_project.text)
            other_id = other_project.json()["project_id"]
            other_scan = client.post(
                "/api/local-datasets",
                json={"source_path": str(other_source), "project_id": other_id},
                headers=headers,
            )
            self.assertEqual(other_scan.status_code, 201, other_scan.text)
            other_profile = other_scan.json()["dataset"]["profile"]

            purged = client.post(
                f"/api/projects/{project_id}/purge",
                json={"confirmation": "삭제 복구 PoC"},
                headers=headers,
            )
            self.assertEqual(purged.status_code, 200, purged.text)
            self.assertEqual(purged.json()["deletion_status"], "COMPLETED")
            self.assertEqual(client.get(f"/api/readiness/{other_profile}").status_code, 200)
            self.assertTrue((other_source / "other.txt").is_file())
        finally:
            client.close()
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
