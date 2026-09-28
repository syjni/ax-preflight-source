"""Validate the exact user prompt stored by a Kiro CLI v1 session."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Kiro session JSONL line {number}: {path}") from exc
    return records


def _text_content(content: list[dict[str, Any]]) -> tuple[str, bool]:
    non_text = any(item.get("kind") != "text" for item in content)
    return "".join(item.get("data", "") for item in content if item.get("kind") == "text"), non_text


def validate_submitted_prompt(
    run_dir: Path,
    session_id: str,
    expected_agent_name: str,
    *,
    sessions_root: Path | None = None,
) -> dict[str, Any]:
    """Return prompt/session evidence without mutating the run or Kiro store."""
    sessions_root = sessions_root or (Path.home() / ".kiro" / "sessions" / "cli")
    session_path = sessions_root / f"{session_id}.json"
    events_path = sessions_root / f"{session_id}.jsonl"
    session = _read_json(session_path)
    events = _jsonl(events_path)
    if session.get("session_id") != session_id:
        raise ValueError("Kiro session ID does not match its filename")

    state = session.get("session_state", {})
    turns = state.get("conversation_metadata", {}).get("user_turn_metadatas", [])
    prompts = [record["data"] for record in events if record.get("kind") == "Prompt"]
    submitted_texts = []
    prompt_message_ids = []
    has_non_text = False
    for prompt in prompts:
        text, non_text = _text_content(prompt.get("content", []))
        submitted_texts.append(text)
        prompt_message_ids.append(prompt.get("message_id"))
        has_non_text = has_non_text or non_text

    prepared_bytes = (run_dir / "prompt.txt").read_bytes()
    prepared_hash = _sha256_bytes(prepared_bytes)
    submitted_bytes = submitted_texts[0].encode("utf-8") if len(submitted_texts) == 1 else None
    submitted_hash = _sha256_bytes(submitted_bytes) if submitted_bytes is not None else None
    exact_match = submitted_bytes == prepared_bytes if submitted_bytes is not None else False
    message_links_valid = len(turns) == len(prompts) and all(
        prompt_message_ids[index] in turn.get("message_ids", [])
        for index, turn in enumerate(turns)
    )

    errors = []
    if state.get("agent_name") != expected_agent_name:
        errors.append("INVALID_WRONG_AGENT")
    if len(turns) != 1 or len(prompts) != 1:
        errors.append("INVALID_MULTIPLE_USER_TURNS" if max(len(turns), len(prompts)) > 1 else "INVALID_MISSING_USER_TURN")
    if len(submitted_texts) == 1 and not submitted_texts[0]:
        errors.append("INVALID_EMPTY_PROMPT")
    if has_non_text:
        errors.append("INVALID_NON_TEXT_PROMPT_CONTENT")
    if not message_links_valid:
        errors.append("INVALID_SESSION_EVENT_LINKAGE")
    if len(submitted_texts) == 1 and submitted_texts[0] and not exact_match:
        errors.append("INVALID_OPERATOR_WRONG_PROMPT")
    prepared_metadata = _read_json(run_dir / "metadata.json")
    recorded_prepared_hash = prepared_metadata.get("prepared_prompt_sha256", prepared_metadata.get("prompt_sha256"))
    if recorded_prepared_hash != prepared_hash:
        errors.append("INVALID_PREPARED_PROMPT_HASH_MISMATCH")

    assistant_responses = []
    completed_turns = 0
    for turn in turns:
        outcome = turn.get("result", {})
        if "Ok" in outcome:
            completed_turns += 1
            text, _ = _text_content(outcome["Ok"].get("content", []))
            assistant_responses.append(text)
    if completed_turns != len(turns):
        errors.append("INVALID_INCOMPLETE_TURN")

    return {
        "schema_version": "ax-submitted-prompt-validation-v1",
        "session_id": session_id,
        "session_file": str(session_path),
        "session_events_file": str(events_path),
        "session_agent_name": state.get("agent_name"),
        "expected_agent_name": expected_agent_name,
        "user_turn_count": len(turns),
        "prompt_event_count": len(prompts),
        "prepared_prompt_sha256": prepared_hash,
        "submitted_prompt_sha256": submitted_hash,
        "submitted_prompt_sha256s": [_sha256_bytes(text.encode("utf-8")) for text in submitted_texts],
        "submitted_prompt_matches_prepared": exact_match,
        "submitted_prompt_empty": len(submitted_texts) == 1 and not submitted_texts[0],
        "message_links_valid": message_links_valid,
        "turns_completed": completed_turns,
        "passed": not errors,
        "validation_errors": errors,
        "assistant_responses": assistant_responses,
    }
