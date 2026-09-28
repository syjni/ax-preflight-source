from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ax_agent.models import AgentOutput
from scripts.assemble_ceiling_dataset import generate_ceiling_dataset
from scripts.ceiling_scoring import OutcomeState, score_agent_output
from scripts.validate_ceiling_dataset import validate_ceiling_benchmark


class CeilingIntegrityRepairTests(unittest.TestCase):
    def test_agent_output_scoring_uses_all_abstention_states(self) -> None:
        supported = {"expected_answer": 12, "scoring_method": {"type": "numeric", "relative_tolerance": 0.0}}
        abstention = {"expects_abstention": True, "expected_answer": None, "scoring_method": {"type": "exact"}}
        correct = AgentOutput(final_answer=12, unit=None, explanation="evidence", source_ids=["source"], abstain=False)
        wrong = AgentOutput(final_answer=11, unit=None, explanation="evidence", source_ids=["source"], abstain=False)
        abstain = AgentOutput(final_answer=None, unit=None, explanation="missing", source_ids=[], abstain=True)
        self.assertEqual(score_agent_output(supported, correct), OutcomeState.CORRECT_SUPPORTED)
        self.assertEqual(score_agent_output(supported, wrong), OutcomeState.INCORRECT_SUPPORTED)
        self.assertEqual(score_agent_output(supported, abstain), OutcomeState.UNJUSTIFIED_ABSTENTION)
        self.assertEqual(score_agent_output(abstention, abstain), OutcomeState.CORRECT_ABSTENTION)
        self.assertEqual(score_agent_output(abstention, wrong), OutcomeState.HALLUCINATION)

    def test_set_scoring_rejects_negation_and_unsafe_substrings(self) -> None:
        task = {
            "expected_answer": ["미개봉", "미사용", "재판매 가능 상태", "원본 영수증"],
            "scoring_method": {"type": "set", "required_items": ["미개봉", "미사용", "재판매 가능 상태", "원본 영수증"], "reject_negated_items": True},
        }
        valid = AgentOutput(final_answer="미개봉, 미사용, 재판매 가능 상태, 원본 영수증", unit=None, explanation="policy", source_ids=["source"], abstain=False)
        negated = AgentOutput(final_answer="미개봉이 아니어도 되고, 미사용, 재판매 가능 상태, 원본 영수증", unit=None, explanation="policy", source_ids=["source"], abstain=False)
        concatenated = AgentOutput(final_answer="미개봉미사용재판매 가능 상태원본 영수증", unit=None, explanation="policy", source_ids=["source"], abstain=False)
        self.assertEqual(score_agent_output(task, valid), OutcomeState.CORRECT_SUPPORTED)
        self.assertEqual(score_agent_output(task, negated), OutcomeState.INCORRECT_SUPPORTED)
        self.assertEqual(score_agent_output(task, concatenated), OutcomeState.INCORRECT_SUPPORTED)

    def test_o03_and_control_family_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate_ceiling_dataset(root)
            benchmark = json.loads((root / "benchmark_tasks.json").read_text(encoding="utf-8"))
            o03 = next(task for task in benchmark["tasks"] if task["task_id"] == "O03_GREEN_TABLE_LAST_ORDER")
            self.assertEqual(o03["category"], "cross_file")
            self.assertEqual(len(o03["required_sources"]), 2)
            self.assertNotIn("C005", json.dumps(o03["tool_plan"], ensure_ascii=False))

            controls = json.loads((root / "control_sources.json").read_text(encoding="utf-8"))
            protected = controls["protected_sources"][0]
            sibling = root / "sample_data" / "ceiling_company" / Path(protected).with_suffix(".copy" + Path(protected).suffix)
            shutil.copyfile(root / "sample_data" / "ceiling_company" / protected, sibling)
            validation = validate_ceiling_benchmark(root)
            check = next(item for item in validation["checks"] if item["name"] == "control_source_hash_and_family_protection")
            self.assertFalse(check["passed"])
            self.assertIn("duplicate_or_conflicting_siblings", check["detail"]["errors"])


if __name__ == "__main__":
    unittest.main()
