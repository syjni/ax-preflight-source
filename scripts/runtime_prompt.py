"""Blind runtime prompt projection for future Kiro execution samples.

This module deliberately accepts a full benchmark task only long enough to
project its two user-facing fields.  It does not execute Kiro or an MCP tool.
"""

from __future__ import annotations

from typing import Any


RUNTIME_PROMPT_FIELDS = ("category", "question")


def project_runtime_prompt(task: dict[str, Any]) -> dict[str, str]:
    """Return the exact, evaluation-safe payload intended for a runtime user prompt."""
    projected = {field: task[field] for field in RUNTIME_PROMPT_FIELDS}
    if set(projected) != set(RUNTIME_PROMPT_FIELDS):
        raise ValueError("runtime prompt projection must contain only category and question")
    if not all(isinstance(value, str) and value.strip() for value in projected.values()):
        raise ValueError("runtime prompt fields must be non-empty strings")
    return projected


def construct_runtime_prompt(projected: dict[str, str]) -> str:
    """Render an explicit two-field prompt with no benchmark-plan expansion."""
    if set(projected) != set(RUNTIME_PROMPT_FIELDS):
        raise ValueError("runtime prompt constructor accepts only category and question")
    return f"업무 범주: {projected['category']}\n질문: {projected['question']}"
