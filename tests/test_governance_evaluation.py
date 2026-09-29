from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ax_product.access_control import AccessControlStore
from ax_product.api import ROOT, create_app
from ax_product.local_datasets import LocalDatasetStore


class GovernanceEvaluationApiTests(unittest.TestCase):
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
        )
        self.access_store = AccessControlStore(
            self.root / "access", secure_cookie=False
        )
        self.client = TestClient(create_app(
            results_root=self.root / "runs",
            local_dataset_store=self.local_store,
            access_control=self.access_store,
        ))
        bootstrap = self.client.post("/api/auth/bootstrap", json={
            "username": "governance.owner",
            "display_name": "PoC 책임자",
            "password": "Reliable-Governance!47",
            "project_name": "감사 가능한 PoC",
        })
        self.assertEqual(bootstrap.status_code, 201, bootstrap.text)
        self.csrf = bootstrap.json()["csrf_token"]
        self.project_id = self.client.get("/api/projects").json()[0]["project_id"]

    @property
    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}

    def scan(self) -> str:
        response = self.client.post(
            "/api/local-datasets",
            json={"source_path": str(self.source), "project_id": self.project_id},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["dataset"]["profile"]

    def test_hash_chained_project_audit_detects_tampering(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.project_id}/audit-log"
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["ledger_status"], "VERIFIED")
        self.assertGreaterEqual(body["event_count"], 1)
        self.assertTrue(all(item["integrity_verified"] for item in body["events"]))

        audit_path = self.root / "access" / "security-audit.jsonl"
        records = audit_path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(records[0])
        tampered["event"] = "TAMPERED_EVENT"
        records[0] = json.dumps(tampered, ensure_ascii=False, sort_keys=True)
        audit_path.write_text("\n".join(records) + "\n", encoding="utf-8")

        detected = self.client.get(
            f"/api/projects/{self.project_id}/audit-log"
        )
        self.assertEqual(detected.status_code, 200, detected.text)
        self.assertEqual(detected.json()["ledger_status"], "INVALID")
        self.assertEqual(detected.json()["events"], [])
        blocked_delete = self.client.post(
            f"/api/projects/{self.project_id}/purge",
            json={"confirmation": "감사 가능한 PoC"},
            headers=self.headers,
        )
        self.assertEqual(blocked_delete.status_code, 409, blocked_delete.text)
        self.assertEqual(blocked_delete.json()["detail"], "AUDIT_LEDGER_INVALID")

    def test_retention_hold_and_verified_purge_cover_all_managed_records(self) -> None:
        profile = self.scan()
        retention = self.client.put(
            f"/api/projects/{self.project_id}/retention-policy",
            json={
                "managed_data_days": 45,
                "audit_event_days": 400,
                "legal_hold": True,
            },
            headers=self.headers,
        )
        self.assertEqual(retention.status_code, 200, retention.text)
        held = self.client.post(
            f"/api/projects/{self.project_id}/purge",
            json={"confirmation": "감사 가능한 PoC"},
            headers=self.headers,
        )
        self.assertEqual(held.status_code, 409, held.text)
        self.assertEqual(held.json()["detail"], "PROJECT_LEGAL_HOLD")
        self.assertTrue(self.local_store.contains(profile))

        released = self.client.put(
            f"/api/projects/{self.project_id}/retention-policy",
            json={
                "managed_data_days": 45,
                "audit_event_days": 400,
                "legal_hold": False,
            },
            headers=self.headers,
        )
        self.assertEqual(released.status_code, 200, released.text)
        policy = self.client.put(
            f"/api/projects/{self.project_id}/execution-policy",
            json={
                "model": "approved-poc-model",
                "daily_run_limit": 5,
                "max_batch_runs": 3,
                "max_concurrent_runs": 1,
                "estimated_cost_per_run_cents": 10,
                "daily_budget_cents": 50,
            },
            headers=self.headers,
        )
        self.assertEqual(policy.status_code, 200, policy.text)
        approval = self.client.post(
            f"/api/projects/{self.project_id}/data-transfer-approval",
            json={
                "dataset_profile": profile,
                "model": "approved-poc-model",
                "data_classification": "INTERNAL",
                "tool_output_to_model_acknowledged": True,
                "provider_policy_reviewed": True,
                "sensitive_data_reviewed": True,
                "valid_days": 30,
            },
            headers=self.headers,
        )
        self.assertEqual(approval.status_code, 200, approval.text)
        evaluation = self.client.put(
            f"/api/projects/{self.project_id}/poc-evaluation/decision",
            params={"dataset_profile": profile},
            json={
                "decision": "REJECTED",
                "note": "차단 항목을 보완한 뒤 다시 검토합니다.",
                "scope_acknowledged": True,
                "risk_acknowledged": True,
                "valid_days": 30,
            },
            headers=self.headers,
        )
        self.assertEqual(evaluation.status_code, 200, evaluation.text)
        self.assertTrue(evaluation.json()["decision_current"])

        inventory = self.client.get(
            f"/api/projects/{self.project_id}/data-inventory"
        ).json()
        self.assertEqual(inventory["execution_policy_count"], 1)
        self.assertEqual(inventory["transfer_approval_count"], 1)
        self.assertEqual(inventory["poc_decision_count"], 1)
        self.assertGreaterEqual(inventory["audit_event_count"], 5)
        self.assertEqual(inventory["retention_policy"]["managed_data_days"], 45)

        purged = self.client.post(
            f"/api/projects/{self.project_id}/purge",
            json={"confirmation": "감사 가능한 PoC"},
            headers=self.headers,
        )
        self.assertEqual(purged.status_code, 200, purged.text)
        result = purged.json()
        self.assertEqual(result["verification_status"], "VERIFIED")
        self.assertEqual(result["execution_policies_deleted"], 1)
        self.assertEqual(result["transfer_approvals_deleted"], 1)
        self.assertEqual(result["poc_decisions_deleted"], 1)
        self.assertGreater(result["audit_events_deleted"], 0)
        self.assertFalse(result["raw_project_identifier_retained"])
        self.assertNotIn(
            self.project_id,
            (self.root / "access" / "security-audit.jsonl").read_text(
                encoding="utf-8"
            ),
        )
        self.assertTrue((self.source / "policy.txt").is_file())

    def test_poc_report_blocks_unsupported_approval_and_stales_after_change(self) -> None:
        profile = self.scan()
        report = self.client.get(
            f"/api/projects/{self.project_id}/poc-evaluation",
            params={"dataset_profile": profile},
        )
        self.assertEqual(report.status_code, 200, report.text)
        body = report.json()
        self.assertEqual(body["recommendation"], "NO_GO")
        self.assertIn(
            "EXECUTION_SAMPLE",
            {item["code"] for item in body["gates"] if item["status"] == "BLOCK"},
        )
        blocked = self.client.put(
            f"/api/projects/{self.project_id}/poc-evaluation/decision",
            params={"dataset_profile": profile},
            json={
                "decision": "APPROVED",
                "note": "근거 없이 승인해서는 안 됩니다.",
                "scope_acknowledged": True,
                "risk_acknowledged": True,
                "valid_days": 30,
            },
            headers=self.headers,
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"], "POC_GO_GATES_REQUIRED")

        rejected = self.client.put(
            f"/api/projects/{self.project_id}/poc-evaluation/decision",
            params={"dataset_profile": profile},
            json={
                "decision": "REJECTED",
                "note": "표본 실행과 직접 근거를 확보한 뒤 재평가합니다.",
                "scope_acknowledged": True,
                "risk_acknowledged": True,
                "valid_days": 30,
            },
            headers=self.headers,
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertTrue(rejected.json()["decision_current"])

        task = self.client.post(
            f"/api/projects/{self.project_id}/tasks",
            json={
                "dataset_profile": profile,
                "category": "반품",
                "question": "반품 접수 기한은 언제까지인가요?",
                "description": "현재 정책을 확인합니다.",
                "owner_role": "고객지원 팀장",
                "success_criteria": ["정책 문서를 인용한다"],
            },
            headers=self.headers,
        )
        self.assertEqual(task.status_code, 201, task.text)
        changed = self.client.get(
            f"/api/projects/{self.project_id}/poc-evaluation",
            params={"dataset_profile": profile},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertFalse(changed.json()["decision_current"])


if __name__ == "__main__":
    unittest.main()
