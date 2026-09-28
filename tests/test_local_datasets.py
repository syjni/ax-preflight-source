from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from ax_product.api import ROOT, create_app
from ax_product.local_datasets import LocalDatasetStore


class LocalDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "reviewer-files"
        self.source.mkdir()
        (self.source / "policy.txt").write_text(
            "담당자 이메일은 owner@example.com 입니다.", encoding="utf-8"
        )
        (self.source / "policy-copy.txt").write_text(
            "담당자 이메일은 owner@example.com 입니다.", encoding="utf-8"
        )
        (self.source / "orders.csv").write_text(
            "order_id,amount\nA-1,12000\nA-2,\n", encoding="utf-8"
        )
        (self.source / "image.png").write_bytes(b"not-a-real-image")
        recent = datetime(2026, 9, 28, 12, tzinfo=timezone.utc).timestamp()
        for path in self.source.iterdir():
            os.utime(path, (recent, recent))
        self.store_root = self.root / "generated-local-audits"
        self.store = LocalDatasetStore(
            base_config=ROOT / "runtime_datasets.json",
            root=self.store_root,
        )
        self.client = TestClient(
            create_app(
                results_root=self.root / "runs",
                local_dataset_store=self.store,
            )
        )

    def test_scan_is_selectable_persistent_and_uses_scan_date(self) -> None:
        response = self.client.post("/api/local-datasets", json={
            "source_path": str(self.source),
            "display_name": "심사자 회사 자료",
        })
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        profile = body["dataset"]["profile"]
        self.assertTrue(profile.startswith("local-reviewer-files-"))
        self.assertEqual(body["dataset"]["origin"], "LOCAL")
        self.assertEqual(body["dataset"]["display_label"], "내 자료 · 심사자 회사 자료")
        self.assertEqual(body["audit"]["file_count"], 4)
        self.assertEqual(body["audit"]["parsed_file_count"], 3)
        self.assertEqual(body["audit"]["unsupported_file_count"], 1)
        self.assertGreaterEqual(body["audit"]["pii_finding_count"], 1)
        self.assertGreaterEqual(body["audit"]["duplicate_group_count"], 1)
        self.assertTrue(body["audit"]["local_only"])
        self.assertEqual(
            body["readiness"]["readiness"]["as_of_date"],
            body["audit"]["as_of_date"],
        )
        self.assertEqual(
            body["readiness"]["readiness"]["flags"]["future_modified_at_count"], 0
        )

        datasets = self.client.get("/api/datasets").json()["datasets"]
        self.assertEqual(datasets[-1]["profile"], profile)
        self.assertEqual(datasets[-1]["source_root_name"], "reviewer-files")
        self.assertEqual(self.client.get(f"/api/readiness/{profile}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/onboarding/{profile}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/tasks/{profile}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/findings/{profile}").status_code, 200)

        reopened = LocalDatasetStore(
            base_config=ROOT / "runtime_datasets.json",
            root=self.store_root,
        )
        self.assertTrue(reopened.contains(profile))
        self.assertEqual(reopened.audit(profile).file_count, 4)

    def test_rescan_is_stable_and_delete_never_touches_source(self) -> None:
        first = self.client.post("/api/local-datasets", json={
            "source_path": str(self.source),
        }).json()
        profile = first["dataset"]["profile"]
        (self.source / "new.txt").write_text("new policy", encoding="utf-8")
        second = self.client.post("/api/local-datasets", json={
            "source_path": f'"{self.source}"',
        })
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["dataset"]["profile"], profile)
        self.assertEqual(second.json()["audit"]["file_count"], 5)

        deleted = self.client.delete(f"/api/local-datasets/{profile}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(deleted.json()["source_files_deleted"])
        self.assertTrue((self.source / "new.txt").exists())
        self.assertEqual(self.client.get(f"/api/local-datasets/{profile}").status_code, 404)
        self.assertNotIn(
            profile,
            {item["profile"] for item in self.client.get("/api/datasets").json()["datasets"]},
        )

    def test_capabilities_and_safe_path_errors_are_explicit(self) -> None:
        capabilities = self.client.get("/api/capabilities").json()
        self.assertEqual(capabilities["mode"], "LOCAL_REVIEW")
        self.assertTrue(capabilities["local_dataset_scan"])
        self.assertFalse(capabilities["ai_task_execution"])
        self.assertEqual(
            capabilities["supported_extensions"],
            [".txt", ".pdf", ".docx", ".csv", ".xlsx"],
        )

        missing = self.client.post("/api/local-datasets", json={
            "source_path": str(self.root / "missing"),
        })
        self.assertEqual(missing.status_code, 422)
        self.assertIn("SOURCE_NOT_FOUND", missing.json()["detail"])

        overlap = self.client.post("/api/local-datasets", json={
            "source_path": str(self.root),
        })
        self.assertEqual(overlap.status_code, 422)
        self.assertIn("SOURCE_OVERLAPS_OUTPUT", overlap.json()["detail"])

        unavailable = TestClient(create_app(results_root=self.root / "plain-runs"))
        self.assertFalse(unavailable.get("/api/capabilities").json()["local_dataset_scan"])
        self.assertEqual(
            unavailable.post(
                "/api/local-datasets", json={"source_path": str(self.source)}
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
