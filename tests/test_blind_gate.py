from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.blind_gate import (
    REPETITIONS_PER_TASK,
    STRESS_TASK_IDS,
    prepare_blind_gate,
    validate_blind_gate,
    validate_prompt_leakage,
)
from scripts.generate_ceiling_dataset import generate_ceiling_dataset
from scripts.validate_ceiling_benchmark import validate_ceiling_benchmark


class BlindKiroRuntimeGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        generate_ceiling_dataset(self.root)
        (self.root / "ceiling_validation.json").write_text(
            json.dumps(validate_ceiling_benchmark(self.root), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (self.root / "scripts").mkdir()
        shutil.copyfile(Path(__file__).parents[1] / "scripts" / "runtime_prompt.py", self.root / "scripts" / "runtime_prompt.py")
        (self.root / ".kiro" / "agents").mkdir(parents=True)
        shutil.copyfile(
            Path(__file__).parents[1] / ".kiro" / "agents" / "ax-evaluation.json",
            self.root / ".kiro" / "agents" / "ax-evaluation.json",
        )
        shutil.copyfile(Path(__file__).parents[1] / "runtime_datasets.json", self.root / "runtime_datasets.json")
        config_path = self.root / ".kiro" / "agents" / "ax-evaluation.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["mcpServers"]["ax-tools"]["env"]["AX_RUNTIME_DATASET_CONFIG"] = str(self.root / "runtime_datasets.json")
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.validation = prepare_blind_gate(self.root)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_gate_is_prepared_but_not_run(self) -> None:
        self.assertTrue(self.validation["passed"], self.validation)
        results = json.loads((self.root / "blind_gate_results.json").read_text(encoding="utf-8"))
        self.assertEqual(results["execution_status"], "NOT_RUN")
        self.assertEqual(len(results["runs"]), len(STRESS_TASK_IDS) * REPETITIONS_PER_TASK)
        self.assertTrue(all(run["run_status"] == "NOT_RUN" for run in results["runs"]))
        required = {
            "task_id", "repetition", "raw_final_output", "parsed_final_answer", "source_ids",
            "abstain", "tool_sequence", "tool_call_count", "system_failure", "scoring_result",
            "retrieval_outcome", "notes",
        }
        self.assertTrue(all(required <= set(run) for run in results["runs"]))

    def test_prompts_are_exact_constructor_outputs_without_leakage(self) -> None:
        leakage = validate_prompt_leakage(self.root)
        self.assertTrue(leakage["passed"], leakage)
        self.assertTrue(leakage["canonical_constructor_match"])
        self.assertEqual(leakage["prompt_count"], len(STRESS_TASK_IDS))
        prompt_text = (self.root / "blind_gate_prompts.md").read_text(encoding="utf-8")
        for task_id in STRESS_TASK_IDS:
            self.assertNotIn(task_id, prompt_text)

    def test_frozen_hash_verification_detects_silent_dataset_change(self) -> None:
        manifest = json.loads((self.root / "blind_gate_manifest.json").read_text(encoding="utf-8"))
        target = self.root / manifest["frozen_artifacts"]["dataset"]["files"][0]["path"]
        target.write_bytes(target.read_bytes() + b"changed")
        validation = validate_blind_gate(self.root)
        self.assertFalse(validation["passed"])
        self.assertIn("frozen_artifact_changed", {item["type"] for item in validation["violations"]})

    def test_result_recording_is_mutable_without_weakening_frozen_inputs(self) -> None:
        path = self.root / "blind_gate_results.json"
        results = json.loads(path.read_text(encoding="utf-8"))
        results["execution_status"] = "IN_PROGRESS"
        run = results["runs"][0]
        run.update({
            "raw_final_output": "{\"final_answer\":10}",
            "parsed_final_answer": 10,
            "source_ids": ["observed-source"],
            "abstain": False,
            "tool_sequence": ["search_documents", "query_table"],
            "tool_call_count": 2,
            "system_failure": False,
            "scoring_result": "CORRECT_SUPPORTED",
            "retrieval_outcome": "REQUIRED_SOURCES_RETRIEVED",
            "notes": "test fixture only",
            "run_status": "RECORDED",
        })
        path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        validation = validate_blind_gate(self.root)
        self.assertTrue(validation["passed"], validation)


if __name__ == "__main__":
    unittest.main()
