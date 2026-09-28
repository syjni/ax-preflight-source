"""Run dataset provenance survives reservation, delivery, and legacy reads."""

from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from ax_product.api import RunRequest, create_app
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.results import ResultStore


ANSWER = SubmitAnswerInput(
    status="ANSWERED", answer="fixture answer", explanation="Synthetic contract test",
    source_ids=["SOURCE_TEST_1"],
)


class ProvenanceRunner:
    def run(self, request: RunRequest, *, run_id: str, results_root: Path) -> None:
        # A runner-supplied profile must not override the API reservation.
        ResultStore(results_root).write(DeliveryEnvelope(
            delivery_status="DELIVERED", run_id=run_id, dataset="ceiling",
            model=request.model, payload=ANSWER, source_link_status="NOT_CHECKED",
        ))


class WaitingRunner:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def run(self, request: RunRequest, *, run_id: str, results_root: Path) -> None:
        self.started.set()
        if not self.release.wait(timeout=10):
            raise RuntimeError("timed out waiting for test release")
        ResultStore(results_root).write(DeliveryEnvelope(
            delivery_status="REJECTED", run_id=run_id, model=request.model,
            reject_reason="NO_SUBMISSION",
        ))


class RunProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_submit_and_lookup_use_persisted_request_dataset(self) -> None:
        client = TestClient(create_app(results_root=self.root, runner=ProvenanceRunner()))
        response = client.post("/api/run", json={
            "dataset": "mini", "request_type": "AD_HOC_QUESTION",
            "question": "Synthetic test question", "run_id": "new-run",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dataset"], "mini")
        self.assertEqual(response.json()["delivery_status"], "DELIVERED")
        self.assertEqual(client.get("/api/runs/new-run").json()["dataset"], "mini")
        stored = json.loads((self.root / "new-run" / "delivery.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["dataset"], "mini")
        self.assertFalse((self.root / "new-run" / "state.json").exists())

    def test_running_lookup_uses_reserved_dataset_and_final_keeps_it(self) -> None:
        runner = WaitingRunner()
        client = TestClient(create_app(results_root=self.root, runner=runner))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, "/api/run", json={
                "dataset": "ceiling", "request_type": "AD_HOC_QUESTION",
                "question": "Synthetic test question", "run_id": "running-run",
            })
            try:
                self.assertTrue(runner.started.wait(timeout=5))
                state = json.loads((self.root / "running-run" / "state.json").read_text(encoding="utf-8"))
                self.assertEqual(state["dataset"], "ceiling")
                self.assertEqual(client.get("/api/runs/running-run").json(), {
                    "run_id": "running-run", "run_status": "RUNNING", "dataset": "ceiling",
                })
            finally:
                runner.release.set()
            final = future.result(timeout=5)
        self.assertEqual(final.json()["dataset"], "ceiling")
        self.assertEqual(final.json()["reject_reason"], "NO_SUBMISSION")
        self.assertEqual(client.get("/api/runs/running-run").json()["dataset"], "ceiling")

    def test_legacy_result_and_running_state_are_unknown_without_rewrite(self) -> None:
        client = TestClient(create_app(results_root=self.root))
        old_final = self.root / "legacy-final" / "delivery.json"
        old_final.parent.mkdir()
        legacy = DeliveryEnvelope(
            delivery_status="DELIVERED", run_id="legacy-final", model="older-model",
            payload=ANSWER, source_link_status="NOT_CHECKED",
        ).model_dump(mode="json")
        legacy.pop("dataset")
        old_final.write_text(json.dumps(legacy), encoding="utf-8")
        before = old_final.read_bytes()
        fetched = client.get("/api/runs/legacy-final")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["dataset"], "UNKNOWN")
        self.assertEqual(fetched.json()["payload"]["answer"], "fixture answer")
        self.assertEqual(old_final.read_bytes(), before)

        old_state = self.root / "legacy-running" / "state.json"
        old_state.parent.mkdir()
        old_state.write_text(json.dumps({"run_id": "legacy-running", "run_status": "RUNNING"}),
                             encoding="utf-8")
        self.assertEqual(client.get("/api/runs/legacy-running").json(), {
            "run_id": "legacy-running", "run_status": "RUNNING", "dataset": "UNKNOWN",
        })


if __name__ == "__main__":
    unittest.main()
