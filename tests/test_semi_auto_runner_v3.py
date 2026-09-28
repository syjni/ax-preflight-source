from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import semi_auto_runner_v3 as runner


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class SemiAutoRunnerV3Tests(unittest.TestCase):
    def test_run_all_preserves_preregistered_64_run_order(self) -> None:
        bindings = json.loads((runner.ROOT / "task_runtime_bindings.json").read_text(encoding="utf-8"))["bindings"]
        observed: list[tuple[str, str, int]] = []

        def fake_run(root: Path, artifact_root: Path, task_id: str, condition: str, repetition: int):
            observed.append((task_id, condition, repetition))
            return {"validity_status": "VALID"}

        with patch.object(runner, "_prepare_and_run", side_effect=fake_run):
            result = runner.run_all(runner.ROOT, Path("unused"))

        expected = [
            (entry["task_id"], condition, repetition)
            for repetition in (1, 2)
            for entry in bindings
            for condition in ("Before", "Ceiling")
        ]
        self.assertEqual(observed, expected)
        self.assertEqual(len(result), 64)

    def test_run_one_uses_one_fresh_process_and_terminates_before_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run = base / "run"
            sessions = base / "sessions"
            sessions.mkdir()
            _write(run / "metadata.json", {
                "experiment_version": "ax-exp-v3",
                "run_status": "PREPARED",
                "task_id": "DEV_ONLY",
                "condition": "Before",
                "repetition": 1,
                "kiro_agent_name": "agent-v3",
            })
            (run / "prompt.txt").write_bytes(b"harmless dev prompt")
            process = Mock(pid=4321)
            process.wait.return_value = 0
            process.poll.return_value = 0

            def capture(run_dir: Path, session_id: str, *, sessions_root: Path):
                metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["process_id"], 4321)
                self.assertTrue(metadata["process_terminated"])
                self.assertTrue(metadata["fresh_process"])
                self.assertFalse(metadata["resume_used"])
                self.assertEqual(session_id, "new-session")
                return metadata

            with (
                patch.object(runner, "_copy_exact_prompt") as clipboard,
                patch.object(runner, "_session_ids", return_value={"old-session"}),
                patch.object(runner, "_new_agent_sessions", return_value=["new-session"]),
                patch.object(runner.subprocess, "Popen", return_value=process) as popen,
                patch.object(runner, "capture_kiro_session_v3", side_effect=capture) as captured,
                patch.object(runner, "finalize_run_v3", return_value={"validity_status": "VALID"}) as finalized,
            ):
                result = runner.run_one(run, root=runner.ROOT, sessions_root=sessions, executable="kiro-cli")

            self.assertEqual(result["validity_status"], "VALID")
            clipboard.assert_called_once_with("harmless dev prompt")
            popen.assert_called_once()
            self.assertNotIn("--resume", popen.call_args.args[0])
            process.wait.assert_called_once_with()
            captured.assert_called_once()
            finalized.assert_called_once()

    def test_ambiguous_session_discovery_is_invalid_and_not_finalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run = base / "run"
            sessions = base / "sessions"
            sessions.mkdir()
            _write(run / "metadata.json", {
                "experiment_version": "ax-exp-v3",
                "run_status": "PREPARED",
                "task_id": "DEV_ONLY",
                "condition": "Before",
                "repetition": 1,
                "kiro_agent_name": "agent-v3",
            })
            (run / "prompt.txt").write_bytes(b"harmless dev prompt")
            process = Mock(pid=4321)
            process.wait.return_value = 0
            process.poll.return_value = 0
            with (
                patch.object(runner, "_copy_exact_prompt"),
                patch.object(runner, "_session_ids", return_value=set()),
                patch.object(runner, "_new_agent_sessions", return_value=[]),
                patch.object(runner.subprocess, "Popen", return_value=process),
                patch.object(runner, "finalize_run_v3") as finalized,
            ):
                result = runner.run_one(run, root=runner.ROOT, sessions_root=sessions, executable="kiro-cli")
            self.assertEqual(result["validity_status"], "INVALID")
            self.assertEqual(result["invalid_reason"], "INVALID_SESSION_DISCOVERY")
            finalized.assert_not_called()


if __name__ == "__main__":
    unittest.main()
