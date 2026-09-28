from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.interactive_run import (
    EXPECTED_TOOLS,
    ROOT,
    _read_json,
    _validate_agent_invariants,
    finalize_run,
    prepare_run,
)


class InteractiveRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kiro_version = patch(
            "scripts.interactive_run._kiro_cli_version",
            return_value="kiro-cli-chat test-double",
        )
        self.kiro_version.start()
        self.addCleanup(self.kiro_version.stop)

    def test_prepare_and_finalize_keep_contract_metrics_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            prepared = prepare_run(
                run_dir,
                task_id="K03_DELAY_COMPENSATION_THRESHOLD",
                condition="Before",
                repetition=1,
                prompt="업무 범주: operations\n질문: 테스트",
                root=ROOT,
            )
            self.assertEqual(prepared["run_status"], "PREPARED")
            self.assertEqual(prepared["expected_runtime_profile"], "ceiling")
            self.assertEqual(prepared["actual_runtime_profile"], "ceiling")
            self.assertEqual((run_dir / "prompt.txt").read_text(encoding="utf-8"), "업무 범주: operations\n질문: 테스트")
            raw = (
                "```json\n"
                '{"final_answer":10,"unit":"곳","explanation":"근거","source_ids":["TABLE_x"],"abstain":false}'
                "\n```"
            )
            (run_dir / "raw_response.txt").write_bytes(raw.encode("utf-8"))
            recorded = finalize_run(run_dir, root=ROOT)
            self.assertEqual(recorded["run_status"], "RECORDED")
            self.assertFalse(recorded["output_contract_valid"])
            self.assertTrue(recorded["semantic_json_available"])
            result = json.loads((run_dir / "parsed_result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["parsed_result"]["final_answer"], 10)
            (ROOT / prepared["kiro_agent_config"]).unlink()

    def test_unknown_task_and_condition_fail_before_prepared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaises(ValueError):
                prepare_run(base / "unknown-task", task_id="UNKNOWN", condition="Before", repetition=1, prompt="x", root=ROOT)
            with self.assertRaises(ValueError):
                prepare_run(base / "unknown-condition", task_id="K01_RETURN_WINDOW", condition="Other", repetition=1, prompt="x", root=ROOT)
            self.assertFalse((base / "unknown-task").exists())
            self.assertFalse((base / "unknown-condition").exists())

    def test_prepare_rejects_requested_actual_runtime_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            with self.assertRaisesRegex(ValueError, "requires runtime profile"):
                prepare_run(
                    run_dir,
                    task_id="K01_RETURN_WINDOW",
                    condition="Before",
                    repetition=1,
                    prompt="x",
                    root=ROOT,
                    actual_runtime_profile="ceiling",
                )
            self.assertFalse(run_dir.exists())

    def test_finalize_runtime_mismatch_cannot_be_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            prepared = prepare_run(
                run_dir,
                task_id="K03_DELAY_COMPENSATION_THRESHOLD",
                condition="Before",
                repetition=1,
                prompt="x",
                root=ROOT,
            )
            metadata_path = run_dir / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["runtime_dataset_identity"]["dataset_name"] = "tampered"
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (run_dir / "raw_response.txt").write_text(
                '{"final_answer":null,"unit":null,"explanation":"x","source_ids":[],"abstain":true}',
                encoding="utf-8",
            )
            recorded = finalize_run(run_dir, root=ROOT)
            self.assertEqual(recorded["validity_status"], "INVALID")
            self.assertIn("recorded_runtime_identity_mismatch", recorded["validation_errors"])
            (ROOT / prepared["kiro_agent_config"]).unlink()

    def test_wrong_model_and_expanded_tool_surface_fail_validation(self) -> None:
        config = _read_json(ROOT / ".kiro/agents/ax-evaluation.json")
        metadata = _read_json(ROOT / ".kiro/ax-evaluation.prompt-metadata.json")
        wrong_model = json.loads(json.dumps(config))
        wrong_model["model"] = "other"
        with self.assertRaisesRegex(ValueError, "model"):
            _validate_agent_invariants(wrong_model, metadata)
        expanded = json.loads(json.dumps(config))
        expanded["tools"] = [*EXPECTED_TOOLS, "@other/tool"]
        with self.assertRaisesRegex(ValueError, "tool surface"):
            _validate_agent_invariants(expanded, metadata)


if __name__ == "__main__":
    unittest.main()
