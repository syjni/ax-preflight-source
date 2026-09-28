"""Build an ax-exp-v4 task prompt without exposing ground truth or scoring aliases."""

from __future__ import annotations

from typing import Any


def project_runtime_task(task: dict[str, Any]) -> dict[str, Any]:
    method = task["scoring_method"]
    kind = method["type"]
    if kind not in {"numeric_quantity", "set_items", "exact_text"}:
        raise ValueError(f"unknown answer kind: {kind}")
    projected = {
        "category": task["category"],
        "question": task["question"],
        "answer_kind": kind,
    }
    if kind == "numeric_quantity":
        projected["allowed_units"] = sorted(method["accepted_units"])
    return projected


def construct_runtime_prompt(task: dict[str, Any]) -> str:
    projected = project_runtime_task(task)
    lines = [
        f"업무 범주: {projected['category']}",
        f"질문: {projected['question']}",
        f"답 유형: {projected['answer_kind']}",
    ]
    if projected["answer_kind"] == "numeric_quantity":
        units = ", ".join(projected["allowed_units"])
        lines.append(f"final_answer는 JSON 숫자, unit은 다음 중 하나: {units}")
    elif projected["answer_kind"] == "set_items":
        lines.append("final_answer는 중복 없는 짧은 항목 문자열의 JSON 배열, unit은 null")
    else:
        lines.append("final_answer는 짧은 문자열, unit은 null")
    lines.append("근거가 부족할 때만 abstain=true, final_answer=null로 답하세요.")
    return "\n".join(lines) + "\n"
