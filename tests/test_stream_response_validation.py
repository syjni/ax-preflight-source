"""Regression tests for Kiro's aggregate stream versus final session response."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.stream_response_validation import validate_stream_response


SESSION_ID = "dev-session-001"


class StreamResponseValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stream = self.root / "stream.jsonl"
        self.session = self.root / "session.jsonl"

    def write_case(self, messages: list[str], *, chunks: list[str] | None = None,
                   final_text: str | None = None, final_truncated: bool = False) -> None:
        aggregate = "".join(messages)
        chunks = chunks if chunks is not None else [aggregate]
        final_text = final_text if final_text is not None else aggregate
        stream_events = [
            {"type": "sessionUpdate", "data": {"sessionId": SESSION_ID,
             "update": {"sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": chunk}}}}
            for chunk in chunks
        ]
        stream_events.append({"type": "runFinished", "data": {
            "sessionId": SESSION_ID, "status": "success", "finalText": final_text,
            "finalTextTruncated": final_truncated}})
        session_events = [{"kind": "Prompt", "data": {"content": [{"kind": "text", "data": "dev"}]}}]
        session_events.extend({"kind": "AssistantMessage", "data": {
            "content": [{"kind": "text", "data": message}]}} for message in messages)
        self.stream.write_text("\n".join(json.dumps(x) for x in stream_events) + "\n", encoding="utf-8")
        self.session.write_text("\n".join(json.dumps(x) for x in session_events) + "\n", encoding="utf-8")

    def validate(self, final_response: str) -> dict:
        return validate_stream_response(self.stream, self.session, session_id=SESSION_ID,
                                        final_response=final_response)

    def test_multiple_assistant_messages_are_valid_when_both_stream_views_agree(self) -> None:
        self.write_case(["", "Looking up the memo.", '{"final_answer":"시설운영팀"}'],
                        chunks=["Looking up ", "the memo.", '{"final_answer":"시설운영팀"}'])
        receipt = self.validate('{"final_answer":"시설운영팀"}')
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["assistant_message_count"], 3)
        self.assertNotEqual(receipt["aggregate_sha256"], receipt["final_response_sha256"])

    def test_single_message_remains_valid(self) -> None:
        self.write_case(['{"final_answer":"시설운영팀"}'])
        self.assertTrue(self.validate('{"final_answer":"시설운영팀"}')["passed"])

    def test_missing_stream_chunk_is_detected(self) -> None:
        self.write_case(["Searching.", "Final."], chunks=["Final."])
        self.assertIn("STREAM_CHUNKS_SESSION_AGGREGATE_MISMATCH",
                      self.validate("Final.")["errors"])

    def test_wrong_run_finished_aggregate_is_detected(self) -> None:
        self.write_case(["Searching.", "Final."], final_text="Final.")
        self.assertIn("STREAM_SESSION_AGGREGATE_MISMATCH", self.validate("Final.")["errors"])

    def test_wrong_session_final_message_is_detected(self) -> None:
        self.write_case(["Searching.", "Final."])
        self.assertIn("SESSION_LAST_MESSAGE_MISMATCH", self.validate("Different.")["errors"])

    def test_truncated_stream_is_detected(self) -> None:
        self.write_case(["Final."], final_truncated=True)
        self.assertIn("STREAM_NOT_COMPLETE", self.validate("Final.")["errors"])


if __name__ == "__main__":
    unittest.main()
