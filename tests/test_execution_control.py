from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from ax_product.access_control import AccessControlStore
from ax_product.api import ROOT, create_app
from ax_product.local_datasets import LocalDatasetStore
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.results import FinalResultExistsError, ResultStore


class SuccessfulRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.block = False
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, request, *, run_id: str, results_root: Path) -> None:
        self.calls.append(run_id)
        if self.block:
            self.started.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("test runner release timed out")
        ResultStore(results_root).write(DeliveryEnvelope(
            delivery_status="DELIVERED",
            run_id=run_id,
            task_id=request.task_id,
            model=request.model,
            payload=SubmitAnswerInput(
                status="ANSWERED",
                answer="30일",
                answer_kind="EXACT_TEXT",
                explanation="승인된 데이터 경계 안에서 실행한 테스트 답변",
                source_ids=["DOC_1"],
            ),
            source_link_status="NOT_CHECKED",
        ))


class ExecutionControlApiTests(unittest.TestCase):
    def setUp(self) -> None:
        test_root = ROOT / ".test-tmp"
        test_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "company-files"
        self.source.mkdir()
        (self.source / "policy.txt").write_text(
            "반품은 30일 이내입니다. 담당자 연락처는 010-1234-5678입니다.",
            encoding="utf-8",
        )
        self.local_store = LocalDatasetStore(
            base_config=ROOT / "runtime_datasets.json",
            root=self.root / "local",
            allowed_scan_roots=[self.root],
        )
        self.access_store = AccessControlStore(
            self.root / "access", secure_cookie=False
        )
        self.runner = SuccessfulRunner()
        self.app = create_app(
            results_root=self.root / "runs",
            batch_root=self.root / "batches",
            local_dataset_store=self.local_store,
            access_control=self.access_store,
            runner=self.runner,
        )
        self.client = TestClient(self.app)
        bootstrap = self.client.post("/api/auth/bootstrap", json={
            "username": "control.owner",
            "display_name": "실행 통제 책임자",
            "password": "Boundary-Budget-Control!72",
            "project_name": "고객지원 PoC",
        })
        self.assertEqual(bootstrap.status_code, 201, bootstrap.text)
        self.csrf = bootstrap.json()["csrf_token"]
        self.headers = {"X-CSRF-Token": self.csrf}
        self.project_id = self.client.get("/api/projects").json()[0]["project_id"]
        scan = self.client.post(
            "/api/local-datasets",
            json={"source_path": str(self.source), "project_id": self.project_id},
            headers=self.headers,
        )
        self.assertEqual(scan.status_code, 201, scan.text)
        self.profile = scan.json()["dataset"]["profile"]
        task = self.client.post(
            f"/api/projects/{self.project_id}/tasks",
            json={
                "dataset_profile": self.profile,
                "category": "반품 정책",
                "question": "현재 반품 기간은 며칠인가요?",
                "description": "승인된 반품 기간을 근거와 함께 확인합니다.",
                "owner_role": "고객지원 팀장",
                "success_criteria": ["근거 문서를 인용한다"],
            },
            headers=self.headers,
        )
        self.assertEqual(task.status_code, 201, task.text)
        self.task_id = task.json()["task_id"]
        approved = self.client.post(
            f"/api/projects/{self.project_id}/tasks/{self.task_id}/approve",
            headers=self.headers,
        )
        self.assertEqual(approved.status_code, 200, approved.text)

    def policy(self, **updates: int | str) -> dict:
        payload = {
            "model": "claude-sonnet-5",
            "daily_run_limit": 2,
            "max_batch_runs": 2,
            "max_concurrent_runs": 1,
            "estimated_cost_per_run_cents": 25,
            "daily_budget_cents": 50,
        }
        payload.update(updates)
        response = self.client.put(
            f"/api/projects/{self.project_id}/execution-policy",
            json=payload,
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def approve_transfer(
        self, classification: str = "INTERNAL", model: str = "claude-sonnet-5"
    ) -> dict:
        response = self.client.post(
            f"/api/projects/{self.project_id}/data-transfer-approval",
            json={
                "dataset_profile": self.profile,
                "model": model,
                "data_classification": classification,
                "tool_output_to_model_acknowledged": True,
                "provider_policy_reviewed": True,
                "sensitive_data_reviewed": True,
                "valid_days": 30,
            },
            headers=self.headers,
        )
        if classification != "PUBLIC":
            self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def run_request(self, suffix: str) -> dict:
        return {
            "dataset": self.profile,
            "request_type": "VERIFIED_BUSINESS_TASK",
            "task_id": self.task_id,
            "model": "claude-sonnet-5",
        }

    def test_bundled_dataset_is_read_only_in_governed_live_mode(self) -> None:
        blocked = self.client.post(
            "/api/run",
            json={
                "dataset": "mini",
                "request_type": "AD_HOC_QUESTION",
                "question": "번들 예시를 다시 실행해 주세요.",
                "model": "claude-sonnet-5",
            },
            headers=self.headers,
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"], "BUNDLED_DATASET_READ_ONLY")
        self.assertEqual(
            blocked.json()["error"]["next_action"],
            "IMPORT_DATASET_INTO_PROJECT",
        )
        self.assertEqual(self.runner.calls, [])

        # Read-only bundled review stays available.
        self.assertEqual(self.client.get("/api/readiness/mini").status_code, 200)

    def test_unapproved_request_type_and_blocked_attempt_do_not_consume_usage(self) -> None:
        self.policy()
        self.approve_transfer()
        blocked = self.client.post(
            "/api/run",
            json={
                "dataset": self.profile,
                "request_type": "AD_HOC_QUESTION",
                "question": "승인되지 않은 임시 질문",
                "model": "claude-sonnet-5",
            },
            headers=self.headers,
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"], "APPROVED_TASK_REQUIRED")
        self.assertEqual(self.runner.calls, [])
        usage = self.client.get(
            f"/api/projects/{self.project_id}/execution-control"
            f"?dataset_profile={self.profile}"
        ).json()["usage"]
        self.assertEqual(usage["reserved_runs"], 0)
        self.assertEqual(usage["finalized_runs"], 0)
        self.assertEqual(usage["estimated_spend_cents"], 0)
        self.assertIn("EXECUTION_BLOCKED", self.access_store.audit_path.read_text(encoding="utf-8"))

    def test_user_cannot_execute_a_dataset_from_another_project(self) -> None:
        created_user = self.client.post(
            "/api/users",
            json={
                "username": "other.owner",
                "display_name": "Other Owner",
                "password": "Other-Project-Boundary!82",
                "global_role": "MEMBER",
            },
            headers=self.headers,
        )
        self.assertEqual(created_user.status_code, 201, created_user.text)
        other_project = self.client.post(
            "/api/projects",
            json={"name": "Other Project"},
            headers=self.headers,
        )
        self.assertEqual(other_project.status_code, 201, other_project.text)
        other_project_id = other_project.json()["project_id"]
        membership = self.client.post(
            f"/api/projects/{other_project_id}/members",
            json={"username": "other.owner", "role": "EDITOR"},
            headers=self.headers,
        )
        self.assertEqual(membership.status_code, 201, membership.text)
        other = TestClient(self.app)
        login = other.post("/api/auth/login", json={
            "username": "other.owner", "password": "Other-Project-Boundary!82",
        })
        self.assertEqual(login.status_code, 200, login.text)
        blocked = other.post(
            "/api/run",
            json=self.run_request("다른 프로젝트"),
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
        )
        self.assertEqual(blocked.status_code, 404, blocked.text)
        self.assertIn("PROJECT_NOT_FOUND", blocked.json()["detail"])
        self.assertEqual(self.runner.calls, [])

    def test_owner_approves_data_boundary_and_hard_budget_blocks_before_runner(self) -> None:
        control_url = (
            f"/api/projects/{self.project_id}/execution-control"
            f"?dataset_profile={self.profile}"
        )
        initial = self.client.get(control_url).json()
        self.assertFalse(initial["can_execute"])
        self.assertIn("EXECUTION_POLICY_REQUIRED", initial["blockers"])
        self.assertIn("DATA_TRANSFER_APPROVAL_REQUIRED", initial["blockers"])
        self.assertEqual(initial["connection"]["executable_status"], "NOT_CHECKED")

        blocked = self.client.post(
            "/api/run", json=self.run_request("차단"), headers=self.headers
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"], "EXECUTION_POLICY_REQUIRED")
        self.assertEqual(self.runner.calls, [])

        self.policy()
        unsafe_public = self.client.post(
            f"/api/projects/{self.project_id}/data-transfer-approval",
            json={
                "dataset_profile": self.profile,
                "model": "claude-sonnet-5",
                "data_classification": "PUBLIC",
                "tool_output_to_model_acknowledged": True,
                "provider_policy_reviewed": True,
                "sensitive_data_reviewed": True,
                "valid_days": 30,
            },
            headers=self.headers,
        )
        self.assertEqual(unsafe_public.status_code, 422, unsafe_public.text)
        self.assertIn("PII_CLASSIFICATION_REQUIRED", unsafe_public.json()["detail"])

        approval = self.approve_transfer()
        self.assertGreaterEqual(approval["pii_affected_file_count"], 1)
        ready = self.client.get(control_url).json()
        self.assertTrue(ready["can_execute"])
        self.assertEqual(ready["connection"]["credential_status"], "ENVIRONMENT_MANAGED_NOT_PROBED")

        for suffix in ("첫 실행", "두 번째 실행"):
            response = self.client.post(
                "/api/run", json=self.run_request(suffix), headers=self.headers
            )
            self.assertEqual(response.status_code, 200, response.text)
        exhausted = self.client.post(
            "/api/run", json=self.run_request("예산 초과"), headers=self.headers
        )
        self.assertEqual(exhausted.status_code, 409, exhausted.text)
        self.assertEqual(exhausted.json()["detail"], "DAILY_RUN_LIMIT_REACHED")
        self.assertEqual(len(self.runner.calls), 2)
        usage = self.client.get(control_url).json()["usage"]
        self.assertEqual(usage["reserved_runs"], 0)
        self.assertEqual(usage["finalized_runs"], 2)
        self.assertEqual(usage["estimated_reserved_cents"], 0)
        self.assertEqual(usage["estimated_spend_cents"], 50)
        self.assertEqual(usage["remaining_budget_cents"], 0)

    def test_local_approved_batch_uses_background_identity_and_batch_cap(self) -> None:
        self.policy(daily_run_limit=5, max_batch_runs=1, daily_budget_cents=125)
        self.approve_transfer()
        draft = self.client.post(
            f"/api/projects/{self.project_id}/tasks",
            json={
                "dataset_profile": self.profile,
                "category": "반품 정책",
                "question": "현재 반품 기간은 며칠인가요?",
                "description": "반품 기간을 근거와 함께 확인합니다.",
                "owner_role": "고객지원 팀장",
                "success_criteria": ["근거 문서를 인용한다"],
            },
            headers=self.headers,
        )
        task_id = draft.json()["task_id"]
        approved = self.client.post(
            f"/api/projects/{self.project_id}/tasks/{task_id}/approve",
            headers=self.headers,
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        request = {
            "batch_id": "customer-batch",
            "dataset": self.profile,
            "model": "claude-sonnet-5",
            "tasks": [{
                "task_id": task_id,
                "request_type": "VERIFIED_BUSINESS_TASK",
            }],
            "repetitions": 2,
            "max_attempts": 1,
        }
        oversized = self.client.post(
            "/api/batches", json=request, headers=self.headers
        )
        self.assertEqual(oversized.status_code, 409, oversized.text)
        self.assertEqual(oversized.json()["detail"], "BATCH_RUN_LIMIT_EXCEEDED")
        self.policy(daily_run_limit=5, max_batch_runs=2, daily_budget_cents=125)
        started = self.client.post(
            "/api/batches", json=request, headers=self.headers
        )
        self.assertEqual(started.status_code, 202, started.text)
        deadline = time.monotonic() + 5
        batch = started.json()
        while batch["state"] not in {"COMPLETED", "COMPLETED_WITH_ERRORS"}:
            self.assertLess(time.monotonic(), deadline, batch)
            time.sleep(0.01)
            batch = self.client.get("/api/batches/customer-batch").json()
        self.assertEqual(batch["state"], "COMPLETED")
        self.assertEqual(batch["project_id"], self.project_id)
        self.assertEqual(batch["succeeded_items"], 2)
        self.assertEqual(len(self.runner.calls), 2)

    def test_model_change_invalidates_dataset_approval_until_owner_reapproves(self) -> None:
        self.policy()
        first_approval = self.approve_transfer()
        self.assertEqual(first_approval["model"], "claude-sonnet-5")

        self.policy(model="claude-opus-5")
        control_url = (
            f"/api/projects/{self.project_id}/execution-control"
            f"?dataset_profile={self.profile}"
        )
        changed = self.client.get(control_url).json()
        self.assertFalse(changed["can_execute"])
        self.assertIn("MODEL_NOT_APPROVED", changed["blockers"])
        self.assertEqual(changed["transfer_approval"]["approval_id"], first_approval["approval_id"])

        blocked_request = self.run_request("모델 변경")
        blocked_request["model"] = "claude-opus-5"
        blocked = self.client.post(
            "/api/run", json=blocked_request, headers=self.headers
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"], "MODEL_NOT_APPROVED")
        self.assertEqual(self.runner.calls, [])

        replacement = self.approve_transfer(model="claude-opus-5")
        self.assertNotEqual(replacement["approval_id"], first_approval["approval_id"])
        self.assertTrue(self.client.get(control_url).json()["can_execute"])

    def test_scan_revision_invalidates_transfer_approval_but_display_rename_does_not(self) -> None:
        self.policy(daily_run_limit=4, daily_budget_cents=100)
        first = self.approve_transfer()
        first_fingerprint = first["dataset_revision_fingerprint"]

        unchanged = self.client.post(
            "/api/local-datasets",
            json={
                "source_path": str(self.source),
                "project_id": self.project_id,
                "display_name": "표시 이름만 변경",
            },
            headers=self.headers,
        )
        self.assertEqual(unchanged.status_code, 201, unchanged.text)
        self.assertEqual(
            unchanged.json()["audit"]["revision_fingerprint"],
            first_fingerprint,
        )
        control_url = (
            f"/api/projects/{self.project_id}/execution-control"
            f"?dataset_profile={self.profile}"
        )
        self.assertTrue(self.client.get(control_url).json()["can_execute"])

        (self.source / "policy.txt").write_text(
            "반품은 14일 이내입니다. 담당자 연락처는 010-9999-7777입니다.",
            encoding="utf-8",
        )
        changed = self.client.post(
            "/api/local-datasets",
            json={"source_path": str(self.source), "project_id": self.project_id},
            headers=self.headers,
        )
        self.assertEqual(changed.status_code, 201, changed.text)
        self.assertNotEqual(
            changed.json()["audit"]["revision_fingerprint"],
            first_fingerprint,
        )
        control = self.client.get(control_url).json()
        self.assertFalse(control["can_execute"])
        self.assertIn("DATA_TRANSFER_APPROVAL_REVISION_MISMATCH", control["blockers"])
        before_calls = list(self.runner.calls)
        blocked = self.client.post(
            "/api/run", json=self.run_request("내용 변경"), headers=self.headers
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(
            blocked.json()["detail"],
            "DATA_TRANSFER_APPROVAL_REVISION_MISMATCH",
        )
        self.assertEqual(self.runner.calls, before_calls)

    def test_expired_revision_approval_is_blocked_before_runner(self) -> None:
        self.policy()
        approval = self.approve_transfer()
        state = json.loads(self.access_store.state_path.read_text(encoding="utf-8"))
        stored = next(
            record for record in state["transfer_approvals"].values()
            if record["approval_id"] == approval["approval_id"]
        )
        stored["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        self.access_store.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        blocked = self.client.post(
            "/api/run", json=self.run_request("만료 승인"), headers=self.headers
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"], "DATA_TRANSFER_APPROVAL_EXPIRED")
        self.assertEqual(self.runner.calls, [])

    def test_dataset_deletion_and_reregistration_do_not_reset_project_usage(self) -> None:
        self.policy(daily_run_limit=2, daily_budget_cents=50)
        self.approve_transfer()
        completed = self.client.post(
            "/api/run", json=self.run_request("사용량 보존"), headers=self.headers
        )
        self.assertEqual(completed.status_code, 200, completed.text)
        deleted = self.client.delete(
            f"/api/local-datasets/{self.profile}", headers=self.headers
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        state = json.loads(self.access_store.state_path.read_text(encoding="utf-8"))
        project_usage = [
            record for record in state["execution_usage"].values()
            if record.get("project_id") == self.project_id
        ]
        self.assertEqual(len(project_usage), 1)
        self.assertEqual(project_usage[0]["status"], "FINALIZED")

        rescanned = self.client.post(
            "/api/local-datasets",
            json={"source_path": str(self.source), "project_id": self.project_id},
            headers=self.headers,
        )
        self.assertEqual(rescanned.status_code, 201, rescanned.text)
        self.assertEqual(rescanned.json()["dataset"]["profile"], self.profile)
        self.approve_transfer()
        usage = self.client.get(
            f"/api/projects/{self.project_id}/execution-control"
            f"?dataset_profile={self.profile}"
        ).json()["usage"]
        self.assertEqual(usage["finalized_runs"], 1)
        self.assertEqual(usage["remaining_run_capacity"], 1)

        other_project = self.client.post(
            "/api/projects", json={"name": "사용량 분리 프로젝트"}, headers=self.headers
        )
        self.assertEqual(other_project.status_code, 201, other_project.text)
        other_project_id = other_project.json()["project_id"]
        other_policy = self.client.put(
            f"/api/projects/{other_project_id}/execution-policy",
            json={
                "model": "claude-sonnet-5",
                "daily_run_limit": 2,
                "max_batch_runs": 2,
                "max_concurrent_runs": 1,
                "estimated_cost_per_run_cents": 25,
                "daily_budget_cents": 50,
            },
            headers=self.headers,
        )
        self.assertEqual(other_policy.status_code, 200, other_policy.text)
        other_usage = self.client.get(
            f"/api/projects/{other_project_id}/execution-control"
        ).json()["usage"]
        self.assertEqual(other_usage["finalized_runs"], 0)
        self.assertEqual(other_usage["remaining_run_capacity"], 2)

        state = json.loads(self.access_store.state_path.read_text(encoding="utf-8"))
        project_record = next(
            record for record in state["execution_usage"].values()
            if record.get("project_id") == self.project_id
        )
        project_record["reserved_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=25)
        ).isoformat()
        self.access_store.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        expired_usage = self.client.get(
            f"/api/projects/{self.project_id}/execution-control"
            f"?dataset_profile={self.profile}"
        ).json()["usage"]
        self.assertEqual(expired_usage["finalized_runs"], 0)
        self.assertEqual(expired_usage["remaining_run_capacity"], 2)

    def test_non_owner_cannot_change_policy_or_approve_data_transfer(self) -> None:
        created = self.client.post(
            "/api/users",
            json={
                "username": "control.viewer",
                "display_name": "실행 통제 조회자",
                "password": "Read-Only-Boundary!92",
                "global_role": "MEMBER",
            },
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        membership = self.client.post(
            f"/api/projects/{self.project_id}/members",
            json={"username": "control.viewer", "role": "VIEWER"},
            headers=self.headers,
        )
        self.assertEqual(membership.status_code, 201, membership.text)

        viewer = TestClient(self.app)
        login = viewer.post("/api/auth/login", json={
            "username": "control.viewer",
            "password": "Read-Only-Boundary!92",
        })
        self.assertEqual(login.status_code, 200, login.text)
        viewer_headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        policy_payload = {
            "model": "claude-sonnet-5",
            "daily_run_limit": 2,
            "max_batch_runs": 2,
            "max_concurrent_runs": 1,
            "estimated_cost_per_run_cents": 25,
            "daily_budget_cents": 50,
        }
        denied_policy = viewer.put(
            f"/api/projects/{self.project_id}/execution-policy",
            json=policy_payload,
            headers=viewer_headers,
        )
        self.assertEqual(denied_policy.status_code, 403, denied_policy.text)
        self.assertIn("PROJECT_OWNER_REQUIRED", denied_policy.json()["detail"])

        self.policy()
        denied_approval = viewer.post(
            f"/api/projects/{self.project_id}/data-transfer-approval",
            json={
                "dataset_profile": self.profile,
                "model": "claude-sonnet-5",
                "data_classification": "INTERNAL",
                "tool_output_to_model_acknowledged": True,
                "provider_policy_reviewed": True,
                "sensitive_data_reviewed": True,
                "valid_days": 30,
            },
            headers=viewer_headers,
        )
        self.assertEqual(denied_approval.status_code, 403, denied_approval.text)
        self.assertIn("PROJECT_OWNER_REQUIRED", denied_approval.json()["detail"])

    def test_pre_runner_rollback_removes_only_unfinished_reservation(self) -> None:
        store = ResultStore(self.root / "rollback-runs")
        store.reserve(
            run_id="unfinished", task_id=None, model="claude-sonnet-5",
            dataset=self.profile,
        )
        store.discard_reservation("unfinished")
        self.assertFalse((store.root / "unfinished").exists())

        store.reserve(
            run_id="finished", task_id=None, model="claude-sonnet-5",
            dataset=self.profile,
        )
        store.write(DeliveryEnvelope(
            delivery_status="REJECTED",
            run_id="finished",
            model="claude-sonnet-5",
            reject_reason="RUNTIME_ERROR",
        ))
        with self.assertRaises(FinalResultExistsError):
            store.discard_reservation("finished")
        self.assertTrue((store.root / "finished" / "delivery.json").is_file())

    def test_concurrent_run_is_rejected_before_second_runner_call(self) -> None:
        self.policy(
            daily_run_limit=4,
            max_batch_runs=4,
            max_concurrent_runs=1,
            daily_budget_cents=100,
        )
        self.approve_transfer()
        self.runner.block = True
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(
                self.client.post,
                "/api/run",
                json=self.run_request("긴 실행"),
                headers=self.headers,
            )
            self.assertTrue(self.runner.started.wait(timeout=2))
            second = self.client.post(
                "/api/run",
                json=self.run_request("동시 실행"),
                headers=self.headers,
            )
            self.assertEqual(second.status_code, 409, second.text)
            self.assertEqual(second.json()["detail"], "CONCURRENCY_LIMIT_REACHED")
            self.assertEqual(len(self.runner.calls), 1)
            self.runner.release.set()
            completed = first.result(timeout=5)
        self.assertEqual(completed.status_code, 200, completed.text)


if __name__ == "__main__":
    unittest.main()
