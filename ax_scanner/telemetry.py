from __future__ import annotations

import os
import shutil
from typing import Any, Protocol

from .models import LLMTaskTelemetry, LiveLLMStatus


class LLMProvider(Protocol):
    """Minimal boundary for a future three-task live smoke runner."""

    provider_name: str
    model_name: str

    def run_task(self, task: dict[str, Any]) -> tuple[dict[str, Any], LLMTaskTelemetry]: ...


def detect_live_llm_status(
    environ: dict[str, str] | None = None,
    *,
    local_runtime_available: bool | None = None,
) -> LiveLLMStatus:
    env = environ if environ is not None else os.environ
    if env.get("OPENAI_API_KEY"):
        return LiveLLMStatus(
            status="LIVE_LLM_AVAILABLE_NOT_RUN",
            provider="openai",
            model=env.get("OPENAI_MODEL"),
            reason="OpenAI credentials detected; a dedicated exactly-three-task smoke run is required before marking complete.",
        )
    if env.get("AWS_ACCESS_KEY_ID") or env.get("AWS_PROFILE"):
        return LiveLLMStatus(
            status="LIVE_LLM_AVAILABLE_NOT_RUN",
            provider="aws",
            model=None,
            reason="AWS credentials detected; provider configuration must be verified before an exactly-three-task smoke run.",
        )
    has_local_runtime = shutil.which("ollama") is not None if local_runtime_available is None else local_runtime_available
    if has_local_runtime:
        return LiveLLMStatus(
            status="LIVE_LLM_AVAILABLE_NOT_RUN",
            provider="ollama",
            model=None,
            reason="A local Ollama runtime was detected; an installed model must be verified before an exactly-three-task smoke run.",
        )
    return LiveLLMStatus(
        status="LIVE_LLM_PENDING",
        reason="No OpenAI API key, AWS credential/profile, or supported local LLM runtime was available.",
    )
