from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from ax_product.api import RunRequest, create_app
from ax_product.evidence import ToolResponseStore
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.results import FinalResultExistsError, ResultStore, RunInProgressError
from ax_product.tool_attempts import ToolAttemptStore


ROOT = Path(__file__).resolve().parents[1]
ANSWER = {"status": "ANSWERED", "answer": "30 days", "unit": None,
          "explanation": "Test evidence", "source_ids": ["DOC_1"],
          "abstention_reason": None}
AD_HOC = {"dataset": "mini", "request_type": "AD_HOC_QUESTION",
          "question": "What is the return window?"}


class LocalMcpRunner:
    """Deterministic runner: local MCP calls only, no Kiro or Claude process."""

    def __init__(self, mode: str = "valid") -> None:
        self.mode = mode
        self.observed_stream: dict | None = None

    def run(self, request: RunRequest, *, run_id: str, results_root: Path) -> None:
        if self.mode == "error":
            raise RuntimeError("simulated runner failure")
        calls = []
        if self.mode in ("valid", "kiro_stream", "invalid"):
            calls.append({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "submit_answer",
                                     "arguments": {**ANSWER, "source_ids": []}}})
        if self.mode in ("valid", "kiro_stream"):
            calls.append({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                          "params": {"name": "submit_answer", "arguments": ANSWER}})
        command = [sys.executable, "-m", "ax_product.server", "--run-id", run_id,
                   "--model", request.model, "--dataset-profile", request.dataset,
                   "--dataset-config", str(ROOT / "runtime_datasets.json"),
                   "--results-root", str(results_root)]
        if request.task_id:
            command += ["--task-id", request.task_id]
        completed = subprocess.run(
            command, input="".join(json.dumps(call, ensure_ascii=False) + "\n" for call in calls),
            text=True, encoding="utf-8", capture_output=True, cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=20,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr)
        if self.mode == "prose_only":
            self.observed_stream = {"finalText": "30 days"}
        if self.mode in ("valid", "kiro_stream"):
            replies = [json.loads(line) for line in completed.stdout.splitlines()]
            assert replies[0]["result"]["isError"]
            if self.mode == "kiro_stream":
                # Observed Kiro stream shape: no structuredContent at this layer.
                self.observed_stream = {
                    "rawOutput": {"items": [{"Json": {"content": [
                        {"type": "text", "text": replies[1]["result"]["content"][0]["text"]}
                    ]}}]},
                    "finalText": "WRONG PROSE ANSWER",
                }
            else:
                assert replies[1]["result"].get("structuredContent", {}).get("payload", {}).get("answer") == "30 days", replies


class BlockingRunner:
    def __init__(self, fail: bool = False) -> None:
        self.started = Event()
        self.release = Event()
        self.fail = fail

    def run(self, request: RunRequest, *, run_id: str, results_root: Path) -> None:
        self.started.set()
        if not self.release.wait(timeout=10):
            raise RuntimeError("blocked runner timed out")
        if self.fail:
            raise RuntimeError("deterministic runner failure")
        ResultStore(results_root).write(DeliveryEnvelope(
            delivery_status="DELIVERED", run_id=run_id, task_id=None,
            model=request.model, payload=SubmitAnswerInput(**ANSWER),
            source_link_status="NOT_CHECKED",
        ))


class DeliveredThenRaiseRunner:
    def run(self, request: RunRequest, *, run_id: str, results_root: Path) -> None:
        ResultStore(results_root).write(DeliveryEnvelope(
            delivery_status="DELIVERED", run_id=run_id, task_id=None,
            model=request.model, payload=SubmitAnswerInput(**ANSWER),
            source_link_status="NOT_CHECKED",
        ))
        raise RuntimeError("cleanup failed after final delivery")


