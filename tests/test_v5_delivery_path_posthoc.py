"""Development-only checks of the gate-to-evaluator consumption path."""

from __future__ import annotations

import json
import unittest

from scripts.v4_contract import strict_output
from scripts.v4_evaluation import evaluate_response


TASK = {
    "task_id": "DEV_DELIVERY_PATH_01",
    "expected_answer": "시설운영팀",
    "expects_abstention": False,
    "scoring_method": {"type": "exact_text", "accepted_forms": ["시설운영팀"]},
}


def answer(value: str = "시설운영팀") -> str:
    return json.dumps({
        "final_answer": value,
        "unit": None,
        "explanation": "개발용 문서에서 책임팀을 확인했습니다.",
        "source_ids": ["DEV_SOURCE_1"],
        "abstain": False,
    }, ensure_ascii=False)


class DeliveryPathTests(unittest.TestCase):
    def test_native_and_wrapped_answers_reach_the_scorer_through_delivery(self) -> None:
        body = answer()
        cases = (
            (body, True, "NATIVE_STRICT"),
            ("확인했습니다.\n```json\n" + body + "\n```", False, "NORMALIZED_WRAPPER"),
            ("개발용 확인 문장입니다.\n" + body, False, "NORMALIZED_WRAPPER"),
        )
        for raw, native, decision in cases:
            with self.subTest(decision=decision, raw_length=len(raw)):
                result = evaluate_response(TASK, raw)
                self.assertEqual(result.native_strict, native)
                self.assertEqual(result.gate_decision, decision)
                self.assertTrue(result.delivered_valid)
                self.assertEqual(result.outcome, "CORRECT_SUPPORTED")
                self.assertTrue(result.correct)
                self.assertTrue(result.primary_success)
                self.assertIsNotNone(strict_output(result.delivered_json or ""))
                self.assertEqual(json.loads(result.delivered_json or "{}"), json.loads(body))
                if not native:
                    self.assertIsNone(strict_output(raw))
                    self.assertNotIn("```", result.delivered_json or "")

    def test_malformed_and_structurally_ambiguous_answers_fail_closed(self) -> None:
        body = answer()
        cases = (
            "not JSON",
            body[:-1],
            body.replace('"unit": null', '"unit": "invalid", "unit": null'),
            body.replace('"source_ids":', '"unexpected": 1, "source_ids":'),
            body + "\n" + body,
            body + "\n{}",
        )
        for raw in cases:
            with self.subTest(raw=raw[:60]):
                result = evaluate_response(TASK, raw)
                self.assertEqual(result.gate_decision, "REJECTED")
                self.assertIsNone(result.delivered_json)
                self.assertFalse(result.delivered_valid)
                self.assertEqual(result.outcome, "NO_VALID_OUTPUT")
                self.assertFalse(result.correct)
                self.assertFalse(result.primary_success)

    def test_valid_json_with_wrong_answer_is_not_success(self) -> None:
        result = evaluate_response(TASK, answer("다른팀"))
        self.assertTrue(result.delivered_valid)
        self.assertEqual(result.outcome, "INCORRECT_SUPPORTED")
        self.assertFalse(result.correct)
        self.assertFalse(result.primary_success)


if __name__ == "__main__":
    unittest.main()
