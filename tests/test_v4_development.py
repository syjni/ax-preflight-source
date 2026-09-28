"""Synthetic development cases; no ax-exp-v3 held-out answer is used."""

from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.v4_contract import AgentOutputV4, gate_response, strict_output
from scripts.v4_scoring import Outcome, score_output
from scripts.v4_prompt import construct_runtime_prompt
from scripts.v4_preflight import validate_manifest
from scripts.v4_evaluation import evaluate_response


def output(answer, unit=None, *, abstain=False) -> dict:
    return {
        "final_answer": answer,
        "unit": unit,
        "explanation": "개발용 자료를 확인했습니다.",
        "source_ids": [] if abstain else ["DEV_SOURCE_1"],
        "abstain": abstain,
    }


RATE_TASK = {
    "task_id": "DEV_RATE_01",
    "expected_answer": "0.140625",
    "scoring_method": {
        "type": "numeric_quantity",
        "accepted_units": {
            "ratio": {"scale_to_canonical": "1", "absolute_tolerance_canonical": "0.00005"},
            "percent": {"scale_to_canonical": "0.01", "absolute_tolerance_canonical": "0.00005"},
        },
    },
}

SET_TASK = {
    "task_id": "DEV_SET_01",
    "expected_answer": ["봉인 유지", "구매 증빙"],
    "scoring_method": {
        "type": "set_items",
        "accepted_forms": {
            "봉인 유지": ["봉인이 유지된 상태"],
            "구매 증빙": ["구매 증빙 서류"],
        },
    },
}

THRESHOLD_TASK = {
    "task_id": "DEV_THRESHOLD_01",
    "expected_answer": 5,
    "scoring_method": {
        "type": "numeric_quantity",
        "accepted_units": {
            "business_days_threshold": {
                "scale_to_canonical": "1", "absolute_tolerance_canonical": "0"
            },
        },
    },
}


class V4ContractTests(unittest.TestCase):
    def test_native_and_wrapped_are_recorded_separately(self) -> None:
        body = json.dumps(output(["봉인 유지", "구매 증빙"]), ensure_ascii=False)
        native = gate_response(body)
        wrapped = gate_response("확인했습니다.\n```json\n" + body + "\n```")
        self.assertTrue(native.native_strict)
        self.assertTrue(native.delivered_valid)
        self.assertEqual(native.decision, "NATIVE_STRICT")
        self.assertFalse(wrapped.native_strict)
        self.assertTrue(wrapped.delivered_valid)
        self.assertEqual(wrapped.decision, "NORMALIZED_WRAPPER")
        self.assertIsNotNone(strict_output(wrapped.delivered_json or ""))
        self.assertNotEqual(wrapped.raw_sha256, wrapped.delivered_sha256)

    def test_gate_rejects_ambiguous_or_malformed_objects(self) -> None:
        body = json.dumps(output(5, "business_days_threshold"), ensure_ascii=False)
        cases = [
            body + "\n" + body,
            body[:-1] + ',"abstain":false}',
            body.replace('"explanation":', '"other":'),
            "{" + body,
            body.replace('"final_answer": 5', '"final_answer": NaN'),
        ]
        for raw in cases:
            with self.subTest(raw=raw[:35]):
                result = gate_response(raw)
                self.assertFalse(result.delivered_valid)
                self.assertIsNone(result.delivered_json)
                self.assertEqual(result.decision, "REJECTED")

    def test_missing_required_field_is_rejected(self) -> None:
        value = output(5, "business_days_threshold")
        value.pop("unit")
        self.assertFalse(gate_response(json.dumps(value)).semantic_available)

    def test_evaluation_keeps_native_and_delivered_success_distinct(self) -> None:
        raw = "검수 결과입니다.\n" + json.dumps(output(14.06, "percent"), ensure_ascii=False)
        result = evaluate_response(RATE_TASK, raw)
        self.assertFalse(result.native_strict)
        self.assertTrue(result.delivered_valid)
        self.assertEqual(result.outcome, "CORRECT_SUPPORTED")
        self.assertTrue(result.primary_success)
        self.assertEqual(result.receipt()["task_id"], "DEV_RATE_01")
        rejected = evaluate_response(RATE_TASK, raw + "\n" + raw)
        self.assertEqual(rejected.outcome, "NO_VALID_OUTPUT")
        self.assertFalse(rejected.primary_success)