class AttemptTraceRunner:
    def run(self, request: RunRequest, *, run_id: str, results_root: Path) -> None:
        ToolAttemptStore(results_root).record(
            run_id=run_id,
            tool_name="search_documents",
            arguments={"top_k": 0},
            status="ERROR",
            error_code="VALIDATION_ERROR",
        )
        ToolAttemptStore(results_root).record(
            run_id=run_id,
            tool_name="read_document",
            arguments={"document_id": "DOC_1"},
            status="SUCCESS",
        )
        ToolResponseStore(results_root).record(
            run_id=run_id,
            tool_name="read_document",
            output={
                "document_id": "DOC_1",
                "title": "반품 정책",
                "content": "30 days",
                "truncated": False,
            },
        )
        ResultStore(results_root).write(DeliveryEnvelope(
            delivery_status="DELIVERED",
            run_id=run_id,
            task_id=None,
            model=request.model,
            payload=SubmitAnswerInput(**ANSWER),
            source_link_status="LINKED",
        ))


class ProductApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def client(self, mode: str = "valid") -> TestClient:
        return TestClient(create_app(results_root=self.root, runner=LocalMcpRunner(mode)))

    def test_dataset_list_is_curated_and_uses_runtime_registry_names(self) -> None:
        response = self.client().get("/api/datasets")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "ax-datasets-response-v1")
        self.assertEqual(
            [
                {
                    key: option[key]
                    for key in ("profile", "dataset_name", "display_label")
                }
                for option in payload["datasets"]
            ],
            [
                {
                    "profile": "mini",
                    "dataset_name": "mini-company-smoke",
                    "display_label": "Mini · 샘플 데이터",
                },
                {
                    "profile": "portfolio-hidden-conflict-before",
                    "dataset_name": "hanbit-portfolio-hidden-conflict-before-v1",
                    "display_label": "한빛유통 30개 파일 · Before",
                },
                {
                    "profile": "portfolio-ceiling-after",
                    "dataset_name": "hanbit-distribution-ceiling-v1",
                    "display_label": "한빛유통 30개 파일 · After",
                },
                {
                    "profile": "demo-return-before",
                    "dataset_name": "product-demo-return-before-v1",
                    "display_label": "반품 정책 · Before",
                },
                {
                    "profile": "demo-return-after",
                    "dataset_name": "product-demo-return-after-v1",
                    "display_label": "반품 정책 · After",
                },
            ],
        )
        self.assertTrue(
            all(option["origin"] == "BUNDLED" for option in payload["datasets"])
        )
        self.assertTrue(
            all(option["scanned_at"] is None for option in payload["datasets"])
        )
        self.assertTrue(
            all(option["source_root_name"] is None for option in payload["datasets"])
        )
        self.assertNotIn("before-accessibility-", response.text)
        self.assertNotIn('"ceiling"', response.text)

    def test_featured_cases_stay_empty_without_verified_frozen_runs(self) -> None:
        response = self.client().get("/api/featured-cases")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "schema_version": "ax-featured-cases-response-v1",
            "featured_cases": [],
        })

    def test_valid_submission_survives_mcp_exit_and_duplicate_is_rejected(self) -> None:
        client = self.client()
        request = {**AD_HOC, "run_id": "api-valid", "model": "fake-model"}
        response = client.post("/api/run", json=request)
        self.assertEqual(response.status_code, 200)
        envelope = response.json()
        self.assertEqual(envelope["delivery_status"], "DELIVERED")
        self.assertEqual(envelope["payload"]["answer"], "30 days")
        self.assertEqual(envelope["source_link_status"], "NOT_CHECKED")
        self.assertIsNone(envelope["task_id"])
        self.assertNotIn("score", envelope)
        self.assertEqual(client.get("/api/runs/api-valid").json(), envelope)
        evidence = client.get("/api/runs/api-valid/evidence-check")
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(evidence.json()["verdict"], "UNCONFIRMED")
        self.assertTrue(evidence.json()["unconfirmed_is_not_incorrect"])
        self.assertEqual(client.get("/api/runs/api-valid").json(), envelope)
        self.assertEqual(ResultStore(self.root).read("api-valid").model_dump(mode="json"), envelope)
        context = json.loads((self.root / "api-valid" / "run-context.json").read_text(encoding="utf-8"))
        self.assertEqual(context["task_label"], AD_HOC["question"])
        findings = client.get("/api/findings/mini")
        self.assertEqual(findings.status_code, 200)
        self.assertEqual(findings.json()["diagnostics"]["task_count"], 1)
        self.assertEqual(findings.json()["diagnostics"]["processable_task_count"], 1)
        self.assertEqual(client.post("/api/run", json=request).status_code, 409)

    def test_no_submission_invalid_only_and_runner_error_are_persisted(self) -> None:
        for mode, reason in (("none", "NO_SUBMISSION"),
                             ("invalid", "INVALID_SUBMISSION"),
                             ("error", "RUNTIME_ERROR")):
            with self.subTest(mode=mode):
                client = self.client(mode)
                run_id = f"api-{mode}"
                response = client.post("/api/run", json={**AD_HOC, "run_id": run_id})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["delivery_status"], "REJECTED")
                self.assertEqual(response.json()["reject_reason"], reason)
                self.assertEqual(client.get(f"/api/runs/{run_id}").json(), response.json())

    def test_kiro_stream_shape_and_final_text_do_not_drive_delivery(self) -> None:
        runner = LocalMcpRunner("kiro_stream")
        client = TestClient(create_app(results_root=self.root, runner=runner))
        delivered = client.post("/api/run", json={**AD_HOC, "run_id": "kiro-shape"}).json()
        self.assertEqual(delivered["payload"]["answer"], "30 days")
        self.assertNotIn("structuredContent", runner.observed_stream)
        raw = runner.observed_stream["rawOutput"]["items"][0]["Json"]["content"][0]["text"]
        self.assertEqual(json.loads(raw)["run_id"], "kiro-shape")
        self.assertNotEqual(delivered["payload"]["answer"], runner.observed_stream["finalText"])
        self.assertEqual(client.get("/api/runs/kiro-shape").json(), delivered)

        prose_runner = LocalMcpRunner("prose_only")
        prose_only = TestClient(create_app(results_root=self.root, runner=prose_runner))
        rejected = prose_only.post("/api/run", json={**AD_HOC, "run_id": "prose-only"}).json()
        self.assertEqual(prose_runner.observed_stream["finalText"], "30 days")
        self.assertEqual(rejected["reject_reason"], "NO_SUBMISSION")

    def test_retrieval_trace_endpoint_keeps_failed_attempt_order(self) -> None:
        client = TestClient(create_app(
            results_root=self.root,
            runner=AttemptTraceRunner(),
        ))
        delivered = client.post(
            "/api/run",
            json={**AD_HOC, "run_id": "attempt-trace"},
        )
        self.assertEqual(delivered.status_code, 200)

        trace = client.get("/api/runs/attempt-trace/retrieval-trace")
        self.assertEqual(trace.status_code, 200)
        self.assertEqual(trace.json()["schema_version"], "ax-retrieval-trace-v2")
        self.assertEqual(
            [step["status"] for step in trace.json()["steps"]],
            ["ERROR", "SUCCESS"],
        )
        self.assertEqual(
            trace.json()["steps"][0]["error_code"],
            "VALIDATION_ERROR",
        )

    def test_readiness_and_tasks_do_not_expose_ground_truth(self) -> None:
        client = self.client()
        readiness = client.get("/api/readiness/mini")
        self.assertEqual(readiness.status_code, 200)
        self.assertEqual(readiness.json()["readiness"]["schema_version"], "ax-readiness-score-v1")
        self.assertEqual(len(readiness.json()["unscored_observations"]), 1)
        observation = readiness.json()["unscored_observations"][0]
        self.assertEqual(observation["code"], "PROBABLE_VERSION_GROUP")
        self.assertEqual(observation["severity"], "warning")
        self.assertEqual(observation["file_ids"], [
            "FILE_2595481c695ba10d", "FILE_084aace9889c4091"])
        self.assertNotIn("score", observation)
        from readiness_score import score_scan_report_file
        self.assertEqual(readiness.json()["readiness"], score_scan_report_file(ROOT / "scan_report.json"))
        tasks = client.get("/api/tasks/ceiling")
        self.assertEqual(tasks.status_code, 200)
        self.assertEqual(tasks.json()["catalog_status"], "CANDIDATES_AVAILABLE")
        self.assertEqual(len(tasks.json()["tasks"]), 10)
        self.assertTrue(all(task["status"] == "CANDIDATE" for task in tasks.json()["tasks"]))
        self.assertNotIn("expected_answer", tasks.text)
        self.assertEqual(client.get("/api/tasks/no-such-profile").status_code, 404)
        self.assertEqual(client.get("/api/runs/no-such-run").status_code, 404)

    def test_parallel_runs_remain_separate(self) -> None:
        client = self.client()
        def submit(run_id: str) -> dict:
            return client.post("/api/run", json={**AD_HOC, "run_id": run_id}).json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(submit, ("parallel-a", "parallel-b")))
        self.assertEqual(first["run_id"], "parallel-a")
        self.assertEqual(second["run_id"], "parallel-b")
        self.assertEqual(first["delivery_status"], second["delivery_status"])
        self.assertEqual(len(list(self.root.glob("*/delivery.json"))), 2)

    def test_parallel_duplicate_run_id_has_one_owner(self) -> None:
        client = self.client()
        def submit(_: int) -> int:
            return client.post("/api/run", json={**AD_HOC, "run_id": "same-id"}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(submit, range(2)))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(ResultStore(self.root).read("same-id").delivery_status, "DELIVERED")

    def test_running_state_then_final_delivery_or_failure(self) -> None:
        for fail, final_status in ((False, "DELIVERED"), (True, "REJECTED")):
            with self.subTest(fail=fail):
                runner = BlockingRunner(fail)
                client = TestClient(create_app(results_root=self.root, runner=runner))
                run_id = "blocked-fail" if fail else "blocked-pass"
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(client.post, "/api/run", json={**AD_HOC, "run_id": run_id})
                    try:
                        self.assertTrue(runner.started.wait(timeout=5))
                        running = client.get(f"/api/runs/{run_id}")
                        self.assertEqual(running.status_code, 200)
                        self.assertEqual(running.json(), {"run_id": run_id, "run_status": "RUNNING",
                                                          "dataset": "mini"})
                        self.assertFalse(ResultStore(self.root).path(run_id).exists())
                        with self.assertRaises(RunInProgressError):
                            ResultStore(self.root).read(run_id)
                    finally:
                        runner.release.set()
                    final = future.result(timeout=5)
                self.assertEqual(final.status_code, 200)
                self.assertEqual(final.json()["delivery_status"], final_status)
                self.assertFalse((self.root / run_id / "state.json").exists())
                if fail:
                    self.assertEqual(final.json()["reject_reason"], "RUNTIME_ERROR")
                self.assertEqual(client.get(f"/api/runs/{run_id}").json(), final.json())

    def test_unavailable_runner_and_distinct_request_forms(self) -> None:
        client = TestClient(create_app(results_root=self.root))
        unavailable = client.post("/api/run", json={**AD_HOC, "run_id": "unavailable"})
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.json()["detail"], "RUNNER_UNAVAILABLE")
        self.assertFalse((self.root / "unavailable").exists())

        enabled = self.client()
        verified = enabled.post("/api/run", json={
            "dataset": "mini", "request_type": "VERIFIED_BUSINESS_TASK", "task_id": "TASK_1"})
        self.assertEqual(verified.status_code, 409)
        self.assertEqual(verified.json()["detail"], "VERIFIED_TASK_NOT_ONBOARDED")
        self.assertEqual(enabled.post("/api/run", json={"dataset": "mini", "task_id": "TASK_1"}).status_code, 422)
        self.assertEqual(enabled.post("/api/run", json={**AD_HOC, "task_id": "TASK_1"}).status_code, 422)
        self.assertEqual(enabled.post("/api/run", json={**AD_HOC, "expected_answer": "30 days"}).status_code, 422)

        candidate = enabled.post("/api/run", json={
            "dataset": "mini",
            "request_type": "TASK_CANDIDATE",
            "task_id": "TASK_POLICY_RETURN_WINDOW",
            "question": "현재 반품 가능 기간은 며칠인가요?",
            "run_id": "candidate-run",
        })
        self.assertEqual(candidate.status_code, 200)
        self.assertEqual(candidate.json()["task_id"], "TASK_POLICY_RETURN_WINDOW")
        candidate_findings = enabled.get("/api/findings/mini").json()
        self.assertGreaterEqual(candidate_findings["diagnostics"]["task_count"], 1)

        mismatch = enabled.post("/api/run", json={
            "dataset": "mini",
            "request_type": "TASK_CANDIDATE",
            "task_id": "TASK_POLICY_RETURN_WINDOW",
            "question": "바뀐 질문",
        })
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(mismatch.json()["detail"], "TASK_CANDIDATE_MISMATCH")

    def test_runner_cleanup_error_preserves_delivered_envelope(self) -> None:
        client = TestClient(create_app(results_root=self.root, runner=DeliveredThenRaiseRunner()))
        response = client.post("/api/run", json={**AD_HOC, "run_id": "cleanup-error"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["delivery_status"], "DELIVERED")
        self.assertEqual(response.json()["payload"]["answer"], "30 days")
        self.assertIsNone(response.json()["reject_reason"])
        path = ResultStore(self.root).path("cleanup-error")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), response.json())
        self.assertEqual(client.get("/api/runs/cleanup-error").json(), response.json())

    def test_final_envelope_is_write_once_even_with_concurrent_writers(self) -> None:
        store = ResultStore(self.root)
        store.reserve(run_id="write-once", task_id=None, model="fake-model", dataset="mini")
        delivered = DeliveryEnvelope(
            delivery_status="DELIVERED", run_id="write-once", model="fake-model",
            payload=SubmitAnswerInput(**ANSWER), source_link_status="NOT_CHECKED")
        rejected = DeliveryEnvelope(
            delivery_status="REJECTED", run_id="write-once", model="fake-model",
            reject_reason="RUNTIME_ERROR")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(store.write, envelope) for envelope in (delivered, rejected)]
            outcomes = []
            for future in futures:
                try:
                    future.result(timeout=5)
                    outcomes.append("written")
                except FinalResultExistsError:
                    outcomes.append("duplicate")
        self.assertEqual(sorted(outcomes), ["duplicate", "written"])
        winner = store.read("write-once")
        before = store.path("write-once").read_bytes()
        with self.assertRaises(FinalResultExistsError):
            store.write(winner)
        with self.assertRaises(FinalResultExistsError):
            store.write(delivered if winner.delivery_status == "REJECTED" else rejected)
        self.assertEqual(store.path("write-once").read_bytes(), before)

    def test_invalid_run_requires_explicit_gate_verdict(self) -> None:
        class InvalidGate:
            def assess(self, request: RunRequest, *, run_id: str) -> str:
                return "INVALID_RUN"

        class ForbiddenRunner:
            def run(self, request: RunRequest, *, run_id: str, results_root: Path) -> None:
                raise AssertionError("runner must not execute")

        client = TestClient(create_app(results_root=self.root, runner=ForbiddenRunner(), gate=InvalidGate()))
        result = client.post("/api/run", json={**AD_HOC, "run_id": "gated-invalid"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["reject_reason"], "INVALID_RUN")
        self.assertEqual(client.get("/api/runs/gated-invalid").json(), result.json())


if __name__ == "__main__":
    unittest.main()
