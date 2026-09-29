from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ax_product.access_control import AccessControlStore
from ax_product.api import ROOT, create_app
from ax_product.evidence import EvidenceCheckResult, EvidenceCheckStore
from ax_product.local_datasets import LocalDatasetStore
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.results import ResultStore


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
            allowed_scan_roots=[self.root],
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
        self.user_id = bootstrap.json()["user"]["user_id"]
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

    def task(self, profile: str, *, approve: bool = True) -> str:
        response = self.client.post(
            f"/api/projects/{self.project_id}/tasks",
            json={
                "dataset_profile": profile,
                "category": "반품",
                "question": "반품 접수 기한은 언제까지인가요?",
                "description": "현재 정책을 반복 확인합니다.",
                "owner_role": "고객지원 팀장",
                "success_criteria": ["정책 문서를 인용한다"],
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        task_id = response.json()["task_id"]
        if approve:
            approved = self.client.post(
                f"/api/projects/{self.project_id}/tasks/{task_id}/approve",
                headers=self.headers,
            )
            self.assertEqual(approved.status_code, 200, approved.text)
        return task_id

    def write_run(
        self,
        profile: str,
        task_id: str,
        run_id: str,
        *,
        request_type: str = "VERIFIED_BUSINESS_TASK",
        rejected: bool = False,
        direct_evidence: bool = False,
    ) -> None:
        store = ResultStore(self.root / "runs")
        store.reserve(
            run_id=run_id,
            task_id=task_id if request_type != "AD_HOC_QUESTION" else None,
            model="approved-poc-model",
            dataset=profile,
            task_key=task_id,
            task_label="반품 접수 기한은 언제까지인가요?",
            request_type=request_type,
        )
        if rejected:
            envelope = DeliveryEnvelope(
                delivery_status="REJECTED",
                run_id=run_id,
                task_id=task_id,
                model="approved-poc-model",
                reject_reason="RUNTIME_ERROR",
            )
        else:
            envelope = DeliveryEnvelope(
                delivery_status="DELIVERED",
                run_id=run_id,
                task_id=task_id,
                model="approved-poc-model",
                payload=SubmitAnswerInput(
                    status="ANSWERED",
                    answer="14일",
                    answer_kind="EXACT_TEXT",
                    explanation="정책 문서에서 확인했습니다.",
                    source_ids=["DOC_POLICY"],
                ),
                source_link_status="LINKED",
            )
        store.write(envelope)
        if direct_evidence and not rejected:
            EvidenceCheckStore(self.root / "runs").write(EvidenceCheckResult(
                run_id=run_id,
                verdict="DIRECT_MATCH",
                delivery_sha256="0" * 64,
                cited_source_ids=["DOC_POLICY"],
                matched_source_ids=["DOC_POLICY"],
                unmatched_source_ids=[],
                evidence=[],
                limitations=[],
            ))

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
        self.assertEqual(result["audit_events_deleted"], 0)
        self.assertTrue(result["raw_project_identifier_retained"])
        self.assertTrue(result["audit_tombstone_retained"])
        audit_records = [
            json.loads(line)
            for line in (self.root / "access" / "security-audit.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        self.assertEqual(audit_records[0]["previous_hash"], "GENESIS")
        self.assertEqual(audit_records[-1]["event"], "PROJECT_PURGE_COMPLETED")
        self.assertEqual(
            audit_records[-1]["previous_hash"], audit_records[-2]["record_hash"]
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

    def test_failed_runs_are_excluded_from_the_execution_sample(self) -> None:
        profile = self.scan()
        task_id = self.task(profile)
        for index in range(3):
            self.write_run(
                profile, task_id, f"failed-{index}", rejected=True
            )

        report = self.client.get(
            f"/api/projects/{self.project_id}/poc-evaluation",
            params={"dataset_profile": profile},
        ).json()

        self.assertEqual(report["metrics"]["observed_runs"], 0)
        self.assertEqual(report["run_population"]["included_runs"], 0)
        self.assertEqual(report["run_population"]["excluded_runtime_failure_runs"], 3)
        execution_gate = next(
            item for item in report["gates"] if item["code"] == "EXECUTION_SAMPLE"
        )
        self.assertEqual(execution_gate["status"], "BLOCK")
        self.assertEqual(report["recommendation"], "NO_GO")

    def test_approved_task_without_successful_runs_cannot_reach_go(self) -> None:
        profile = self.scan()
        task_id = self.task(profile)

        report = self.client.get(
            f"/api/projects/{self.project_id}/poc-evaluation",
            params={"dataset_profile": profile},
        ).json()

        self.assertEqual(report["recommendation"], "NO_GO")
        self.assertEqual(report["task_samples"], [{
            "task_id": task_id,
            "task_label": "반품 접수 기한은 언제까지인가요?",
            "included_runs": 0,
            "minimum_runs": 3,
            "sample_complete": False,
        }])

    def test_direct_evidence_requires_minimum_sample_and_ratio(self) -> None:
        profile = self.scan()
        task_id = self.task(profile)
        self.write_run(
            profile, task_id, "evidence-ratio-0", direct_evidence=True
        )

        undersized = self.client.get(
            f"/api/projects/{self.project_id}/poc-evaluation",
            params={"dataset_profile": profile},
        ).json()
        undersized_gate = next(
            item for item in undersized["gates"]
            if item["code"] == "DIRECT_EVIDENCE"
        )
        self.assertEqual(undersized_gate["status"], "BLOCK")
        self.assertEqual(undersized_gate["numerator"], 1)
        self.assertEqual(undersized_gate["denominator"], 1)

        for index in range(1, 3):
            self.write_run(
                profile,
                task_id,
                f"evidence-ratio-{index}",
                direct_evidence=False,
            )

        report = self.client.get(
            f"/api/projects/{self.project_id}/poc-evaluation",
            params={"dataset_profile": profile},
        ).json()

        evidence_gate = next(
            item for item in report["gates"] if item["code"] == "DIRECT_EVIDENCE"
        )
        self.assertEqual(evidence_gate["status"], "BLOCK")
        self.assertEqual(evidence_gate["numerator"], 1)
        self.assertEqual(evidence_gate["denominator"], 3)
        self.assertEqual(evidence_gate["minimum_sample"], 3)
        self.assertEqual(evidence_gate["minimum_ratio"], 0.8)
        self.assertIn("33.3%", evidence_gate["detail"])

    def test_irrelevant_ad_hoc_run_does_not_change_assessment_fingerprint(self) -> None:
        profile = self.scan()
        task_id = self.task(profile)
        for index in range(3):
            self.write_run(
                profile, task_id, f"approved-{index}", direct_evidence=True
            )
        before = self.client.get(
            f"/api/projects/{self.project_id}/poc-evaluation",
            params={"dataset_profile": profile},
        ).json()

        self.write_run(
            profile,
            "ad-hoc-question",
            "irrelevant-ad-hoc",
            request_type="AD_HOC_QUESTION",
            direct_evidence=True,
        )
        after = self.client.get(
            f"/api/projects/{self.project_id}/poc-evaluation",
            params={"dataset_profile": profile},
        ).json()

        self.assertEqual(after["run_population"]["excluded_non_verified_request_runs"], 1)
        self.assertEqual(before["assessment_fingerprint"], after["assessment_fingerprint"])

    def test_governance_boundary_is_separate_from_current_execution_capacity(self) -> None:
        profile = self.scan()
        task_id = self.task(profile)
        policy = self.client.put(
            f"/api/projects/{self.project_id}/execution-policy",
            json={
                "model": "approved-poc-model",
                "daily_run_limit": 1,
                "max_batch_runs": 1,
                "max_concurrent_runs": 1,
                "estimated_cost_per_run_cents": 10,
                "daily_budget_cents": 10,
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
        for index in range(3):
            self.write_run(
                profile, task_id, f"governed-{index}", direct_evidence=True
            )

        before = self.client.get(
            f"/api/projects/{self.project_id}/poc-evaluation",
            params={"dataset_profile": profile},
        ).json()
        self.assertEqual(before["diagnostics_version"], "v2")
        self.assertEqual(before["recommendation"], "GO")
        self.assertEqual(
            next(item for item in before["gates"] if item["code"] == "MODEL_BOUNDARY")["status"],
            "PASS",
        )

        self.access_store.record_execution(
            self.access_store.user_by_id(self.user_id),
            self.project_id,
            profile,
            "approved-poc-model",
            "capacity-only-run",
        )
        after = self.client.get(
            f"/api/projects/{self.project_id}/poc-evaluation",
            params={"dataset_profile": profile},
        ).json()

        capacity = next(
            item for item in after["gates"] if item["code"] == "EXECUTION_CAPACITY"
        )
        self.assertFalse(capacity["decision_relevant"])
        self.assertIn("DAILY_RUN_LIMIT_REACHED", capacity["detail"])
        self.assertEqual(after["recommendation"], "GO")
        self.assertEqual(before["assessment_fingerprint"], after["assessment_fingerprint"])


if __name__ == "__main__":
    unittest.main()
