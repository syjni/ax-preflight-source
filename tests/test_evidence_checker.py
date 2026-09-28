from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from ax_product.evidence import (
    EvidenceArtifactExistsError,
    EvidenceCheckStore,
    ToolResponseRecord,
    ToolResponseStore,
    check_evidence,
    check_run,
)
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.results import ResultStore


def delivered(*, run_id: str = "run-1", answer=7, unit=None,
              source_ids=None, status: str = "ANSWERED",
              explanation: str = "Approved structured explanation") -> DeliveryEnvelope:
    source_ids = ["TABLE_1"] if source_ids is None else source_ids
    payload = SubmitAnswerInput(
        status=status, answer=answer if status == "ANSWERED" else None,
        unit=unit if status == "ANSWERED" else None,
        explanation=explanation, source_ids=source_ids,
        abstention_reason=None if status == "ANSWERED" else "NOT_FOUND",
    )
    return DeliveryEnvelope(
        delivery_status="DELIVERED", run_id=run_id, dataset="mini", model="m",
        payload=payload, source_link_status="NOT_CHECKED",
    )


def record(output: dict, *, run_id: str = "run-1", sequence: int = 1,
           tool: str = "query_table") -> ToolResponseRecord:
    import json

    encoded = json.dumps(output, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return ToolResponseRecord(
        run_id=run_id, sequence=sequence, tool_name=tool, output=output,
        output_sha256=hashlib.sha256(encoded).hexdigest(),
    )


class EvidenceCheckerTests(unittest.TestCase):
    def test_direct_match_uses_only_cited_same_run_response(self) -> None:
        result = check_evidence(delivered(answer="구매관리팀", source_ids=["FILE_1"]), [
            record({"document_id": "FILE_2", "content": "구매관리팀"}, tool="read_document"),
            record({"document_id": "FILE_1", "content": "승인팀은 구매관리팀이다."},
                   sequence=2, tool="read_document"),
        ])
        self.assertEqual(result.verdict, "DIRECT_MATCH")
        self.assertEqual(result.matched_source_ids, ["FILE_1"])
        self.assertTrue(all(ref.sequence == 2 for ref in result.evidence))

    def test_derivation_is_limited_to_sum_difference_and_count(self) -> None:
        output = {"table_id": "TABLE_1", "rows": [{"amount": "2"}, {"amount": "5"}],
                  "rows_returned": 2, "result_rows_before_limit": 2,
                  "source_rows_matched": 2, "truncated": False, "source_ids": ["TABLE_1"]}
        self.assertEqual(check_evidence(delivered(answer=7), [record(output)]).verdict, "DERIVABLE")
        difference = check_evidence(delivered(answer=3), [record(output)])
        self.assertEqual((difference.verdict, difference.derivation.operation),
                         ("DERIVABLE", "DIFFERENCE"))
        counted = check_evidence(delivered(answer=2), [record({
            "table_id": "TABLE_1", "rows": [{"name": "a"}, {"name": "b"}],
            "rows_returned": 2, "result_rows_before_limit": 2,
            "source_rows_matched": 2, "truncated": False, "source_ids": ["TABLE_1"],
        })])
        self.assertEqual((counted.verdict, counted.derivation.operation),
                         ("DERIVABLE", "COUNT"))

    def test_ambiguous_derivations_are_not_promoted(self) -> None:
        output = {"table_id": "TABLE_1", "rows": [
            {"net": 2, "gross": 2}, {"net": 5, "gross": 5}],
            "rows_returned": 2, "result_rows_before_limit": 2,
            "source_rows_matched": 2, "truncated": False, "source_ids": ["TABLE_1"]}
        result = check_evidence(delivered(answer=7), [record(output)])
        self.assertEqual(result.verdict, "PARTIAL_SUPPORT")
        self.assertIsNone(result.derivation)

    def test_numeric_unit_requires_compatible_context(self) -> None:
        result = check_evidence(delivered(
            answer=7, unit="days", source_ids=["FILE_1"]
        ), [record({"document_id": "FILE_1", "content": "반품 기한은 7 days이다."},
                   tool="read_document")])
        self.assertEqual(result.verdict, "DIRECT_MATCH")

    def test_whole_string_quantity_accepts_matching_explicit_unit(self) -> None:
        for answer, unit in (("30일", "일"), ("30 days", "일"), ("30일", "days")):
            with self.subTest(answer=answer, unit=unit):
                result = check_evidence(delivered(
                    answer=answer, unit=unit, source_ids=["FILE_1"]
                ), [record({
                    "document_id": "FILE_1",
                    "content": "현재 반품 가능 기간은 30일 이내입니다.",
                }, tool="read_document")])
                self.assertEqual(result.verdict, "DIRECT_MATCH")

    def test_whole_string_quantity_rejects_mismatched_explicit_unit(self) -> None:
        result = check_evidence(delivered(
            answer="30일", unit="원", source_ids=["FILE_1"]
        ), [record({
            "document_id": "FILE_1",
            "content": "현재 반품 가능 기간은 30일 이내입니다.",
        }, tool="read_document")])
        self.assertEqual(result.verdict, "UNCONFIRMED")

    def test_explicit_unit_does_not_promote_non_quantity_strings(self) -> None:
        answers = ("기한은 30일", "30일 이내", "약 30일", "30일입니다")
        for answer in answers:
            with self.subTest(answer=answer):
                result = check_evidence(delivered(
                    answer=answer, unit="일", source_ids=["FILE_1"]
                ), [record({
                    "document_id": "FILE_1",
                    "content": f"승인된 답변은 {answer}.",
                }, tool="read_document")])
                self.assertEqual(result.verdict, "UNCONFIRMED")

    def test_whole_string_quantity_requires_number_and_unit_in_evidence(self) -> None:
        for content, expected in (
            ("접수 번호는 30입니다.", "PARTIAL_SUPPORT"),
            ("반품 기한은 130일입니다.", "UNCONFIRMED"),
        ):
            with self.subTest(content=content):
                result = check_evidence(delivered(
                    answer="30일", unit="일", source_ids=["FILE_1"]
                ), [record({"document_id": "FILE_1", "content": content},
                           tool="read_document")])
                self.assertEqual(result.verdict, expected)

    def test_numeric_answer_with_unit_behavior_is_preserved(self) -> None:
        result = check_evidence(delivered(
            answer=30, unit="일", source_ids=["FILE_1"]
        ), [record({
            "document_id": "FILE_1",
            "content": "현재 반품 가능 기간은 30일 이내입니다.",
        }, tool="read_document")])
        self.assertEqual(result.verdict, "DIRECT_MATCH")

    def test_counterexample_identifier_is_not_answer_content(self) -> None:
        result = check_evidence(delivered(answer="TABLE_1"), [record({
            "table_id": "TABLE_1", "rows": [{"table_id": "TABLE_1"}], "rows_returned": 1,
            "result_rows_before_limit": 1, "source_rows_matched": 1,
            "truncated": False, "source_ids": ["TABLE_1"],
        })])
        self.assertEqual(result.verdict, "UNCONFIRMED")

    def test_counterexample_lookup_metadata_is_not_numeric_content(self) -> None:
        output = {
            "table_id": "TABLE_1", "value": "C013", "matched_rows": 1,
            "ambiguous": False, "source_ids": ["TABLE_1"],
        }
        for answer in (1, "1"):
            with self.subTest(answer=answer):
                result = check_evidence(
                    delivered(answer=answer), [record(output, tool="lookup_value")]
                )
                self.assertEqual(result.verdict, "UNCONFIRMED")

    def test_counterexample_incompatible_unit_is_not_direct(self) -> None:
        result = check_evidence(delivered(
            answer="7 days", source_ids=["FILE_1"]
        ), [record({"document_id": "FILE_1", "content": "작업 제한은 7 hours이다."},
                   tool="read_document")])
        self.assertEqual(result.verdict, "PARTIAL_SUPPORT")

    def test_counterexample_truncated_rows_cannot_prove_count(self) -> None:
        result = check_evidence(delivered(answer=2), [record({
            "table_id": "TABLE_1", "rows": [{"name": "a"}, {"name": "b"}],
            "rows_returned": 2, "result_rows_before_limit": 10,
            "source_rows_matched": 10, "truncated": True, "source_ids": ["TABLE_1"],
        })])
        self.assertEqual(result.verdict, "UNCONFIRMED")

    def test_counterexample_positive_abstention_sentence_cannot_match(self) -> None:
        result = check_evidence(delivered(
            status="ABSTAINED", answer=None, source_ids=["FILE_1"],
            explanation="관련 정보가 없다. 고객 이름은 홍길동입니다.",
        ), [record({"document_id": "FILE_1", "content": "고객 이름은 홍길동입니다."},
                   tool="read_document")])
        self.assertEqual(result.verdict, "UNCONFIRMED")

    def test_rate_without_answer_value_is_unconfirmed_not_derived(self) -> None:
        output = {"table_id": "TABLE_1", "rows": [
            {"approved": "7", "reviewed": "83"},
            {"approved": "5", "reviewed": "76"},
            {"approved": "9", "reviewed": "91"},
        ]}
        result = check_evidence(delivered(answer=8.4, unit="percent"), [record(output)])
        self.assertEqual(result.verdict, "UNCONFIRMED")
        self.assertIsNone(result.derivation)

    def test_counterexample_unrelated_numeric_data_is_unconfirmed(self) -> None:
        result = check_evidence(delivered(answer=999), [record({
            "table_id": "TABLE_1", "rows": [{"amount": 7}, {"amount": 8}],
            "rows_returned": 2, "result_rows_before_limit": 2,
            "source_rows_matched": 2, "truncated": False,
            "source_ids": ["TABLE_1"],
        })])
        self.assertEqual(result.verdict, "UNCONFIRMED")

    def test_counterexample_list_with_unit_is_unconfirmed(self) -> None:
        result = check_evidence(delivered(
            answer=["7"], unit="days"
        ), [record({
            "table_id": "TABLE_1", "value": "7", "unit": "days",
            "matched_rows": 1, "source_ids": ["TABLE_1"],
        }, tool="lookup_value")])
        self.assertEqual(result.verdict, "UNCONFIRMED")

    def test_counterexample_boolean_with_unit_is_unconfirmed(self) -> None:
        result = check_evidence(delivered(
            answer=True, unit="days"
        ), [record({
            "table_id": "TABLE_1", "value": True, "unit": "days",
            "matched_rows": 1, "source_ids": ["TABLE_1"],
        }, tool="lookup_value")])
        self.assertEqual(result.verdict, "UNCONFIRMED")

    def test_missing_record_or_citation_is_unconfirmed_not_incorrect(self) -> None:
        no_record = check_evidence(delivered(), [])
        self.assertEqual(no_record.verdict, "UNCONFIRMED")
        self.assertTrue(no_record.unconfirmed_is_not_incorrect)
        no_citation = check_evidence(delivered(
            status="ABSTAINED", answer=None, source_ids=[],
            explanation="관련 정보가 없다.",
        ), [record({"table_id": "TABLE_1", "content": "관련 정보가 없다."})])
        self.assertEqual(no_citation.verdict, "UNCONFIRMED")
        self.assertIn("uncited responses are not inspected", no_citation.limitations[-1])

    def test_explicit_cited_negative_statement_directly_supports_abstention(self) -> None:
        explanation = "이 문서는 승인팀을 정하지 않았다. 관련 승인팀 정보가 없다."
        result = check_evidence(delivered(
            status="ABSTAINED", answer=None, source_ids=["FILE_1"], explanation=explanation,
        ), [record({"document_id": "FILE_1", "content": explanation}, tool="read_document")])
        self.assertEqual(result.verdict, "DIRECT_MATCH")

    def test_cross_run_record_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            check_evidence(delivered(run_id="run-a"), [record(
                {"table_id": "TABLE_1", "rows": [{"answer": 7}]}, run_id="run-b"
            )])

    def test_separate_check_artifact_is_write_once_and_delivery_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_store = ResultStore(root)
            result_store.reserve(run_id="stored", task_id=None, model="m", dataset="mini")
            envelope = delivered(run_id="stored")
            result_store.write(envelope)
            delivery_before = result_store.path("stored").read_bytes()
            responses = ToolResponseStore(root)
            responses.record(run_id="stored", tool_name="query_table", output={
                "table_id": "TABLE_1", "rows": [{"value": 7}], "source_ids": ["TABLE_1"]})
            checked = check_run(root, "stored")
            path = EvidenceCheckStore(root).write(checked)
            self.assertNotEqual(path, result_store.path("stored"))
            self.assertEqual(result_store.path("stored").read_bytes(), delivery_before)
            self.assertEqual(checked.delivery_sha256, hashlib.sha256(delivery_before).hexdigest())
            with self.assertRaises(EvidenceArtifactExistsError):
                EvidenceCheckStore(root).write(checked)
            self.assertEqual(result_store.path("stored").read_bytes(), delivery_before)


if __name__ == "__main__":
    unittest.main()
