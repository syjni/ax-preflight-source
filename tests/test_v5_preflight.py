"""Prospective checks that protect the new v5 held-out boundary."""

from __future__ import annotations

import copy
import json
import unittest

from scripts.v4_prompt import project_runtime_task
from scripts.v5_preflight import ROOT, validate_manifest


class V5PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = json.loads((ROOT / "experiment/v5/CANDIDATE_MANIFEST.json").read_text(encoding="utf-8"))

    def test_new_candidate_passes_draft_preflight(self) -> None:
        self.assertEqual(validate_manifest(copy.deepcopy(self.candidate), require_ready=False), [])

    def test_v4_question_reuse_is_rejected(self) -> None:
        modified = copy.deepcopy(self.candidate)
        v4 = json.loads((ROOT / "experiment/frozen/ax-exp-v4-manifest.json").read_text(encoding="utf-8"))
        modified["tasks"][0]["question"] = v4["tasks"][0]["question"]
        self.assertTrue(any("v3 or v4 question text reused" in error
                            for error in validate_manifest(modified, require_ready=False)))

    def test_dataset_hash_change_is_rejected(self) -> None:
        modified = copy.deepcopy(self.candidate)
        modified["dataset_files"][0]["sha256"] = "0" * 64
        self.assertTrue(any("missing or changed dataset file" in error
                            for error in validate_manifest(modified, require_ready=False)))

    def test_model_projection_hides_answers_and_sources(self) -> None:
        for task in self.candidate["tasks"]:
            projection = project_runtime_task(task)
            self.assertEqual(set(projection) - {"allowed_units"},
                             {"category", "question", "answer_kind"})
            self.assertNotIn("expected_answer", projection)
            self.assertNotIn("required_sources", projection)
            self.assertNotIn("accepted_forms", projection)


if __name__ == "__main__":
    unittest.main()
