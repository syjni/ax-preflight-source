from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ax_product.access_control import AccessControlStore
from ax_product.api import ROOT, create_app
from ax_product.local_datasets import LocalDatasetStore
from ax_product.models import DeliveryEnvelope
from ax_product.results import ResultStore


class AccessControlApiTests(unittest.TestCase):
    def setUp(self) -> None:
        test_root = ROOT / ".test-tmp"
        test_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "customer-files"
        self.source.mkdir()
        (self.source / "policy.txt").write_text(
            "반품 접수는 주문일로부터 14일 이내입니다.", encoding="utf-8"
        )
        self.local_store = LocalDatasetStore(
            base_config=ROOT / "runtime_datasets.json",
            root=self.root / "local",
            allowed_scan_roots=[self.root],
        )
        self.access_store = AccessControlStore(self.root / "access", secure_cookie=False)
        self.client = TestClient(create_app(
            results_root=self.root / "runs",
            local_dataset_store=self.local_store,
            access_control=self.access_store,
        ))

    def bootstrap(self) -> tuple[str, str]:
        response = self.client.post("/api/auth/bootstrap", json={
            "username": "owner.one",
            "display_name": "PoC 책임자",
            "password": "Thorough-Sea-Glass!47",
            "project_name": "반품 자동화 PoC",
        })
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        project_id = self.client.get("/api/projects").json()[0]["project_id"]
        return body["csrf_token"], project_id

    def test_bootstrap_session_csrf_and_secrets_are_fail_closed(self) -> None:
        self.assertEqual(self.client.get("/api/capabilities").status_code, 200)
        self.assertEqual(self.client.get("/api/datasets").status_code, 401)
        initial = self.client.get("/api/auth/session").json()
        self.assertTrue(initial["bootstrap_required"])
        csrf, project_id = self.bootstrap()

        cookie = self.client.cookies.get("ax_preflight_session")
        self.assertIsNotNone(cookie)
        rejected = self.client.post("/api/projects", json={"name": "차단되어야 함"})
        self.assertEqual(rejected.status_code, 403)
        created = self.client.post(
            "/api/projects", json={"name": "두 번째 프로젝트"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertNotEqual(created.json()["project_id"], project_id)

        state_text = (self.root / "access" / "state.json").read_text(encoding="utf-8")
        self.assertNotIn("Thorough-Sea-Glass!47", state_text)
        self.assertNotIn(cookie, state_text)
        self.assertNotIn(csrf, state_text)

        # Refreshing another tab issues a new token without invalidating the
        # first tab's bounded CSRF token history.
        refreshed_csrf = self.client.get("/api/auth/session").json()["csrf_token"]
        self.assertNotEqual(refreshed_csrf, csrf)
        first_tab_write = self.client.post(
            "/api/projects", json={"name": "첫 탭에서도 생성"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(first_tab_write.status_code, 201, first_tab_write.text)

    def test_failed_logins_are_persistently_rate_limited(self) -> None:
        access_store = AccessControlStore(
            self.root / "rate-limit-access",
            secure_cookie=False,
            login_max_failures=3,
            login_window_minutes=15,
            login_lock_minutes=15,
        )
        client = TestClient(create_app(
            results_root=self.root / "rate-limit-runs",
            local_dataset_store=self.local_store,
            access_control=access_store,
        ))
        bootstrap = client.post("/api/auth/bootstrap", json={
            "username": "limit.owner",
            "display_name": "제한 확인 관리자",
            "password": "Secure-Harbor-Light!93",
            "project_name": "로그인 제한 확인",
        })
        csrf = bootstrap.json()["csrf_token"]
        self.assertEqual(
            client.post(
                "/api/auth/logout", headers={"X-CSRF-Token": csrf}
            ).status_code,
            204,
        )
        for expected in (401, 401, 429):
            response = client.post("/api/auth/login", json={
                "username": "limit.owner", "password": "incorrect-password",
            })
            self.assertEqual(response.status_code, expected, response.text)
        locked = client.post("/api/auth/login", json={
            "username": "limit.owner", "password": "Secure-Harbor-Light!93",
        })
        self.assertEqual(locked.status_code, 429, locked.text)
        self.assertEqual(locked.headers["Retry-After"], "900")
        state_text = (self.root / "rate-limit-access" / "state.json").read_text(encoding="utf-8")
        state = json.loads(state_text)
        self.assertNotIn("limit.owner", state["login_attempts"])
        self.assertNotIn("incorrect-password", state_text)

    def test_project_membership_isolates_datasets_and_task_approval(self) -> None:
        csrf, project_id = self.bootstrap()
        scan = self.client.post(
            "/api/local-datasets",
            json={
                "source_path": str(self.source),
                "display_name": "반품팀 자료",
                "project_id": project_id,
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(scan.status_code, 201, scan.text)
        profile = scan.json()["dataset"]["profile"]

        draft = self.client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "dataset_profile": profile,
                "category": "반품 정책",
                "question": "고객 A의 반품 요청을 승인할 수 있나요?",
                "description": "정책 문서에 근거해 승인 가능 여부를 판단합니다.",
                "owner_role": "고객지원 팀장",
                "success_criteria": ["근거 문서를 인용한다", "불확실하면 보류한다"],
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(draft.status_code, 201, draft.text)
        task_id = draft.json()["task_id"]
        self.assertEqual(
            self.client.get(f"/api/tasks/{profile}").json()["tasks"][0]["status"],
            "CANDIDATE",
        )
        approved = self.client.post(
            f"/api/projects/{project_id}/tasks/{task_id}/approve",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(
            self.client.get(f"/api/tasks/{profile}").json()["tasks"][0]["status"],
            "VERIFIED",
        )

        user = self.client.post(
            "/api/users",
            json={
                "username": "reviewer.two",
                "display_name": "검토자",
                "password": "Different-River-Stone!82",
                "global_role": "MEMBER",
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(user.status_code, 201, user.text)

        reviewer = TestClient(self.client.app)
        login = reviewer.post("/api/auth/login", json={
            "username": "reviewer.two", "password": "Different-River-Stone!82",
        })
        self.assertEqual(login.status_code, 200, login.text)
        reviewer_csrf = login.json()["csrf_token"]
        self.assertEqual(reviewer.get("/api/projects").json(), [])
        self.assertEqual(reviewer.get(f"/api/readiness/{profile}").status_code, 404)
        self.assertNotIn(
            profile,
            {item["profile"] for item in reviewer.get("/api/datasets").json()["datasets"]},
        )

        membership = self.client.post(
            f"/api/projects/{project_id}/members",
            json={"username": "reviewer.two", "role": "VIEWER"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(membership.status_code, 201, membership.text)
        self.assertEqual(reviewer.get(f"/api/readiness/{profile}").status_code, 200)
        self.assertIn(
            profile,
            {item["profile"] for item in reviewer.get("/api/datasets").json()["datasets"]},
        )
        forbidden = reviewer.post(
            f"/api/projects/{project_id}/tasks/{task_id}/approve",
            headers={"X-CSRF-Token": reviewer_csrf},
        )
        self.assertEqual(forbidden.status_code, 403)

        second_project = reviewer.post(
            "/api/projects", json={"name": "검토자 전용"},
            headers={"X-CSRF-Token": reviewer_csrf},
        )
        self.assertEqual(second_project.status_code, 201, second_project.text)
        self.assertNotIn(
            second_project.json()["project_id"],
            {project["project_id"] for project in self.client.get("/api/projects").json()},
        )

        removed = self.client.delete(
            f"/api/projects/{project_id}/members/{user.json()['user_id']}",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(removed.status_code, 204, removed.text)
        self.assertEqual(reviewer.get(f"/api/readiness/{profile}").status_code, 404)
        revoked = self.client.post(
            f"/api/users/{user.json()['user_id']}/revoke-sessions",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(revoked.json()["revoked_sessions"], 1)
        self.assertEqual(reviewer.get("/api/projects").status_code, 401)

    def test_project_inventory_and_confirmed_purge_delete_managed_records_only(self) -> None:
        csrf, project_id = self.bootstrap()
        scan = self.client.post(
            "/api/local-datasets",
            json={"source_path": str(self.source), "project_id": project_id},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(scan.status_code, 201, scan.text)
        profile = scan.json()["dataset"]["profile"]
        task = self.client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "dataset_profile": profile,
                "category": "반품 정책",
                "question": "반품 접수 기한은 언제까지인가요?",
                "description": "반품 접수 가능 기간을 확인합니다.",
                "owner_role": "고객지원 팀장",
                "success_criteria": ["정책 문서를 인용한다"],
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(task.status_code, 201, task.text)

        writable = ResultStore(self.root / "runs")
        writable.reserve(
            run_id="project-purge-run", task_id=None, model="test",
            dataset=profile,
        )
        busy_inventory = self.client.get(
            f"/api/projects/{project_id}/data-inventory"
        ).json()
        self.assertEqual(busy_inventory["running_run_count"], 1)
        blocked = self.client.post(
            f"/api/projects/{project_id}/purge",
            json={"confirmation": "반품 자동화 PoC"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)

        writable.write(DeliveryEnvelope(
            delivery_status="REJECTED", run_id="project-purge-run",
            model="test", reject_reason="RUNTIME_ERROR",
        ))
        mismatch = self.client.post(
            f"/api/projects/{project_id}/purge",
            json={"confirmation": "다른 프로젝트"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(mismatch.status_code, 422, mismatch.text)
        purged = self.client.post(
            f"/api/projects/{project_id}/purge",
            json={"confirmation": "반품 자동화 PoC"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(purged.status_code, 200, purged.text)
        body = purged.json()
        self.assertEqual(body["local_datasets_deleted"], 1)
        self.assertEqual(body["business_tasks_deleted"], 1)
        self.assertEqual(body["writable_runs_deleted"], 1)
        self.assertFalse(body["source_files_deleted"])
        self.assertTrue((self.source / "policy.txt").is_file())
        self.assertEqual(self.client.get("/api/projects").json(), [])
        self.assertEqual(self.client.get(f"/api/readiness/{profile}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
