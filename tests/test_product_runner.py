from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ax_mcp.runtime_dataset import resolve_runtime_dataset
from ax_mcp.telemetry import InvocationLogger
from ax_product.adapter import PRODUCT_TOOL_NAMES, ProductMcpAdapter, ProductToolError
from ax_product.api import RunRequest, app, create_app, create_app_from_env
from ax_product.evidence import EvidenceCheckStore, ToolResponseStore, check_run
from ax_product.results import ResultStore
from ax_product.runner import KiroProductRunner, PRODUCT_TOOL_REFS, _terminate_process_tree


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".kiro" / "agents" / "ax-product.json"
DATASET_CONFIG = ROOT / "runtime_datasets.json"
QUESTION = "현재 반품 가능 기간은 며칠인가요?"
REQUEST = {
    "dataset": "mini",
    "request_type": "AD_HOC_QUESTION",
    "question": QUESTION,
    "model": "test-product-model",
}
CANDIDATE_REQUEST = {
    "dataset": "mini",
    "request_type": "TASK_CANDIDATE",
    "task_id": "TASK_POLICY_RETURN_WINDOW",
    "question": QUESTION,
    "model": "test-product-model",
}


class FakeKiroProcess:
    next_pid = 41000

    def __init__(self, argv: list[str], kwargs: dict, callback=None, *, returncode: int = 0,
                 stdout: str = "", stderr: str = "", timeout: bool = False) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.callback = callback
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timeout = timeout
        self.communications = 0
        self.killed = False
        self.pid = FakeKiroProcess.next_pid
        FakeKiroProcess.next_pid += 1

    def communicate(self, timeout=None):
        self.communications += 1
        if self.timeout and self.communications == 1:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        if self.callback is not None and self.communications == 1:
            self.callback(self.argv)
        return self.stdout, self.stderr

    def poll(self):
        return self.returncode if self.killed or self.communications else None

    def kill(self):
        self.killed = True
        if self.returncode == 0:
            self.returncode = -9


class KiroRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.temp_root = Path(self.temporary.name)
        self.results_root = self.temp_root / "results"
        self.agents_dir = self.temp_root / "agents"
        self.processes: list[FakeKiroProcess] = []

    def runner(self, *, timeout_seconds: float = 30) -> KiroProductRunner:
        return KiroProductRunner(
            project_root=ROOT,
            template_path=TEMPLATE,
            agents_dir=self.agents_dir,
            dataset_config=DATASET_CONFIG,
            executable="kiro-cli-test.exe",
            timeout_seconds=timeout_seconds,
        )

    def popen_factory(self, callback=None, *, returncode=0, stdout="", stderr="", timeout=False):
        def factory(argv, **kwargs):
            process = FakeKiroProcess(
                argv, kwargs, callback, returncode=returncode,
                stdout=stdout, stderr=stderr, timeout=timeout,
            )
            self.processes.append(process)
            return process
        return factory

    def config_from_argv(self, argv: list[str]) -> dict:
        name = argv[argv.index("--agent") + 1]
        return json.loads((self.agents_dir / f"{name}.json").read_text(encoding="utf-8"))

    @staticmethod
    def _arg(args: list[str], name: str) -> str:
        return args[args.index(name) + 1]

    def test_configuration_check_does_not_contact_model_or_trust_missing_override(self) -> None:
        with patch("ax_product.runner.shutil.which", return_value=None):
            self.assertFalse(self.runner().configuration_available())
        with patch("ax_product.runner.shutil.which", return_value="C:/tools/kiro-cli-test.exe"):
            self.assertTrue(self.runner().configuration_available())

        malformed = self.temp_root / "malformed-agent.json"
        malformed.write_text("{}", encoding="utf-8")
        runner = KiroProductRunner(
            project_root=ROOT,
            template_path=malformed,
            agents_dir=self.agents_dir,
            dataset_config=DATASET_CONFIG,
            executable="kiro-cli-test.exe",
        )
        with patch("ax_product.runner.shutil.which", return_value="C:/tools/kiro-cli-test.exe"):
            self.assertFalse(runner.configuration_available())

    def publish(self, argv: list[str], mode: str) -> None:
        config = self.config_from_argv(argv)
        server = config["mcpServers"]["ax-product-tools"]
        args = server["args"]
        run_id = self._arg(args, "--run-id")
        model = self._arg(args, "--model")
        dataset_profile = self._arg(args, "--dataset-profile")
        results_root = Path(self._arg(args, "--results-root"))
        task_id = self._arg(args, "--task-id") if "--task-id" in args else None
        selected = resolve_runtime_dataset(
            dataset_profile, Path(self._arg(args, "--dataset-config"))
        )
        adapter = ProductMcpAdapter(
            selected.scan_report,
            selected.source_root,
            run_id=run_id,
            model=model,
            task_id=task_id,
            invocation_logger=InvocationLogger(stream=io.StringIO()),
            response_store=ToolResponseStore(results_root),
        )
        if mode == "valid":
            output = adapter.call_tool(
                "search_documents", {"query": "현재 반품 기간", "top_k": 5}
            )
            source_id = output["results"][0]["document_id"]
            adapter.call_tool("submit_answer", {
                "status": "ANSWERED",
                "answer": "30일",
                "unit": None,
                "explanation": "현재 반품 기간은 30일입니다.",
                "source_ids": [source_id],
                "abstention_reason": None,
            })
        elif mode == "invalid":
            with self.assertRaises(ProductToolError):
                adapter.call_tool("submit_answer", {
                    "status": "ANSWERED", "answer": "30일", "unit": None,
                    "explanation": "잘못된 제출", "source_ids": [],
                    "abstention_reason": None,
                })
        elif mode != "none":
            raise AssertionError(mode)
        ResultStore(results_root).write(adapter.delivery_envelope())
        EvidenceCheckStore(results_root).write(check_run(results_root, run_id))

    def test_agent_routes_run_dataset_model_results_and_exact_question_safely(self) -> None:
        malicious = '기간?; Write-Output "OWNED"; $(Get-ChildItem)'
        request = RunRequest(**{**REQUEST, "question": malicious})
        ResultStore(self.results_root).reserve(
            run_id="route-run", task_id=None, model=request.model, dataset=request.dataset
        )
        observed: dict = {}

        def callback(argv):
            config = self.config_from_argv(argv)
            observed.update(config)
            args = config["mcpServers"]["ax-product-tools"]["args"]
            self.assertEqual(self._arg(args, "--run-id"), "route-run")
            self.assertEqual(self._arg(args, "--model"), request.model)
            self.assertEqual(self._arg(args, "--dataset-profile"), "mini")
            self.assertEqual(Path(self._arg(args, "--dataset-config")), DATASET_CONFIG)
            self.assertEqual(Path(self._arg(args, "--results-root")), self.results_root.resolve())
            self.publish(argv, "none")

        with patch("ax_product.runner.subprocess.Popen", self.popen_factory(callback)):
            self.runner().run(request, run_id="route-run", results_root=self.results_root)
        process = self.processes[0]
        self.assertEqual(process.argv[-1], malicious)
        self.assertEqual(process.argv[:-1], [
            "kiro-cli-test.exe", "chat", "--agent", observed["name"],
            "--require-mcp-startup", "--no-interactive",
            "--output-format", "stream-json",
            "--agent-engine", "v2",
        ])
        self.assertIs(process.kwargs["shell"], False)
        self.assertIs(process.kwargs["stdin"], subprocess.DEVNULL)
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(observed["prompt"], template["prompt"])
        self.assertEqual(observed["model"], request.model)
        self.assertEqual(observed["tools"], list(PRODUCT_TOOL_REFS))
        self.assertEqual(observed["allowedTools"], list(PRODUCT_TOOL_REFS))
        self.assertEqual(len(observed["tools"]), 5)
        self.assertEqual(list(observed["mcpServers"]), ["ax-product-tools"])
        self.assertEqual(tuple(name.rsplit("/", 1)[1] for name in observed["tools"]),
                         PRODUCT_TOOL_NAMES)
        self.assertEqual(list(self.agents_dir.glob("*.json")), [])

    def test_candidate_api_uses_real_runner_and_preserves_question_and_task_id(self) -> None:
        observed_server_args: list[str] = []

        def callback(argv: list[str]) -> None:
            config = self.config_from_argv(argv)
            observed_server_args.extend(
                config["mcpServers"]["ax-product-tools"]["args"]
            )
            self.publish(argv, "valid")

        client = TestClient(create_app(results_root=self.results_root, runner=self.runner()))
        with patch(
            "ax_product.runner.subprocess.Popen", self.popen_factory(callback)
        ):
            response = client.post(
                "/api/run", json={**CANDIDATE_REQUEST, "run_id": "candidate-live"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["delivery_status"], "DELIVERED")
        self.assertEqual(response.json()["task_id"], CANDIDATE_REQUEST["task_id"])
        self.assertEqual(self.processes[0].argv[-1], CANDIDATE_REQUEST["question"])
        self.assertEqual(
            self._arg(observed_server_args, "--task-id"), CANDIDATE_REQUEST["task_id"]
        )
        context = json.loads(
            (self.results_root / "candidate-live" / "run-context.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(context["task_id"], CANDIDATE_REQUEST["task_id"])
        self.assertEqual(context["task_label"], CANDIDATE_REQUEST["question"])
        self.assertEqual(context["request_type"], "TASK_CANDIDATE")

    def test_candidate_catalog_mismatch_is_rejected_before_real_runner_starts(self) -> None:
        client = TestClient(create_app(results_root=self.results_root, runner=self.runner()))
        with patch("ax_product.runner.subprocess.Popen") as popen:
            response = client.post(
                "/api/run",
                json={
                    **CANDIDATE_REQUEST,
                    "question": "카탈로그와 다른 질문",
                    "run_id": "candidate-mismatch",
                },
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "TASK_CANDIDATE_MISMATCH")
        popen.assert_not_called()
        self.assertFalse((self.results_root / "candidate-mismatch").exists())

    def test_final_text_is_ignored_and_only_accepted_submission_is_delivered(self) -> None:
        final_text = json.dumps({"type": "runFinished", "data": {"finalText": "30일"}})
        no_submit = TestClient(create_app(results_root=self.results_root, runner=self.runner()))
        with patch("ax_product.runner.subprocess.Popen", self.popen_factory(
            lambda argv: self.publish(argv, "none"), stdout=final_text
        )):
            rejected = no_submit.post("/api/run", json={**REQUEST, "run_id": "final-text-only"})
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["reject_reason"], "NO_SUBMISSION")

        delivered_client = TestClient(
            create_app(results_root=self.results_root, runner=self.runner())
        )
        with patch("ax_product.runner.subprocess.Popen", self.popen_factory(
            lambda argv: self.publish(argv, "valid"), stdout=final_text
        )):
            delivered = delivered_client.post(
                "/api/run", json={**REQUEST, "run_id": "accepted-only"}
            )
        self.assertEqual(delivered.status_code, 200)
        body = delivered.json()
        self.assertEqual(body["delivery_status"], "DELIVERED")
        self.assertEqual(body["payload"]["answer"], "30일")
        self.assertEqual(len(body["payload"]["source_ids"]), 1)
        records = ToolResponseStore(self.results_root).read("accepted-only")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].run_id, "accepted-only")
        evidence = delivered_client.get("/api/runs/accepted-only/evidence-check").json()
        self.assertEqual(evidence["cited_source_ids"], body["payload"]["source_ids"])
        self.assertEqual(evidence["matched_source_ids"], body["payload"]["source_ids"])

    def test_no_submission_invalid_submission_and_nonzero_exit_contracts(self) -> None:
        cases = [
            ("no-submit", lambda argv: self.publish(argv, "none"), 0, "NO_SUBMISSION"),
            ("invalid", lambda argv: self.publish(argv, "invalid"), 0, "INVALID_SUBMISSION"),
            ("nonzero", None, 17, "RUNTIME_ERROR"),
        ]
        for run_id, callback, returncode, reason in cases:
            with self.subTest(run_id=run_id):
                client = TestClient(create_app(results_root=self.results_root, runner=self.runner()))
                with patch("ax_product.runner.subprocess.Popen", self.popen_factory(
                    callback, returncode=returncode, stderr="literal process failure"
                )):
                    response = client.post("/api/run", json={**REQUEST, "run_id": run_id})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["delivery_status"], "REJECTED")
                self.assertEqual(response.json()["reject_reason"], reason)
                self.assertEqual(client.get(f"/api/runs/{run_id}").json(), response.json())
                self.assertEqual(list(self.agents_dir.glob("*.json")), [])

    def test_timeout_terminates_tree_and_cleans_agent_before_runtime_error(self) -> None:
        client = TestClient(create_app(
            results_root=self.results_root, runner=self.runner(timeout_seconds=0.25)
        ))
        terminated: list[int] = []

        def terminate(process):
            terminated.append(process.pid)
            process.kill()

        with patch("ax_product.runner.subprocess.Popen", self.popen_factory(timeout=True)), \
                patch("ax_product.runner._terminate_process_tree", terminate):
            response = client.post("/api/run", json={**REQUEST, "run_id": "timed-out"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reject_reason"], "RUNTIME_ERROR")
        self.assertEqual(terminated, [self.processes[-1].pid])
        self.assertEqual(self.processes[-1].communications, 2)
        self.assertEqual(list(self.agents_dir.glob("*.json")), [])

    @unittest.skipUnless(os.name == "nt", "Windows process-tree assertion")
    def test_windows_tree_kill_uses_taskkill_without_a_shell(self) -> None:
        process = FakeKiroProcess(["kiro"], {})
        with patch("ax_product.runner.subprocess.run") as run:
            _terminate_process_tree(process)
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["taskkill", "/PID", str(process.pid), "/T", "/F"])
        self.assertIs(kwargs["shell"], False)
        self.assertTrue(process.killed)

    def test_process_creation_exception_cleans_temporary_agent(self) -> None:
        request = RunRequest(**REQUEST)
        ResultStore(self.results_root).reserve(
            run_id="creation-error", task_id=None, model=request.model, dataset=request.dataset
        )
        with patch("ax_product.runner.subprocess.Popen", side_effect=OSError("spawn failed")):
            with self.assertRaises(OSError):
                self.runner().run(
                    request, run_id="creation-error", results_root=self.results_root
                )
        self.assertEqual(list(self.agents_dir.glob("*.json")), [])

    def test_communication_exception_terminates_process_tree_and_cleans_agent(self) -> None:
        request = RunRequest(**REQUEST)
        ResultStore(self.results_root).reserve(
            run_id="communication-error", task_id=None,
            model=request.model, dataset=request.dataset,
        )
        process_holder: list[FakeKiroProcess] = []

        def factory(argv, **kwargs):
            process = FakeKiroProcess(argv, kwargs)
            original = process.communicate

            def communicate(timeout=None):
                if process.communications == 0:
                    process.communications += 1
                    raise OSError("pipe failed")
                return original(timeout)

            process.communicate = communicate
            process_holder.append(process)
            return process

        terminated: list[int] = []

        def terminate(process):
            terminated.append(process.pid)
            process.kill()

        with patch("ax_product.runner.subprocess.Popen", factory), \
                patch("ax_product.runner._terminate_process_tree", terminate):
            with self.assertRaises(OSError):
                self.runner().run(
                    request, run_id="communication-error", results_root=self.results_root
                )
        self.assertEqual(terminated, [process_holder[0].pid])
        self.assertTrue(process_holder[0].killed)
        self.assertEqual(list(self.agents_dir.glob("*.json")), [])

    def test_parallel_runs_use_distinct_agent_files_and_processes(self) -> None:
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        observed: list[tuple[str, str]] = []
        request = RunRequest(**REQUEST)
        for run_id in ("parallel-one", "parallel-two"):
            ResultStore(self.results_root).reserve(
                run_id=run_id, task_id=None, model=request.model, dataset=request.dataset
            )

        def factory(argv, **kwargs):
            def callback(current_argv):
                config = self.config_from_argv(current_argv)
                run_id = self._arg(
                    config["mcpServers"]["ax-product-tools"]["args"], "--run-id"
                )
                with lock:
                    observed.append((config["name"], run_id))
                barrier.wait(timeout=5)
                self.publish(current_argv, "none")
            process = FakeKiroProcess(argv, kwargs, callback)
            with lock:
                self.processes.append(process)
            return process

        with patch("ax_product.runner.subprocess.Popen", factory):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        self.runner().run, request, run_id=run_id,
                        results_root=self.results_root,
                    )
                    for run_id in ("parallel-one", "parallel-two")
                ]
                for future in futures:
                    future.result(timeout=10)
        self.assertEqual({run_id for _, run_id in observed}, {"parallel-one", "parallel-two"})
        self.assertEqual(len({name for name, _ in observed}), 2)
        self.assertEqual(len({process.pid for process in self.processes}), 2)
        self.assertEqual(list(self.agents_dir.glob("*.json")), [])

    def test_default_exported_app_remains_unavailable_and_duplicate_is_409(self) -> None:
        unavailable = TestClient(app).post(
            "/api/run", json={**REQUEST, "run_id": "default-unavailable"}
        )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.json()["detail"], "RUNNER_UNAVAILABLE")

        started = threading.Event()
        release = threading.Event()

        def callback(argv):
            started.set()
            self.assertTrue(release.wait(timeout=5))
            self.publish(argv, "none")

        client = TestClient(create_app(results_root=self.results_root, runner=self.runner()))
        with patch("ax_product.runner.subprocess.Popen", self.popen_factory(callback)):
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(
                    client.post, "/api/run", json={**REQUEST, "run_id": "duplicate-live"}
                )
                self.assertTrue(started.wait(timeout=5))
                duplicate = client.post(
                    "/api/run", json={**REQUEST, "run_id": "duplicate-live"}
                )
                running = client.get("/api/runs/duplicate-live")
                release.set()
                completed = first.result(timeout=10)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(running.json()["run_status"], "RUNNING")
        self.assertEqual(completed.json()["reject_reason"], "NO_SUBMISSION")

    def test_environment_factory_is_explicitly_opt_in(self) -> None:
        with patch.dict(os.environ, {"AX_PRODUCT_RUNNER": "disabled"}):
            with self.assertRaises(RuntimeError):
                create_app_from_env()
        with patch.dict(os.environ, {
            "AX_PRODUCT_RUNNER": "kiro",
            "AX_KIRO_CLI": "kiro-from-env.exe",
            "AX_PRODUCT_RUN_TIMEOUT_SECONDS": "12.5",
            "AX_RUNTIME_DATASET_CONFIG": str(DATASET_CONFIG),
        }):
            configured = create_app_from_env()
        self.assertEqual(configured.title, "AX Preflight API")


if __name__ == "__main__":
    unittest.main()
