from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.create_ceiling_dataset import generate_ceiling_dataset
from scripts.validate_ceiling_artifacts import validate_ceiling_benchmark


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


class CeilingDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temp.name) / "first"
        cls.paths = generate_ceiling_dataset(cls.root)
        cls.validation = validate_ceiling_benchmark(cls.root)
        cls.manifest = json.loads((cls.root / "dataset_manifest.json").read_text(encoding="utf-8"))
        cls.benchmark = json.loads((cls.root / "benchmark_tasks.json").read_text(encoding="utf-8"))
        cls.ground_truth = json.loads((cls.root / "ground_truth.json").read_text(encoding="utf-8"))
        cls.controls = json.loads((cls.root / "control_sources.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def test_deterministic_dataset_regeneration(self) -> None:
        second_root = Path(self._temp.name) / "second"
        generate_ceiling_dataset(second_root)
        self.assertEqual(_tree_hashes(self.root), _tree_hashes(second_root))

    def test_ground_truth_regeneration_matches_benchmark(self) -> None:
        truth_by_id = {entry["task_id"]: entry for entry in self.ground_truth["tasks"]}
        self.assertEqual(len(truth_by_id), len(self.benchmark["tasks"]))
        for task in self.benchmark["tasks"]:
            self.assertEqual(truth_by_id[task["task_id"]]["expected_answer"], task["expected_answer"])

    def test_benchmark_schema_and_scoring_method_validation(self) -> None:
        required = {
            "task_id", "category", "question", "expected_answer", "scoring_method",
            "required_sources", "primary_blocker", "control",
        }
        self.assertGreaterEqual(len(self.benchmark["tasks"]), 15)
        self.assertTrue(all(required <= set(task) for task in self.benchmark["tasks"]))
        self.assertTrue(all(task["scoring_method"]["type"] in {"numeric", "exact", "set", "llm_judge"}
                            for task in self.benchmark["tasks"]))
        self.assertTrue(next(check for check in self.validation["checks"]
                             if check["name"] == "benchmark_schema_and_scoring")["passed"])

    def test_required_source_and_control_source_integrity(self) -> None:
        manifest_sources = {entry["relative_path"] for entry in self.manifest["files"]}
        for task in self.benchmark["tasks"]:
            self.assertTrue(set(task["required_sources"]) <= manifest_sources)
        expected_controls = sorted({
            source for task in self.benchmark["tasks"] if task["control"] for source in task["required_sources"]
        })
        self.assertEqual(self.controls["protected_sources"], expected_controls)
        self.assertGreaterEqual(len(self.controls["control_task_ids"]), 4)

    def test_deterministic_tool_contract_is_not_reported_as_runtime_feasibility(self) -> None:
        check = next(check for check in self.validation["checks"] if check["name"] == "deterministic_tool_contract_validation")
        self.assertTrue(check["passed"], check["detail"])
        self.assertEqual(check["detail"]["validated_tasks"], len(self.benchmark["tasks"]))
        self.assertIn("not Kiro/runtime feasibility", check["detail"]["scope"])
        for task in self.benchmark["tasks"]:
            self.assertNotIn("TABLE_", task["question"])
            self.assertNotIn("TABLE_", json.dumps(task["tool_plan"], ensure_ascii=False))

    def test_runtime_leakage_prevention(self) -> None:
        check = next(check for check in self.validation["checks"] if check["name"] == "runtime_leakage_prevention")
        self.assertTrue(check["passed"], check["detail"])
        for path in self.paths["source_root"].rglob("*"):
            if path.is_file():
                data = path.read_bytes().lower()
                self.assertNotIn(b"expected_answer", data)
                self.assertNotIn(b"primary_blocker", data)
        report = json.loads((self.root / "ceiling_scan_report.json").read_text(encoding="utf-8"))
        self.assertFalse(any(table["sheet_name"] == "SearchGuide" for table in report["tables"]))

    def test_independent_truth_and_blind_runtime_samples_are_generated(self) -> None:
        truth_check = next(check for check in self.validation["checks"] if check["name"] == "independent_source_truth_verification")
        self.assertTrue(truth_check["passed"], truth_check["detail"])
        samples = json.loads((self.root / "runtime_blind_samples.json").read_text(encoding="utf-8"))
        self.assertEqual(samples["execution_status"], "NOT_RUN")
        self.assertEqual(len(samples["samples"]), len(self.benchmark["tasks"]))
        self.assertTrue(all(set(sample) == {"category", "question", "runtime_prompt"} for sample in samples["samples"]))

    def test_generated_dataset_is_clean_and_uses_all_p0_formats(self) -> None:
        self.assertEqual(self.manifest["condition"], "ceiling")
        self.assertGreaterEqual(self.manifest["file_count"], 20)
        self.assertEqual(set(self.manifest["format_counts"]), {"txt", "pdf", "docx", "csv", "xlsx"})
        self.assertTrue(all(entry["runtime_facing"] for entry in self.manifest["files"]))


if __name__ == "__main__":
    unittest.main()
