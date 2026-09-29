from __future__ import annotations

import os
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ax_product.api import ROOT, create_app
from ax_product.local_datasets import (
    LocalDatasetError,
    LocalDatasetRequest,
    LocalDatasetStore,
)


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
        self.allowed_roots = patch.dict(
            os.environ, {"AX_ALLOWED_SCAN_ROOTS": str(self.root)}
        )
        self.allowed_roots.start()
        self.addCleanup(self.allowed_roots.stop)
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
        self.assertEqual(body["audit"]["source_mode"], "PATH")
        self.assertFalse(body["audit"]["source_files_copied"])
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
        first_revision = first["audit"]["revision_fingerprint"]
        same = self.client.post("/api/local-datasets", json={
            "source_path": str(self.source),
            "display_name": "표시 이름 변경",
        })
        self.assertEqual(same.status_code, 201, same.text)
        self.assertEqual(
            same.json()["audit"]["revision_fingerprint"], first_revision
        )
        (self.source / "new.txt").write_text("new policy", encoding="utf-8")
        second = self.client.post("/api/local-datasets", json={
            "source_path": f'"{self.source}"',
        })
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["dataset"]["profile"], profile)
        self.assertEqual(second.json()["audit"]["file_count"], 5)
        self.assertNotEqual(
            second.json()["audit"]["revision_fingerprint"], first_revision
        )

        deleted = self.client.delete(f"/api/local-datasets/{profile}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(deleted.json()["source_files_deleted"])
        self.assertFalse(deleted.json()["managed_copy_deleted"])
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
        self.assertTrue(capabilities["local_file_upload"])
        self.assertTrue(capabilities["local_path_scan"])
        self.assertFalse(capabilities["ai_task_execution"])
        self.assertTrue(capabilities["pdf_table_extraction"])
        self.assertEqual(capabilities["max_upload_files"], self.store.max_files)
        self.assertEqual(
            capabilities["max_upload_file_bytes"], self.store.max_file_bytes
        )
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

    def test_path_scan_is_disabled_without_an_explicit_allowed_root(self) -> None:
        with patch.dict(os.environ, {"AX_ALLOWED_SCAN_ROOTS": ""}):
            store = LocalDatasetStore(
                base_config=ROOT / "runtime_datasets.json",
                root=self.root / "no-path-store",
            )
        client = TestClient(create_app(
            results_root=self.root / "no-path-runs",
            local_dataset_store=store,
        ))

        capabilities = client.get("/api/capabilities").json()
        self.assertTrue(capabilities["local_dataset_scan"])
        self.assertTrue(capabilities["local_file_upload"])
        self.assertFalse(capabilities["local_path_scan"])
        blocked = client.post(
            "/api/local-datasets", json={"source_path": str(self.source)}
        )
        self.assertEqual(blocked.status_code, 403, blocked.text)
        self.assertEqual(blocked.json()["detail"], "PATH_SCAN_UNAVAILABLE")

    def test_path_scan_rejects_resolved_paths_outside_allowed_roots(self) -> None:
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: outside.rmdir())
        (outside / "secret.txt").write_text("secret", encoding="utf-8")
        self.addCleanup(lambda: (outside / "secret.txt").unlink(missing_ok=True))

        response = self.client.post(
            "/api/local-datasets", json={"source_path": str(outside)}
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("SOURCE_OUTSIDE_ALLOWED_ROOTS", response.json()["detail"])

    def test_path_scan_does_not_cross_project_ownership(self) -> None:
        first = self.store.scan(LocalDatasetRequest(
            source_path=str(self.source), project_id="prj_" + "1" * 32
        ))
        self.assertTrue(self.store.contains(first))

        with self.assertRaisesRegex(
            LocalDatasetError, "다른 프로젝트"
        ) as raised:
            self.store.scan(LocalDatasetRequest(
                source_path=str(self.source), project_id="prj_" + "2" * 32
            ))
        self.assertEqual(raised.exception.code, "SOURCE_ASSIGNED_TO_OTHER_PROJECT")

    def test_browser_upload_is_local_persistent_and_deleted_with_record(self) -> None:
        response = self.client.post(
            "/api/local-datasets/upload",
            files=[
                ("files", ("policy.txt", "반품 기간은 14일입니다.".encode("utf-8"), "text/plain")),
                ("files", ("orders.csv", b"order_id,amount\nA-1,12000\n", "text/csv")),
            ],
            data={
                "relative_paths": json.dumps(
                    ["review-files/policy.txt", "review-files/tables/orders.csv"]
                ),
                "display_name": "브라우저 선택 자료",
                "source_root_name": "review-files",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        profile = body["dataset"]["profile"]
        self.assertEqual(body["audit"]["source_mode"], "UPLOAD")
        self.assertTrue(body["audit"]["source_files_copied"])
        self.assertTrue(body["audit"]["managed_copy_deleted_with_record"])
        self.assertEqual(body["audit"]["source_root_name"], "review-files")
        self.assertEqual(body["audit"]["file_count"], 2)
        managed_roots = list((self.store_root / "uploads").iterdir())
        self.assertEqual(len(managed_roots), 1)
        self.assertTrue((managed_roots[0] / "review-files" / "policy.txt").is_file())

        deleted = self.client.delete(f"/api/local-datasets/{profile}")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["managed_copy_deleted"])
        self.assertFalse(managed_roots[0].exists())

    def test_browser_upload_rejects_path_escape_and_cleans_allocation(self) -> None:
        response = self.client.post(
            "/api/local-datasets/upload",
            files=[("files", ("secret.txt", b"secret", "text/plain"))],
            data={"relative_paths": json.dumps(["../secret.txt"])},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("INVALID_UPLOAD_PATH", response.json()["detail"])
        upload_root = self.store_root / "uploads"
        self.assertFalse(upload_root.exists() and any(upload_root.iterdir()))

    def test_browser_upload_accepts_1001_small_files(self) -> None:
        files = [
            ("files", (f"file-{index:04d}.unsupported", b"", "application/octet-stream"))
            for index in range(1001)
        ]
        response = self.client.post(
            "/api/local-datasets/upload",
            files=files,
            data={
                "relative_paths": json.dumps(
                    [f"review/file-{index:04d}.unsupported" for index in range(1001)]
                ),
                "source_root_name": "review",
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["audit"]["file_count"], 1001)

    def test_upload_file_count_boundary_and_individual_size_are_enforced(self) -> None:
        with patch.dict(os.environ, {
            "AX_PRODUCT_LOCAL_SCAN_MAX_FILES": "2",
            "AX_PRODUCT_LOCAL_SCAN_MAX_FILE_BYTES": "4",
        }):
            store = LocalDatasetStore(
                base_config=ROOT / "runtime_datasets.json",
                root=self.root / "bounded-store",
            )
        client = TestClient(create_app(
            results_root=self.root / "bounded-runs",
            local_dataset_store=store,
        ))
        accepted = client.post(
            "/api/local-datasets/upload",
            files=[
                ("files", ("a.unsupported", b"1234", "application/octet-stream")),
                ("files", ("b.unsupported", b"1234", "application/octet-stream")),
            ],
            data={"relative_paths": json.dumps(["a.unsupported", "b.unsupported"])},
        )
        self.assertEqual(accepted.status_code, 201, accepted.text)

        too_many = client.post(
            "/api/local-datasets/upload",
            files=[
                ("files", (f"{name}.unsupported", b"1", "application/octet-stream"))
                for name in ("c", "d", "e")
            ],
            data={"relative_paths": json.dumps([
                "c.unsupported", "d.unsupported", "e.unsupported"
            ])},
        )
        self.assertEqual(too_many.status_code, 422, too_many.text)
        self.assertIn("FILE_LIMIT_EXCEEDED", too_many.json()["detail"])

        too_large = client.post(
            "/api/local-datasets/upload",
            files=[("files", ("large.txt", b"12345", "text/plain"))],
            data={"relative_paths": json.dumps(["large.txt"])},
        )
        self.assertEqual(too_large.status_code, 422, too_large.text)
        self.assertIn("FILE_SIZE_LIMIT_EXCEEDED", too_large.json()["detail"])


if __name__ == "__main__":
    unittest.main()
