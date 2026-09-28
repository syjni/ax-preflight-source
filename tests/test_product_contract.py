from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from ax_product.delivery import SubmitAnswerSession
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput, UnscoredObservation
from ax_product.schema_export import export_schemas


ANSWERED = {
    "status": "ANSWERED", "answer": 0, "unit": "건",
    "explanation": "집계 결과입니다.", "source_ids": ["TABLE_1"],
}


class SubmitAnswerInputTests(unittest.TestCase):
    def test_answered_accepts_zero_false_and_set_answers(self) -> None:
        for answer in (0, False, ["항목 A", "항목 B"]):
            with self.subTest(answer=answer):
                payload = SubmitAnswerInput.model_validate({**ANSWERED, "answer": answer})
                self.assertEqual(payload.answer, answer)
                self.assertIs(type(payload.answer), type(answer))

    def test_answered_requires_answer_source_and_no_abstention_reason(self) -> None:
        for change in (
            {"answer": None}, {"answer": "  "}, {"answer": []},
            {"source_ids": []}, {"abstention_reason": "NOT_FOUND"},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                SubmitAnswerInput.model_validate({**ANSWERED, **change})

    def test_abstention_reasons_and_source_count_policy(self) -> None:
        for reason, ids in (
            ("NOT_FOUND", []),
            ("NOT_FOUND", ["DOC_1"]),
            ("INSUFFICIENT_EVIDENCE", ["DOC_1"]),
            ("CONFLICTING_EVIDENCE", ["DOC_1"]),
            ("CONFLICTING_EVIDENCE", ["DOC_1", "DOC_2"]),
        ):
            with self.subTest(reason=reason, ids=ids):
                payload = SubmitAnswerInput(
                    status="ABSTAINED", explanation="현재 자료로 확정할 수 없습니다.",
                    abstention_reason=reason, source_ids=ids,
                )
                self.assertIsNone(payload.answer)
        for reason in ("INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"):
            with self.subTest(reason=reason), self.assertRaises(ValidationError):
                SubmitAnswerInput(
                    status="ABSTAINED", explanation="근거 부족",
                    abstention_reason=reason, source_ids=[],
                )

    def test_abstained_field_relationships(self) -> None:
        base = {
            "status": "ABSTAINED", "explanation": "찾지 못했습니다.",
            "abstention_reason": "NOT_FOUND", "source_ids": [],
        }
        for change in ({"answer": 0}, {"unit": "건"}, {"abstention_reason": None}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                SubmitAnswerInput.model_validate({**base, **change})

    def test_rejects_unknown_reason_blank_text_bad_ids_and_extra_fields(self) -> None:
        for change in (
            {"explanation": " \t"}, {"source_ids": [" "]},
            {"source_ids": [" TABLE_1"]},
            {"source_ids": ["TABLE_1", "TABLE_1"]},
            {"extra_field": "x"}, {"answer": float("nan")},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                SubmitAnswerInput.model_validate({**ANSWERED, **change})
        with self.assertRaises(ValidationError):
            SubmitAnswerInput(
                status="ABSTAINED", explanation="보류", abstention_reason="UNKNOWN"
            )

    def test_source_count_does_not_claim_real_evidence_linkage(self) -> None:
        # The ID is syntactically valid but has not been compared with tool results.
        payload = SubmitAnswerInput.model_validate({**ANSWERED, "source_ids": ["NONEXISTENT"]})
        self.assertEqual(payload.source_ids, ["NONEXISTENT"])
        session = SubmitAnswerSession()
        self.assertTrue(session.submit(payload).accepted)
        self.assertEqual(
            session.envelope(run_id="run-1", task_id=None, model="test").source_link_status,
            "NOT_CHECKED",
        )


class SubmissionSessionTests(unittest.TestCase):
    def test_invalid_attempt_does_not_consume_slot(self) -> None:
        session = SubmitAnswerSession()
        self.assertEqual(session.state, "UNSUBMITTED")
        attempt = session.submit({**ANSWERED, "source_ids": []})
        self.assertEqual(attempt.error_code, "VALIDATION_ERROR")
        self.assertTrue(attempt.validation_errors)
        self.assertEqual(session.state, "UNSUBMITTED")
        self.assertEqual(session.envelope(run_id="r", task_id=None, model="m").reject_reason,
                         "INVALID_SUBMISSION")
        self.assertTrue(session.submit(ANSWERED).accepted)
        self.assertEqual(session.state, "ACCEPTED")

    def test_first_valid_submission_wins_and_is_copy_protected(self) -> None:
        session = SubmitAnswerSession()
        arguments = {**ANSWERED, "source_ids": ["FIRST"]}
        self.assertTrue(session.submit(arguments).accepted)
        arguments["source_ids"].append("LATER")
        copy = session.accepted_payload
        self.assertIsNotNone(copy)
        copy.source_ids.append("MUTATED")
        self.assertEqual(session.submit({**ANSWERED, "answer": 42}).error_code,
                         "ALREADY_SUBMITTED")
        self.assertEqual(session.submit({"invalid": True}).error_code,
                         "ALREADY_SUBMITTED")
        self.assertEqual(session.accepted_payload.source_ids, ["FIRST"])
        self.assertEqual(session.accepted_payload.answer, 0)

    def test_no_submission_and_delivered_envelopes(self) -> None:
        session = SubmitAnswerSession()
        empty = session.envelope(run_id="r", task_id="task", model="m")
        self.assertEqual((empty.delivery_status, empty.reject_reason),
                         ("REJECTED", "NO_SUBMISSION"))
        session.submit(ANSWERED)
        delivered = session.envelope(run_id="r", task_id="task", model="m")
        self.assertEqual(delivered.delivery_status, "DELIVERED")
        self.assertEqual(delivered.payload.answer, 0)
        self.assertIsNone(delivered.reject_reason)
        delivered.payload.source_ids.append("MUTATED")
        self.assertEqual(session.accepted_payload.source_ids, ["TABLE_1"])

    def test_envelope_rejects_impossible_combinations(self) -> None:
        with self.assertRaises(ValidationError):
            DeliveryEnvelope(delivery_status="DELIVERED", run_id="r", model="m",
                             source_link_status="NOT_CHECKED")
        with self.assertRaises(ValidationError):
            DeliveryEnvelope(delivery_status="REJECTED", run_id="r", model="m",
                             reject_reason="NO_SUBMISSION", payload=SubmitAnswerInput(**ANSWERED))


class ObservationAndSchemaTests(unittest.TestCase):
    def test_unscored_version_group_has_no_readiness_score_field(self) -> None:
        observation = UnscoredObservation(
            code="PROBABLE_VERSION_GROUP", severity="warning",
            message="버전 추정 그룹이 3개 있습니다.", file_ids=["FILE_1", "FILE_2"],
        )
        self.assertNotIn("score", observation.model_dump())
        self.assertNotIn("score", UnscoredObservation.model_fields)
        with self.assertRaises(ValidationError):
            UnscoredObservation(**observation.model_dump(), score=72)

    def test_schema_export_is_deterministic_and_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            paths = export_schemas(output_dir)
            self.assertEqual({path.name for path in paths}, {
                "SubmitAnswerInput.schema.json", "DeliveryEnvelope.schema.json",
                "UnscoredObservation.schema.json", "ToolResponseRecord.schema.json",
                "ToolAttemptRecord.schema.json",
                "EvidenceCheckResult.schema.json",
                "OnboardingAssessment.schema.json",
                "RetrievalTrace.schema.json",
                "DataFinding.schema.json", "FindingsResponse.schema.json",
            })
            first = {path.name: path.read_bytes() for path in paths}
            export_schemas(output_dir)
            self.assertEqual(first, {path.name: path.read_bytes() for path in paths})
            for path in paths:
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])
            delivery_schema = json.loads((output_dir / "DeliveryEnvelope.schema.json").read_text(encoding="utf-8"))
            self.assertIn("SubmitAnswerInput", delivery_schema["$defs"])


if __name__ == "__main__":
    unittest.main()
