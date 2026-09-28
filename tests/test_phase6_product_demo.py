from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ax_mcp.runtime_dataset import (
    resolve_runtime_dataset,
    runtime_identity,
    validate_runtime_resource_leakage,
)
from ax_scanner.models import ScanReport
from readiness_score import calculate_readiness_score, score_scan_report_file
from portable_path_order import frozen_sorted_files
from scripts.run_phase6_demo import (
    ARTIFACT_ROOT,
    FIXED_SOURCE_MTIME,
    PROFILES,
    QUESTION_PATH,
    build_schedule,
    execute,
    prepare_static_artifacts,
    request_payload,
)
from scripts.verify_phase6_demo import Phase6VerificationError, verify_phase6_demo


ROOT = Path(__file__).resolve().parents[1]
PROTECTED_TREE_HASHES = {
    "sample_data/mini_company": "f26bbb6c5da7520b4ff11cd2415026e5b21118bb00c8212564fc9fd1778d7bfe",
    "sample_data/ceiling_company": "ae5d6c78c847a37860098dd527abecc040aded07fecccadf0c86d0739d00e78c",
    "sample_data/before_variants": "735996d49dcec1d65c3497d2805226408dd7d4ab0f9a97b57d28a127eaba0275",
    "experiment/frozen": "46657a5887019e936c80af7156a5ac722aa7c30f25b95264d0ec55370e8de9b4",
}


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in frozen_sorted_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class Phase6ProductDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.datasets = {
            profile: resolve_runtime_dataset(profile) for profile in PROFILES
        }
        cls.reports = {
            profile: ScanReport.model_validate_json(
                dataset.scan_report.read_text(encoding="utf-8")
            )
            for profile, dataset in cls.datasets.items()
        }
        cls.readiness = {
            profile: score_scan_report_file(dataset.scan_report)
            for profile, dataset in cls.datasets.items()
        }

    def test_static_readiness_total_and_all_five_dimensions_are_identical(self) -> None:
        before = self.readiness[PROFILES[0]]
        after = self.readiness[PROFILES[1]]
        self.assertEqual(before["readiness_score"], after["readiness_score"])
        self.assertEqual(before["dimensions"], after["dimensions"])
        self.assertEqual(
            set(before["dimensions"]),
            {"accessibility", "completeness", "redundancy", "timeliness", "safety"},
        )

    def test_version_warning_decreases_and_is_unscored(self) -> None:
        before = self.reports[PROFILES[0]]
        after = self.reports[PROFILES[1]]
        self.assertGreater(len(before.probable_version_groups), 0)
        self.assertLess(
            len(after.probable_version_groups),
            len(before.probable_version_groups),
        )
        for profile, report in self.reports.items():
            without_warning = report.model_copy(
                update={"probable_version_groups": []}, deep=True
            )
            self.assertEqual(
                calculate_readiness_score(without_warning.model_dump(mode="json")),
                self.readiness[profile],
            )

    def test_runtime_profile_matches_source_and_has_no_leakage(self) -> None:
        identities = {}
        for profile, dataset in self.datasets.items():
            identities[profile] = runtime_identity(dataset)
            leakage = validate_runtime_resource_leakage(dataset)
            self.assertTrue(leakage["passed"], leakage)
            self.assertEqual(identities[profile]["file_count"], 2)
            mtimes = {
                file.modified_at.isoformat() for file in self.reports[profile].files
            }
            self.assertEqual(mtimes, {FIXED_SOURCE_MTIME})
        self.assertEqual(
            identities[PROFILES[0]]["file_count"],
            identities[PROFILES[1]]["file_count"],
        )

    def test_all_six_requests_use_byte_identical_question_and_alternate(self) -> None:
        question_bytes = QUESTION_PATH.read_bytes().rstrip(b"\r\n")
        question = question_bytes.decode("utf-8")
        payloads = [
            request_payload(
                profile=profile,
                run_id=f"test-{order}",
                model="claude-sonnet-5",
                question=question,
            )
            for order, profile, _ in build_schedule(3)
        ]
        self.assertEqual(
            [payload["dataset"] for payload in payloads],
            [PROFILES[0], PROFILES[1]] * 3,
        )
        self.assertEqual(
            {payload["question"].encode("utf-8") for payload in payloads},
            {question_bytes},
        )

    def test_existing_research_and_product_baseline_datasets_are_unchanged(self) -> None:
        for relative, expected in PROTECTED_TREE_HASHES.items():
            with self.subTest(relative=relative):
                self.assertEqual(tree_hash(ROOT / relative), expected)

    def test_manifest_records_question_once_and_not_inside_runtime_roots(self) -> None:
        manifest = json.loads(
            (ROOT / "artifacts/phase6_product_demo/dataset-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["question"].encode("utf-8"),
                         QUESTION_PATH.read_bytes().rstrip(b"\r\n"))
        def keys(value):
            if isinstance(value, dict):
                return set(value).union(*(keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(item) for item in value))
            return set()

        self.assertNotIn("expected_answer", keys(manifest))
        for dataset in self.datasets.values():
            self.assertFalse(any(
                path.name == "question.txt"
                for path in dataset.source_root.rglob("*") if path.is_file()
            ))

    def test_official_run_receipts_are_complete_hash_bound_and_leak_free(self) -> None:
        artifact_root = ROOT / "artifacts/phase6_product_demo"
        manifest = json.loads(
            (artifact_root / "run-manifest.json").read_text(encoding="utf-8")
        )
        summary = json.loads(
            (artifact_root / "summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["mode"], "official")
        self.assertTrue(manifest["fresh_process_per_run"])
        self.assertFalse(manifest["raw_kiro_output_used_as_product_result"])
        self.assertFalse(manifest["raw_kiro_output_persisted_as_customer_log"])
        self.assertEqual(len(manifest["runs"]), 6)
        self.assertEqual(summary["run_count"], 6)
        self.assertEqual(summary["run_ids"], [run["run_id"] for run in manifest["runs"]])
        self.assertEqual(len(set(summary["run_ids"])), 6)
        self.assertEqual(
            [run["dataset_profile"] for run in summary["runs"]],
            [PROFILES[0], PROFILES[1]] * 3,
        )
        self.assertEqual(
            {run["question_utf8_sha256"] for run in summary["runs"]},
            {manifest["question_utf8_sha256"]},
        )
        for run in summary["runs"]:
            with self.subTest(run_id=run["run_id"]):
                directory = ROOT / run["run_artifact_directory"]
                delivery = directory / "delivery.json"
                evidence = directory / "evidence-check.json"
                responses = sorted((directory / "tool-responses").glob("*.json"))
                self.assertTrue(delivery.is_file())
                self.assertTrue(evidence.is_file())
                self.assertEqual(hashlib.sha256(delivery.read_bytes()).hexdigest(),
                                 run["delivery_sha256"])
                self.assertEqual(hashlib.sha256(evidence.read_bytes()).hexdigest(),
                                 run["evidence_check_sha256"])
                self.assertEqual(len(responses), run["tool_response_count"])
                self.assertFalse(any(
                    "stdout" in path.name.casefold() or "finaltext" in path.name.casefold()
                    for path in directory.rglob("*") if path.is_file()
                ))

    def test_official_observed_behavior_meets_product_sanity_threshold(self) -> None:
        summary = json.loads(
            (ROOT / "artifacts/phase6_product_demo/summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(summary["sanity_criteria"]["passed"])
        self.assertGreaterEqual(
            summary["sanity_criteria"]["before_conflicting_abstention_count"], 2
        )
        self.assertGreaterEqual(summary["sanity_criteria"]["after_answered_count"], 2)
        self.assertGreaterEqual(
            summary["citation_checks"]["before_conflict_runs_with_both_sources"], 2
        )
        self.assertGreaterEqual(
            summary["citation_checks"]["after_answered_runs_with_current_source"], 2
        )

    def test_official_rerun_is_rejected_before_prepare_or_scanner(self) -> None:
        with (
            patch("scripts.run_phase6_demo.prepare_static_artifacts") as prepare,
            patch("scripts.run_phase6_demo._run_scanner") as scanner,
        ):
            with self.assertRaises(FileExistsError):
                execute(
                    mode="official",
                    repetitions=3,
                    model="claude-sonnet-5",
                    timeout_seconds=1,
                    kiro_cli="must-not-be-resolved",
                    execution_id="must-not-run",
                )
        prepare.assert_not_called()
        scanner.assert_not_called()

    def test_rejected_official_rerun_preserves_static_bytes_and_mtime(self) -> None:
        paths = [
            ARTIFACT_ROOT / name for name in (
                "before-scan-report.json",
                "after-scan-report.json",
                "dataset-manifest.json",
                "remediation-receipt.json",
            )
        ]
        before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
        }
        with self.assertRaises(FileExistsError):
            execute(
                mode="official",
                repetitions=3,
                model="claude-sonnet-5",
                timeout_seconds=1,
                kiro_cli="must-not-be-resolved",
                execution_id="must-not-run",
            )
        after = {
            path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
        }
        self.assertEqual(before, after)

    def test_prepare_only_path_cannot_overwrite_official_static_artifacts(self) -> None:
        path = ARTIFACT_ROOT / "dataset-manifest.json"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        with patch("scripts.run_phase6_demo._run_scanner") as scanner:
            with self.assertRaises(FileExistsError):
                prepare_static_artifacts()
        scanner.assert_not_called()
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))

    def test_post_freeze_pilot_reads_static_artifacts_without_scanner(self) -> None:
        paths = [
            ARTIFACT_ROOT / name for name in (
                "before-scan-report.json",
                "after-scan-report.json",
                "dataset-manifest.json",
                "remediation-receipt.json",
            )
        ]
        before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
        }
        with (
            patch("scripts.run_phase6_demo._run_scanner") as scanner,
            patch(
                "scripts.run_phase6_demo._kiro_executable",
                side_effect=RuntimeError("stop before execution"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop before execution"):
                execute(
                    mode="pilot",
                    repetitions=1,
                    model="claude-sonnet-5",
                    timeout_seconds=1,
                    kiro_cli="must-not-be-resolved",
                    execution_id="regression-no-scanner",
                )
        scanner.assert_not_called()
        after = {
            path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
        }
        self.assertEqual(before, after)

    def test_phase6_verifier_passes_current_frozen_artifacts(self) -> None:
        result = verify_phase6_demo(root=ROOT)
        self.assertTrue(result["passed"])
        self.assertEqual(result["official_run_count"], 6)
        self.assertEqual(result["state_json_count"], 0)

    def test_phase6_verifier_rejects_tampered_frozen_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary)
            shutil.copytree(
                ROOT / "artifacts/phase6_product_demo",
                copied_root / "artifacts/phase6_product_demo",
            )
            shutil.copytree(
                ROOT / "sample_data/product_demo",
                copied_root / "sample_data/product_demo",
            )
            (copied_root / ".kiro/agents").mkdir(parents=True)
            target = copied_root / "artifacts/phase6_product_demo/RESULTS.md"
            target.write_bytes(target.read_bytes() + b"\ntampered\n")
            with self.assertRaises(Phase6VerificationError):
                verify_phase6_demo(root=copied_root)

    def test_phase6_tree_has_no_unterminated_state(self) -> None:
        self.assertEqual(list(ARTIFACT_ROOT.rglob("state.json")), [])

    def test_diagnostic_runs_are_preserved_as_runtime_errors(self) -> None:
        receipt = json.loads(
            (ARTIFACT_ROOT / "DIAGNOSTIC_CLOSURE.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["active_process_count"], 0)
        self.assertEqual(
            {run["run_id"] for run in receipt["runs"]},
            {
                "phase6demo-diagnostic-after-001",
                "phase6demo-diagnostic-after-002",
            },
        )
        for run in receipt["runs"]:
            delivery = json.loads(
                (ROOT / run["delivery_path"]).read_text(encoding="utf-8")
            )
            evidence = json.loads(
                (ROOT / run["evidence_check_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(delivery["run_id"], run["run_id"])
            self.assertEqual(delivery["dataset"], "demo-return-after")
            self.assertEqual(delivery["delivery_status"], "REJECTED")
            self.assertEqual(delivery["reject_reason"], "RUNTIME_ERROR")
            self.assertEqual(evidence["delivery_sha256"], run["delivery_sha256"])


if __name__ == "__main__":
    unittest.main()
