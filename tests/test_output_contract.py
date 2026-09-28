from __future__ import annotations

import json
import hashlib
import unittest
from pathlib import Path

from scripts.output_contract import parse_agent_response


VALID = {
    "final_answer": 10,
    "unit": "곳",
    "explanation": "회사 자료에 근거한 집계입니다.",
    "source_ids": ["TABLE_example"],
    "abstain": False,
}


class OutputContractTests(unittest.TestCase):
    def raw(self) -> str:
        return json.dumps(VALID, ensure_ascii=False)

    def test_exact_object_is_strict_and_semantically_available(self) -> None:
        result = parse_agent_response(" \n" + self.raw() + "\t")
        self.assertTrue(result.output_contract_valid)
        self.assertTrue(result.semantic_json_available)
        self.assertEqual(result.raw_response, " \n" + self.raw() + "\t")
        self.assertEqual(result.parsed_result, VALID)

    def test_markdown_fence_fails_strict_but_extracts_semantics(self) -> None:
        raw = "```json\n" + self.raw() + "\n```"
        result = parse_agent_response(raw)
        self.assertFalse(result.output_contract_valid)
        self.assertTrue(result.semantic_json_available)
        self.assertEqual(result.raw_response, raw)
        self.assertEqual(result.parsed_result, VALID)

    def test_leading_and_trailing_prose_fail_strict(self) -> None:
        raw = "answer follows\n" + self.raw() + "\nend"
        result = parse_agent_response(raw)
        self.assertFalse(result.output_contract_valid)
        self.assertTrue(result.semantic_json_available)

    def test_malformed_json_is_never_repaired(self) -> None:
        raw = '{"final_answer":10,"unit":"곳","explanation":"x","source_ids":[],"abstain":false'
        result = parse_agent_response(raw)
        self.assertFalse(result.output_contract_valid)
        self.assertFalse(result.semantic_json_available)
        self.assertIsNone(result.parsed_result)

    def test_missing_or_extra_fields_do_not_match_frozen_schema(self) -> None:
        missing = dict(VALID)
        missing.pop("explanation")
        extra = {**VALID, "reasoning": "outside frozen schema"}
        for value in (missing, extra):
            with self.subTest(value=value):
                result = parse_agent_response(json.dumps(value, ensure_ascii=False))
                self.assertFalse(result.output_contract_valid)
                self.assertFalse(result.semantic_json_available)

    def test_two_valid_objects_are_ambiguous_and_not_extracted(self) -> None:
        raw = self.raw() + "\n" + self.raw()
        result = parse_agent_response(raw)
        self.assertFalse(result.output_contract_valid)
        self.assertFalse(result.semantic_json_available)
        self.assertIsNone(result.parsed_result)

    def test_duplicate_fields_are_rejected_without_repair(self) -> None:
        raw = self.raw()[:-1] + ',"abstain":false}'
        result = parse_agent_response(raw)
        self.assertFalse(result.output_contract_valid)
        self.assertFalse(result.semantic_json_available)

    def test_prompt_revision_is_versioned_hashed_and_generic(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / ".kiro" / "agents" / "ax-evaluation.json").read_text(encoding="utf-8"))
        metadata = json.loads((root / ".kiro" / "ax-evaluation.prompt-metadata.json").read_text(encoding="utf-8"))
        prompt = config["prompt"]
        self.assertEqual(metadata["prompt_version"], "2")
        self.assertEqual(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), metadata["prompt_sha256"])
        for required in (
            "exactly one raw JSON object", "Do not use Markdown code fences",
            "Do not write prose before the JSON", "Do not write prose after the JSON",
            "The first non-whitespace character must be {",
            "the last non-whitespace character must be }",
        ):
            self.assertIn(required, prompt)
        for task_specific in (
            "O01", "O05", "C01", "C04", "C07", "한빛상사", "윤성마트", "다온유통",
            "거래처_마스터.xlsx", "주문_원장_2026.xlsx", "TABLE_FILE_",
        ):
            self.assertNotIn(task_specific, prompt)


if __name__ == "__main__":
    unittest.main()
