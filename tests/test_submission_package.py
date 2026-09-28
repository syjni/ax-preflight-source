from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.build_submission_package import (
    ARTIFACT_FILES,
    ARTIFACT_PREFIXES,
    CORE_PREFIXES,
    NONPORTABLE_TRACKED_PREFIXES,
    REQUIRED_CLOSURE_FILES,
    ZIP_FIXED_TIMESTAMP,
    _filesystem_path,
    candidate_paths,
    safe_extract,
    verify_extraction,
)


class SubmissionPackageInventoryTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).resolve().parents[1] / ".git").exists(), "source inventory requires Git metadata")
    def test_inventory_contains_complete_current_core_and_required_closure(self) -> None:
        paths = set(candidate_paths())
        self.assertTrue(REQUIRED_CLOSURE_FILES <= paths)
        for prefix in CORE_PREFIXES:
            self.assertTrue(any(path.startswith(prefix) for path in paths), prefix)
        for prefix in ARTIFACT_PREFIXES:
            self.assertTrue(any(path.startswith(prefix) for path in paths), prefix)
        self.assertTrue(ARTIFACT_FILES <= paths)
        self.assertTrue(any(path.startswith("results_console/dist/") for path in paths))

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / ".git").exists(), "source inventory requires Git metadata")
    def test_inventory_excludes_mutable_and_historical_package_output(self) -> None:
        paths = candidate_paths()
        self.assertFalse(any(path.startswith("artifacts/product_runs/") for path in paths))
        self.assertFalse(any(path.startswith("artifacts/product_batches/") for path in paths))
        self.assertFalse(any(path.startswith("artifacts/submission/") for path in paths))
        self.assertFalse(any(path.startswith("artifacts/final_submission_audit/") for path in paths))
        self.assertFalse(any(path.startswith("_review_v2/") for path in paths))
        self.assertFalse(any(path.endswith("state.json") for path in paths))
        self.assertFalse(any(path.endswith(".map") for path in paths))
        for prefix in NONPORTABLE_TRACKED_PREFIXES:
            self.assertFalse(any(path.startswith(prefix) for path in paths), prefix)

    def test_verify_extraction_reports_missing_file_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({
                    "files": [{"path": "missing.txt", "size_bytes": 1, "sha256": "0" * 64}],
                }),
                encoding="utf-8",
            )

            result = verify_extraction(root / "extracted", manifest)

        self.assertFalse(result["passed"])
        self.assertEqual(result["missing"], ["missing.txt"])

    def test_safe_extract_restores_deterministic_fixture_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "fixture.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                info = zipfile.ZipInfo("fixture.txt", date_time=ZIP_FIXED_TIMESTAMP)
                archive.writestr(info, b"fixture")

            destination = root / "extracted"
            safe_extract(archive_path, destination)

            observed = datetime.fromtimestamp(
                (destination / "fixture.txt").stat().st_mtime,
                tz=timezone.utc,
            )
        self.assertEqual(
            observed.replace(tzinfo=None),
            datetime(*ZIP_FIXED_TIMESTAMP),
        )

    def test_safe_extract_and_verify_support_long_nested_paths(self) -> None:
        root = Path(tempfile.mkdtemp())
        try:
            relative = "/".join(["nested-segment-12345"] * 12 + ["fixture.txt"])
            archive_path = root / "long-path.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                info = zipfile.ZipInfo(relative, date_time=ZIP_FIXED_TIMESTAMP)
                archive.writestr(info, b"fixture")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({
                    "files": [{
                        "path": relative,
                        "size_bytes": 7,
                        "sha256": hashlib.sha256(b"fixture").hexdigest(),
                    }],
                }),
                encoding="utf-8",
            )

            destination = root / "extracted"
            safe_extract(archive_path, destination)
            result = verify_extraction(destination, manifest)
        finally:
            shutil.rmtree(_filesystem_path(root))

        self.assertTrue(result["passed"])
        self.assertEqual(result["file_count"], 1)


if __name__ == "__main__":
    unittest.main()