class V4ScoringTests(unittest.TestCase):
    def test_percent_and_ratio_use_registered_units_and_tolerances(self) -> None:
        for answer, unit in [(14.06, "percent"), (0.1406, "ratio"), (0.140625, "ratio")]:
            with self.subTest(answer=answer, unit=unit):
                self.assertEqual(score_output(RATE_TASK, AgentOutputV4.model_validate(output(answer, unit))),
                                 Outcome.CORRECT_SUPPORTED)
        for answer, unit in [(14.07, "percent"), (0.1407, "ratio"), (14.06, "ratio"),
                             (14.06, None), ("14.06", "percent")]:
            with self.subTest(answer=answer, unit=unit):
                self.assertEqual(score_output(RATE_TASK, AgentOutputV4.model_validate(output(answer, unit))),
                                 Outcome.INCORRECT_SUPPORTED)

    def test_set_items_require_complete_positive_concepts(self) -> None:
        accepted = AgentOutputV4.model_validate(output(["봉인이 유지된 상태", "구매 증빙 서류"]))
        self.assertEqual(score_output(SET_TASK, accepted), Outcome.CORRECT_SUPPORTED)
        for items in (["봉인 미유지", "구매 증빙"], ["봉인 유지"],
                      ["봉인 유지", "구매 증빙", "미등록 조건"],
                      ["봉인 유지", "봉인 유지"]):
            with self.subTest(items=items):
                result = score_output(SET_TASK, AgentOutputV4.model_validate(output(items)))
                self.assertEqual(result, Outcome.INCORRECT_SUPPORTED)

    def test_threshold_uses_unambiguous_number_and_unit(self) -> None:
        numeric = AgentOutputV4.model_validate(output(5, "business_days_threshold"))
        phrase = AgentOutputV4.model_validate(output("5영업일 초과", "business_days_threshold"))
        self.assertEqual(score_output(THRESHOLD_TASK, numeric), Outcome.CORRECT_SUPPORTED)
        self.assertEqual(score_output(THRESHOLD_TASK, phrase), Outcome.INCORRECT_SUPPORTED)

    def test_abstention_is_distinct_from_bad_format_and_wrong_answer(self) -> None:
        abstention = AgentOutputV4.model_validate(output(None, abstain=True))
        self.assertEqual(score_output({**SET_TASK, "expects_abstention": True}, abstention),
                         Outcome.CORRECT_ABSTENTION)
        self.assertEqual(score_output(SET_TASK, abstention), Outcome.UNJUSTIFIED_ABSTENTION)


class V4PromptTests(unittest.TestCase):
    def test_runtime_prompt_exposes_type_and_units_without_answers(self) -> None:
        task = {**RATE_TASK, "category": "operations", "question": "개발용 반품률은 얼마인가요?"}
        prompt = construct_runtime_prompt(task)
        self.assertIn("답 유형: numeric_quantity", prompt)
        self.assertIn("percent, ratio", prompt)
        self.assertNotIn("0.140625", prompt)
        self.assertNotIn("0.00005", prompt)

    def test_set_prompt_does_not_expose_accepted_forms(self) -> None:
        task = {**SET_TASK, "category": "knowledge", "question": "개발용 접수 요건을 답하세요."}
        prompt = construct_runtime_prompt(task)
        self.assertIn("JSON 배열", prompt)
        self.assertNotIn("봉인 유지", prompt)
        self.assertNotIn("구매 증빙", prompt)


class V4PreflightTests(unittest.TestCase):
    def test_new_manifest_passes_then_detects_overlap_and_changed_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "benchmark_tasks.json").write_text(
                json.dumps({"tasks": [{"task_id": "OLD", "question": "옛 질문"}]}), encoding="utf-8")
            dataset = root / "experiment/v4/heldout/new-corpus.txt"
            dataset.parent.mkdir(parents=True)
            dataset.write_text("새 개발용 자료", encoding="utf-8")
            required = ["scripts/v4_contract.py", "scripts/v4_scoring.py", "scripts/v4_prompt.py",
                        "scripts/v4_evaluation.py",
                        "scripts/v4_official_runner.py",
                        "scripts/freeze_v4.py",
                        "experiment/v4/AGENT_PROMPT.txt", "experiment/v4/PREREGISTRATION.md"]
            frozen_files = []
            for relative in required:
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(relative, encoding="utf-8")
                frozen_files.append({"path": relative, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
            tasks = []
            for stratum in ("ratio", "threshold", "set", "exact_or_abstain"):
                for number in range(4):
                    task = {
                        "task_id": f"NEW_{stratum}_{number}",
                        "stratum": stratum,
                        "category": "knowledge",
                        "question": f"새 질문 {stratum} {number}",
                        "required_sources": ["experiment/v4/heldout/new-corpus.txt"],
                        "expects_abstention": False,
                    }
                    if stratum in {"ratio", "threshold"}:
                        task["expected_answer"] = "0.25" if stratum == "ratio" else 5
                        task["scoring_method"] = {"type": "numeric_quantity", "accepted_units": {
                            "ratio" if stratum == "ratio" else "business_days_threshold": {
                                "scale_to_canonical": "1", "absolute_tolerance_canonical": "0"
                            }}}
                    elif stratum == "set":
                        task["expected_answer"] = ["증빙"]
                        task["scoring_method"] = {"type": "set_items", "accepted_forms": {"증빙": []}}
                    else:
                        task["expects_abstention"] = number >= 2
                        task["expected_answer"] = None if number >= 2 else "확인"
                        task["scoring_method"] = {"type": "exact_text", "accepted_forms": [] if number >= 2 else ["확인"]}
                    tasks.append(task)
            manifest = {
                "schema_version": "ax-exp-v4-preregistration-v1",
                "experiment_id": "ax-exp-v4",
                "status": "READY_FOR_FREEZE",
                "repetitions": 2,
                "model": "claude-sonnet-5",
                "kiro_cli_version": "kiro-cli-chat 2.23.0",
                "backend": "AUTOMATED_FRESH_PROCESS_V2",
                "runtime_profile": "v4-candidate",
                "dataset_files": [{"path": "experiment/v4/heldout/new-corpus.txt",
                                   "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest()}],
                "frozen_files": frozen_files,
                "tasks": tasks,
            }
            self.assertEqual(validate_manifest(manifest, root=root), [])
            manifest["tasks"][0]["question"] = "옛 질문"
            dataset.write_text("변경된 자료", encoding="utf-8")
            errors = validate_manifest(manifest, root=root)
            self.assertTrue(any("v3 question text reused" in error for error in errors))
            self.assertTrue(any("changed dataset file" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
