from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.interactive_run_v3 import ROOT, capture_kiro_session_v3, finalize_run_v3, prepare_run_v3
from scripts.session_prompt_validation import validate_submitted_prompt


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _session(sessions: Path, session_id: str, prompts: list[str], *, agent: str = "agent") -> None:
    turns = []
    records = []
    for index, prompt in enumerate(prompts):
        prompt_id = f"prompt-{index}"
        assistant_id = f"assistant-{index}"
        records.extend([
            {"version": "v1", "kind": "Prompt", "data": {"message_id": prompt_id, "content": [{"kind": "text", "data": prompt}]}},
            {"version": "v1", "kind": "AssistantMessage", "data": {"message_id": assistant_id, "content": [{"kind": "text", "data": "ok"}]}},
        ])
        turns.append({
            "message_ids": [prompt_id, assistant_id],
            "result": {"Ok": {"content": [{"kind": "text", "data": '{"final_answer":null,"unit":null,"explanation":"x","source_ids":[],"abstain":true}'}]}},
        })
    _write(sessions / f"{session_id}.json", {
        "session_id": session_id,
        "session_state": {"agent_name": agent, "conversation_metadata": {"user_turn_metadatas": turns}},
    })
    (sessions / f"{session_id}.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8",
    )


class PromptValidationV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.kiro_version = patch(
            "scripts.interactive_run._kiro_cli_version",
            return_value="kiro-cli-chat test-double",
        )
        self.kiro_version.start()
        self.addCleanup(self.kiro_version.stop)

    def _fixture(self, submitted: list[str], *, agent: str = "agent"):
        temporary = tempfile.TemporaryDirectory()
        base = Path(temporary.name)
        run = base / "run"
        sessions = base / "sessions"
        run.mkdir()
        sessions.mkdir()
        prompt = "업무 범주: dev\n질문: exact"
        (run / "prompt.txt").write_bytes(prompt.encode("utf-8"))
        _write(run / "metadata.json", {"prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()})
        _session(sessions, "session", submitted, agent=agent)
        return temporary, run, sessions, prompt

    def test_exact_prompt_is_accepted(self) -> None:
        temporary, run, sessions, prompt = self._fixture(["업무 범주: dev\n질문: exact"])
        with temporary:
            result = validate_submitted_prompt(run, "session", "agent", sessions_root=sessions)
            self.assertTrue(result["passed"], result)
            self.assertTrue(result["submitted_prompt_matches_prepared"])
            self.assertEqual(result["user_turn_count"], 1)

    def test_modified_prompt_is_invalid(self) -> None:
        temporary, run, sessions, _ = self._fixture(["업무 범주: dev\n질문: modified"])
        with temporary:
            result = validate_submitted_prompt(run, "session", "agent", sessions_root=sessions)
            self.assertIn("INVALID_OPERATOR_WRONG_PROMPT", result["validation_errors"])

    def test_command_snippet_is_invalid(self) -> None:
        temporary, run, sessions, _ = self._fixture(['Get-Content "$RUN\\prompt.txt" -Raw | Set-Clipboard'])
        with temporary:
            result = validate_submitted_prompt(run, "session", "agent", sessions_root=sessions)
            self.assertIn("INVALID_OPERATOR_WRONG_PROMPT", result["validation_errors"])

    def test_wrong_task_prompt_is_invalid(self) -> None:
        temporary, run, sessions, _ = self._fixture(["업무 범주: other\n질문: 다른 task"])
        with temporary:
            result = validate_submitted_prompt(run, "session", "agent", sessions_root=sessions)
            self.assertFalse(result["submitted_prompt_matches_prepared"])

    def test_prefix_or_suffix_is_invalid(self) -> None:
        for submitted in ("prefix\n업무 범주: dev\n질문: exact", "업무 범주: dev\n질문: exact\nsuffix"):
            with self.subTest(submitted=submitted):
                temporary, run, sessions, _ = self._fixture([submitted])
                with temporary:
                    result = validate_submitted_prompt(run, "session", "agent", sessions_root=sessions)
                    self.assertIn("INVALID_OPERATOR_WRONG_PROMPT", result["validation_errors"])

    def test_empty_prompt_is_invalid(self) -> None:
        temporary, run, sessions, _ = self._fixture([""])
        with temporary:
            result = validate_submitted_prompt(run, "session", "agent", sessions_root=sessions)
            self.assertIn("INVALID_EMPTY_PROMPT", result["validation_errors"])

    def test_multiple_turns_are_invalid(self) -> None:
        temporary, run, sessions, prompt = self._fixture([prompt := "업무 범주: dev\n질문: exact", prompt])
        with temporary:
            result = validate_submitted_prompt(run, "session", "agent", sessions_root=sessions)
            self.assertIn("INVALID_MULTIPLE_USER_TURNS", result["validation_errors"])
            self.assertEqual(result["user_turn_count"], 2)

    def test_wrong_agent_is_invalid(self) -> None:
        temporary, run, sessions, _ = self._fixture(["업무 범주: dev\n질문: exact"], agent="wrong")
        with temporary:
            result = validate_submitted_prompt(run, "session", "agent", sessions_root=sessions)
            self.assertIn("INVALID_WRONG_AGENT", result["validation_errors"])

    def test_v3_wrong_runtime_cannot_be_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run = base / "run"
            sessions = base / "sessions"
            sessions.mkdir()
            prompt = "업무 범주: knowledge\n질문: test"
            prepared = prepare_run_v3(
                run,
                task_id="K03_DELAY_COMPENSATION_THRESHOLD",
                condition="Before",
                repetition=1,
                prompt=prompt,
                root=ROOT,
            )
            config_path = ROOT / prepared["kiro_agent_config"]
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["mcpServers"]["ax-tools"]["env"]["AX_RUNTIME_DATASET"] = "mini"
            _write(config_path, config)
            metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
            metadata.update({"process_id": 123, "process_exit_code": 0, "process_terminated": True})
            _write(run / "metadata.json", metadata)
            _session(sessions, "session", [prompt], agent=prepared["kiro_agent_name"])
            capture_kiro_session_v3(run, "session", sessions_root=sessions)
            recorded = finalize_run_v3(run, root=ROOT)
            self.assertEqual(recorded["validity_status"], "INVALID")
            self.assertTrue(any("runtime" in error for error in recorded["validation_errors"]))
            config_path.unlink()

    def test_v3_exact_prompt_and_runtime_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run = base / "run"
            sessions = base / "sessions"
            sessions.mkdir()
            prompt = "업무 범주: knowledge\n질문: exact v3 integration"
            prepared = prepare_run_v3(
                run,
                task_id="K03_DELAY_COMPENSATION_THRESHOLD",
                condition="Before",
                repetition=1,
                prompt=prompt,
                root=ROOT,
            )
            config_path = ROOT / prepared["kiro_agent_config"]
            try:
                _write(run / "runtime-identity-receipt.json", {
                    "passed": True,
                    "identity": prepared["runtime_dataset_identity"],
                })
                metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
                metadata.update({
                    "process_id": 123,
                    "process_exit_code": 0,
                    "process_terminated": True,
                    "fresh_process": True,
                    "resume_used": False,
                })
                _write(run / "metadata.json", metadata)
                _session(sessions, "session", [prompt], agent=prepared["kiro_agent_name"])
                capture_kiro_session_v3(run, "session", sessions_root=sessions)
                recorded = finalize_run_v3(run, root=ROOT)
                self.assertEqual(recorded["validity_status"], "VALID", recorded)
                self.assertTrue(recorded["submitted_prompt_matches_prepared"])
                self.assertEqual(recorded["prepared_prompt_sha256"], recorded["submitted_prompt_sha256"])
                self.assertEqual(recorded["user_turn_count"], 1)
            finally:
                config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
