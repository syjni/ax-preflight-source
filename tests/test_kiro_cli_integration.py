from __future__ import annotations

import shutil
import subprocess

import pytest


KIRO_CLI = shutil.which("kiro-cli") or shutil.which("kiro-cli.exe")


@pytest.mark.integration
@pytest.mark.skipif(KIRO_CLI is None, reason="Kiro CLI unavailable")
def test_kiro_cli_reports_a_version() -> None:
    """Exercise the external dependency only when it is actually installed."""
    completed = subprocess.run(
        [KIRO_CLI, "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.stdout.strip() or completed.stderr.strip()
