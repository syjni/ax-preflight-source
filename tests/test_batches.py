from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from threading import Event, Lock

from fastapi.testclient import TestClient
from pydantic import ValidationError

from ax_product.api import create_app
from ax_product.batches import (
    BatchCreateRequest,
    BatchItem,
    BatchManager,
    BatchStatus,
    BatchStore,
)
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.results import ResultStore


ANSWER = {
    "status": "ANSWERED",
    "answer": "30 days",
    "unit": None,
    "explanation": "Deterministic batch test evidence",
    "source_ids": ["DOC_1"],
    "abstention_reason": None,
}
CANDIDATE = {
    "task_id": "TASK_POLICY_RETURN_WINDOW",
    "request_type": "TASK_CANDIDATE",
    "question": "현재 반품 가능 기간은 며칠인가요?",
}


class SequencedRunner:
    def __init__(self, *, fail_first: bool = False, block_first: bool = False) -> None:
        self.fail_first = fail_first
        self.block_first = block_first
        self.started = Event()
        self.release = Event()
        self._lock = Lock()
        self.calls: list[str] = []

    def run(self, request, *, run_id: str, results_root: Path) -> None:
        with self._lock:
            self.calls.append(run_id)
            call_number = len(self.calls)
        if call_number == 1:
            self.started.set()
            if self.block_first and not self.release.wait(timeout=10):
                raise RuntimeError("blocked runner timed out")
            if self.fail_first:
                raise RuntimeError("deterministic first-attempt failure")
        ResultStore(results_root).write(DeliveryEnvelope(
            delivery_status="DELIVERED",
            run_id=run_id,
            task_id=request.task_id,
            model=request.model,
            payload=SubmitAnswerInput(**ANSWER),
            source_link_status="NOT_CHECKED",
        ))


def wait_for_batch(
    client: TestClient, batch_id: str, expected: set[str], timeout: float = 5
) -> dict:
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/batches/{batch_id}")
        if response.status_code != 200:
            raise AssertionError(response.text)
        latest = response.json()
        if latest["state"] in expected:
            return latest
        time.sleep(0.01)
    raise AssertionError(f"batch did not reach {expected}: {latest}")


class BatchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.results_root = self.root / "runs"
        self.batch_root = self.root / "batches"

    def client(self, runner) -> TestClient:
        return TestClient(create_app(
            results_root=self.results_root,
            batch_root=self.batch_root,
            runner=runner,
        ))

    @staticmethod
    def request(*, batch_id: str, repetitions: int = 2, max_attempts: int = 2) -> dict:
        return {
            "batch_id": batch_id,
            "dataset": "mini",
            "model": "fake-model",
            "tasks": [{**CANDIDATE}],
            "repetitions": repetitions,
            "max_attempts": max_attempts,
        }

    def test_bounded_request_rejects_duplicate_or_oversized_task_sets(self) -> None:
        valid = BatchCreateRequest.model_validate({
            "dataset": "mini",
            "model": "fake-model",
            "tasks": [
                {
                    "task_id": f"TASK_{index}",
                    "request_type": "TASK_CANDIDATE",
                    "question": f"Question {index}?",
                }
                for index in range(10)
            ],
            "repetitions": 5,
        })
        self.assertEqual(len(valid.tasks) * valid.repetitions, 50)
        with self.assertRaises(ValidationError):
            BatchCreateRequest.model_validate({
                "dataset": "mini",
                "tasks": [CANDIDATE, CANDIDATE],
            })
        with self.assertRaises(ValidationError):
            BatchCreateRequest.model_validate({
                "dataset": "mini",
                "tasks": [
                    {
                        "task_id": f"TASK_{index}",
                        "request_type": "TASK_CANDIDATE",
                        "question": f"Question {index}?",
                    }
                    for index in range(11)
                ],
            })

    def test_batch_completes_with_durable_progress_and_distinct_runs(self) -> None:
        runner = SequencedRunner()
        client = self.client(runner)
        response = client.post(
            "/api/batches", json=self.request(batch_id="complete-batch")
        )
        self.assertEqual(response.status_code, 202, response.text)

        batch = wait_for_batch(client, "complete-batch", {"COMPLETED"})
        self.assertEqual(batch["progress_percent"], 100)
        self.assertEqual(batch["succeeded_items"], 2)
        self.assertEqual(batch["failed_items"], 0)
        self.assertEqual(len(set(runner.calls)), 2)
        self.assertEqual(
            {item["run_id"] for item in batch["items"]}, set(runner.calls)
        )
        persisted = BatchStore(self.batch_root).read("complete-batch")
        self.assertEqual(persisted.model_dump(mode="json"), batch)
        self.assertTrue(all(
            ResultStore(self.results_root).read(run_id).delivery_status == "DELIVERED"
            for run_id in runner.calls
        ))

    def test_partial_failure_retries_only_failed_item_with_new_run_id(self) -> None:
        runner = SequencedRunner(fail_first=True)
        client = self.client(runner)
        response = client.post(
            "/api/batches", json=self.request(batch_id="retry-batch")
        )
        self.assertEqual(response.status_code, 202, response.text)
        failed = wait_for_batch(
            client, "retry-batch", {"COMPLETED_WITH_ERRORS"}
        )
        self.assertEqual(failed["failed_items"], 1)
        self.assertEqual(failed["succeeded_items"], 1)
        failed_item = next(
            item for item in failed["items"] if item["status"] == "FAILED"
        )
        first_run_id = failed_item["run_id"]
        self.assertEqual(failed_item["error_code"], "RUNTIME_ERROR")

        retried = client.post("/api/batches/retry-batch/retry")
        self.assertEqual(retried.status_code, 200, retried.text)
        completed = wait_for_batch(client, "retry-batch", {"COMPLETED"})
        retried_item = next(
            item for item in completed["items"]
            if item["item_id"] == failed_item["item_id"]
        )
        self.assertEqual(retried_item["attempt"], 2)
        self.assertNotEqual(retried_item["run_id"], first_run_id)
        self.assertEqual(completed["succeeded_items"], 2)
        self.assertEqual(len(runner.calls), 3)
        self.assertEqual(
            client.post("/api/batches/retry-batch/retry").status_code, 409
        )

    def test_pause_finishes_active_item_then_resume_continues_queue(self) -> None:
        runner = SequencedRunner(block_first=True)
        client = self.client(runner)
        try:
            response = client.post(
                "/api/batches", json=self.request(batch_id="pause-batch")
            )
            self.assertEqual(response.status_code, 202, response.text)
            self.assertTrue(runner.started.wait(timeout=5))
            paused_requested = client.post("/api/batches/pause-batch/pause")
            self.assertEqual(paused_requested.status_code, 200)
            self.assertEqual(paused_requested.json()["state"], "PAUSE_REQUESTED")
        finally:
            runner.release.set()

        paused = wait_for_batch(client, "pause-batch", {"PAUSED"})
        self.assertEqual(paused["succeeded_items"], 1)
        self.assertEqual(paused["queued_items"], 1)
        self.assertEqual(len(runner.calls), 1)
        resumed = client.post("/api/batches/pause-batch/resume")
        self.assertEqual(resumed.status_code, 200)
        completed = wait_for_batch(client, "pause-batch", {"COMPLETED"})
        self.assertEqual(completed["succeeded_items"], 2)
        self.assertEqual(len(runner.calls), 2)

    def test_cancel_finishes_active_item_and_never_starts_queued_item(self) -> None:
        runner = SequencedRunner(block_first=True)
        client = self.client(runner)
        try:
            response = client.post(
                "/api/batches", json=self.request(batch_id="cancel-batch")
            )
            self.assertEqual(response.status_code, 202, response.text)
            self.assertTrue(runner.started.wait(timeout=5))
            cancelled_requested = client.post("/api/batches/cancel-batch/cancel")
            self.assertEqual(cancelled_requested.status_code, 200)
            self.assertEqual(
                cancelled_requested.json()["state"], "CANCEL_REQUESTED"
            )
        finally:
            runner.release.set()

        cancelled = wait_for_batch(client, "cancel-batch", {"CANCELLED"})
        self.assertEqual(cancelled["succeeded_items"], 1)
        self.assertEqual(cancelled["cancelled_items"], 1)
        self.assertEqual(cancelled["progress_percent"], 100)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(
            client.post("/api/batches/cancel-batch/cancel").status_code, 409
        )

    def test_safe_point_control_does_not_hide_a_completed_last_item(self) -> None:
        for action in ("pause", "cancel"):
            with self.subTest(action=action):
                runner = SequencedRunner(block_first=True)
                client = self.client(runner)
                batch_id = f"last-item-{action}"
                try:
                    response = client.post(
                        "/api/batches",
                        json=self.request(batch_id=batch_id, repetitions=1),
                    )
                    self.assertEqual(response.status_code, 202, response.text)
                    self.assertTrue(runner.started.wait(timeout=5))
                    requested = client.post(
                        f"/api/batches/{batch_id}/{action}"
                    )
                    self.assertEqual(requested.status_code, 200)
                finally:
                    runner.release.set()

                completed = wait_for_batch(client, batch_id, {"COMPLETED"})
                self.assertEqual(completed["succeeded_items"], 1)
                self.assertEqual(completed["cancelled_items"], 0)
                self.assertEqual(completed["progress_percent"], 100)

    def test_startup_recovers_interrupted_work_as_paused_failure(self) -> None:
        created_at = "2026-09-28T00:00:00Z"
        store = BatchStore(self.batch_root)
        store.create(BatchStatus(
            batch_id="restart-batch",
            dataset="mini",
            model="fake-model",
            state="RUNNING",
            requested_control="RUN",
            repetitions=2,
            max_attempts=2,
            created_at=created_at,
            updated_at=created_at,
            total_items=2,
            completed_items=0,
            succeeded_items=0,
            failed_items=0,
            cancelled_items=0,
            running_items=1,
            queued_items=1,
            progress_percent=0,
            items=[
                BatchItem(
                    item_id="t01-r01", task_id="TASK_1", task_label="Question?",
                    request_type="TASK_CANDIDATE", repetition=1, attempt=1,
                    status="RUNNING", run_id="restart-batch-t01-r01-a1",
                ),
                BatchItem(
                    item_id="t01-r02", task_id="TASK_1", task_label="Question?",
                    request_type="TASK_CANDIDATE", repetition=2, attempt=1,
                    status="QUEUED",
                ),
            ],
        ))

        BatchManager(
            store,
            lambda *_: (_ for _ in ()).throw(AssertionError("must not run")),
        )
        recovered = store.read("restart-batch")
        self.assertEqual(recovered.state, "PAUSED")
        self.assertEqual(recovered.requested_control, "PAUSE")
        self.assertEqual(recovered.failed_items, 1)
        self.assertEqual(recovered.queued_items, 1)
        self.assertEqual(
            recovered.items[0].error_code, "INTERRUPTED_BY_RESTART"
        )

    def test_preflight_rejections_create_no_batch_record(self) -> None:
        unavailable = self.client(None)
        response = unavailable.post(
            "/api/batches", json=self.request(batch_id="unavailable-batch")
        )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(self.batch_root.exists())

        enabled = self.client(SequencedRunner())
        invalid = self.request(batch_id="invalid-batch")
        invalid["tasks"][0]["question"] = "mismatched question"
        response = enabled.post("/api/batches", json=invalid)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "TASK_CANDIDATE_MISMATCH")
        self.assertFalse((self.batch_root / "invalid-batch").exists())

    def test_runner_free_app_recovers_stale_batch_but_cannot_resume_it(self) -> None:
        created_at = "2026-09-28T00:00:00Z"
        store = BatchStore(self.batch_root)
        store.create(BatchStatus(
            batch_id="live-elsewhere",
            dataset="mini",
            model="fake-model",
            state="RUNNING",
            requested_control="RUN",
            repetitions=1,
            max_attempts=2,
            created_at=created_at,
            updated_at=created_at,
            total_items=1,
            completed_items=0,
            succeeded_items=0,
            failed_items=0,
            cancelled_items=0,
            running_items=1,
            queued_items=0,
            progress_percent=0,
            items=[BatchItem(
                item_id="t01-r01", task_id="TASK_1", task_label="Question?",
                request_type="TASK_CANDIDATE", repetition=1, attempt=1,
                status="RUNNING", run_id="live-elsewhere-t01-r01-a1",
            )],
        ))

        read_only = self.client(None)
        self.assertEqual(
            read_only.get("/api/batches/live-elsewhere").json()["state"],
            "PAUSED",
        )
        recovered = store.read("live-elsewhere")
        self.assertEqual(recovered.items[0].status, "FAILED")
        self.assertEqual(
            recovered.items[0].error_code, "INTERRUPTED_BY_RESTART"
        )
        blocked = read_only.post("/api/batches/live-elsewhere/retry")
        self.assertEqual(blocked.status_code, 503)
        self.assertEqual(blocked.json()["detail"], "RUNNER_UNAVAILABLE")
        self.assertEqual(store.read("live-elsewhere").state, "PAUSED")


if __name__ == "__main__":
    unittest.main()
