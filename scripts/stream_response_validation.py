"""Validate Kiro v2's aggregate stream and the final assistant message separately.

The CLI's runFinished.finalText concatenates all assistant text messages in a
turn. A session turn's result.Ok.content contains only its final message.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(content: list[dict[str, Any]]) -> str:
    return "".join(item.get("data", "") for item in content if item.get("kind") == "text")


def validate_stream_response(
    stream_path: Path, session_events_path: Path, *,
    session_id: str, final_response: str,
) -> dict[str, Any]:
    """Return a read-only receipt; never infer the final answer from aggregate text."""
    errors: list[str] = []
    stream_events = []
    for number, line in enumerate(stream_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            stream_events.append(json.loads(line))
        except json.JSONDecodeError:
            errors.append(f"STREAM_INVALID_JSON_LINE_{number}")
    finished = [event.get("data", {}) for event in stream_events
                if isinstance(event, dict) and event.get("type") == "runFinished"]
    if len(finished) != 1:
        errors.append("STREAM_FINISHED_COUNT")
        final_text = None
    else:
        event = finished[0]
        final_text = event.get("finalText")
        if event.get("sessionId") != session_id:
            errors.append("STREAM_SESSION_ID")
        if event.get("status") != "success" or event.get("finalTextTruncated") is not False:
            errors.append("STREAM_NOT_COMPLETE")
        if not isinstance(final_text, str):
            errors.append("STREAM_FINAL_TEXT_MISSING")

    chunks = []
    for event in stream_events:
        if not isinstance(event, dict) or event.get("type") != "sessionUpdate":
            continue
        data = event.get("data", {})
        if data.get("sessionId") != session_id:
            errors.append("STREAM_UPDATE_SESSION_ID")
        update = data.get("update", {})
        if update.get("sessionUpdate") == "agent_message_chunk":
            content = update.get("content", {})
            if content.get("type") != "text" or not isinstance(content.get("text"), str):
                errors.append("STREAM_CHUNK_CONTENT")
            else:
                chunks.append(content["text"])
    streamed_text = "".join(chunks)
    if not chunks:
        errors.append("STREAM_NO_TEXT_CHUNKS")

    session_events = []
    for number, line in enumerate(session_events_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            session_events.append(json.loads(line))
        except json.JSONDecodeError:
            errors.append(f"SESSION_INVALID_JSON_LINE_{number}")
    messages = [_text(event.get("data", {}).get("content", [])) for event in session_events
                if isinstance(event, dict) and event.get("kind") == "AssistantMessage"]
    if not messages:
        errors.append("SESSION_NO_ASSISTANT_MESSAGE")
    elif messages[-1] != final_response:
        errors.append("SESSION_LAST_MESSAGE_MISMATCH")
    aggregate = "".join(messages)
    if final_text != aggregate:
        errors.append("STREAM_SESSION_AGGREGATE_MISMATCH")
    if streamed_text != aggregate:
        errors.append("STREAM_CHUNKS_SESSION_AGGREGATE_MISMATCH")
    return {
        "schema_version": "ax-stream-response-validation-v1",
        "passed": not errors,
        "errors": errors,
        "assistant_message_count": len(messages),
        "nonempty_assistant_message_count": sum(bool(message) for message in messages),
        "aggregate_sha256": _sha(aggregate),
        "final_response_sha256": _sha(final_response),
        "streamed_text_sha256": _sha(streamed_text),
        "run_finished_text_sha256": _sha(final_text) if isinstance(final_text, str) else None,
        "aggregate_length": len(aggregate),
        "final_response_length": len(final_response),
        "streamed_text_length": len(streamed_text),
    }
