from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ax_scanner.models import ParseStatus, ScanReport
from ax_scanner.reports import validate_report, write_json_schema, write_report
from ax_scanner.scanner import scan_folder
from ax_scanner.telemetry import detect_live_llm_status
from scripts.create_mini_dataset import create_mini_dataset


class ScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = create_mini_dataset(Path(self._temp.name) / "mini_company")
        self.live = detect_live_llm_status({}, local_runtime_available=False)
        self.report = scan_folder(self.root, live_llm=self.live)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_recursive_metadata_and_stable_file_ids(self) -> None:
        self.assertEqual(self.report.scan_metadata.file_count, 10)
        second = scan_folder(self.root, live_llm=self.live)
        first_ids = {item.relative_path: item.file_id for item in self.report.files}
        second_ids = {item.relative_path: item.file_id for item in second.files}
        self.assertEqual(first_ids, second_ids)
        record = next(item for item in self.report.files if item.relative_path == "docs/contact.txt")
        self.assertEqual(record.filename, "contact.txt")
        self.assertEqual(record.extension, ".txt")
        self.assertRegex(record.sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(record.modified_at.isoformat().replace("+00:00", "Z"), "2026-09-19T00:00:00Z")

    def test_sha256_exact_duplicate_detection(self) -> None:
        self.assertEqual(len(self.report.duplicates), 1)
        duplicate = self.report.duplicates[0]
        self.assertEqual(duplicate.copy_count, 2)
        self.assertEqual(
            duplicate.relative_paths,
            ["archive/contact_copy.txt", "docs/contact.txt"],
        )

    def test_probable_versions_use_only_filename_signals(self) -> None:
        self.assertEqual(len(self.report.probable_version_groups), 1)
        group = self.report.probable_version_groups[0]
        self.assertEqual(group.normalized_name, "return policy")
        self.assertEqual(len(group.candidates), 2)

    def test_report_contains_masked_text_but_no_raw_pii(self) -> None:
        payload = self.report.model_dump_json()
        for raw in (
            "900101-1234567",
            "010-1234-5678",
            "owner@example.com",
            "110-123-456789",
            "sales@hanbit.example",
        ):
            self.assertNotIn(raw, payload)
        self.assertGreaterEqual(len(self.report.pii_findings), 4)
        contact = next(item for item in self.report.files if item.relative_path == "docs/contact.txt")
        self.assertTrue(contact.text_is_masked)
        self.assertIn("[RRN_MASKED]", contact.text)

    def test_unsupported_file_is_reported_not_crashed(self) -> None:
        unsupported = next(item for item in self.report.files if item.relative_path == "unsupported.bin")
        self.assertEqual(unsupported.parse_status, ParseStatus.UNSUPPORTED)
        self.assertEqual(self.report.scan_metadata.unsupported_file_count, 1)

    def test_ocr_required_is_reported(self) -> None:
        self.assertEqual(len(self.report.unreadable_sources), 1)
        self.assertEqual(self.report.unreadable_sources[0].relative_path, "scans/invoice_scan.pdf")
        self.assertTrue(self.report.unreadable_sources[0].requires_ocr)

    def test_json_serialization_schema_and_round_trip_validation(self) -> None:
        output = Path(self._temp.name) / "scan_report.json"
        schema = Path(self._temp.name) / "scan_report.schema.json"
        write_report(self.report, output)
        write_json_schema(schema)
        validated = validate_report(output)
        self.assertIsInstance(validated, ScanReport)
        schema_payload = json.loads(schema.read_text(encoding="utf-8"))
        self.assertEqual(schema_payload["title"], "ScanReport")
        self.assertEqual(set(schema_payload["required"]), {
            "scan_metadata", "files", "duplicates", "probable_version_groups",
            "pii_findings", "unreadable_sources", "tables", "live_llm",
        })

    def test_live_llm_is_explicitly_pending_without_credentials(self) -> None:
        self.assertEqual(self.report.live_llm.status, "LIVE_LLM_PENDING")
        self.assertEqual(self.report.live_llm.tasks, [])
        self.assertFalse(self.report.scan_metadata.llm_dependency_required)


if __name__ == "__main__":
    unittest.main()
