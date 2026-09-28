"""Audit all v5 attempts before computing any preregistered outcome totals."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity
from scripts.session_prompt_validation import validate_submitted_prompt
from scripts.stream_response_validation import validate_stream_response
from scripts.v4_evaluation import evaluate_response
from scripts.v4_prompt import construct_runtime_prompt
from scripts.v5_official_runner import (
    ARTIFACT_ROOT, FROZEN_MANIFEST, ROOT, V5, _agent_config, _events,
)
from scripts.v5_preflight import validate_manifest


RETRY_ROOT = ROOT / "artifacts" / "heldout_ax-exp-v5-retries"
AUDIT = ARTIFACT_ROOT / "AUDIT.json"
ANALYSIS = ARTIFACT_ROOT / "ANALYSIS.json"
RESULTS = ARTIFACT_ROOT / "RESULTS.md"
PROGRESS = ARTIFACT_ROOT / "PROGRESS.md"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_new(path: Path, value: object) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite derived v5 artifact: {path}")
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def inspect_attempt(path: Path, task: dict, manifest: dict, identity: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    metadata = load(path / "metadata.json")
    label = path.relative_to(ROOT).as_posix()

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(f"{label}: {message}")

    task_id, repetition = metadata.get("task_id"), metadata.get("repetition")
    check(path.parts[-2:] == (task_id, f"r{repetition}"), "path and slot disagree")
    check(metadata.get("schema_version") == "ax-interactive-run-v5", "run schema differs")
    check(metadata.get("experiment_version") == "ax-exp-v5", "experiment id differs")
    check(metadata.get("execution_backend") == manifest["backend"], "backend differs")
    check(metadata.get("run_status") == "RECORDED", "run was not recorded")
    check(metadata.get("validity_status") in {"VALID", "INVALID"}, "unknown validity status")
    check(metadata.get("manifest_sha256") == sha(FROZEN_MANIFEST), "frozen manifest hash differs")
    expected_prompt = construct_runtime_prompt(task)
    prompt = (path / "prompt.txt").read_bytes()
    check(prompt == expected_prompt.encode("utf-8"), "prepared prompt differs from frozen task")
    check(hashlib.sha256(prompt).hexdigest() == metadata.get("prompt_sha256"), "prompt hash differs")
    command = load(path / "command.json")
    check(isinstance(command, list) and len(command) == 11 and
          Path(command[0]).name.casefold() == "kiro-cli.exe" and
          command[1:] == ["chat", "--no-interactive", "--output-format", "stream-json",
                          "--agent-engine", "v2", "--agent", metadata["agent_name"],
                          "--require-mcp-startup", expected_prompt],
          "submitted command differs from frozen backend")
    config_path = ROOT / metadata["agent_config"]
    check(sha(config_path) == metadata.get("agent_config_sha256"), "agent config hash differs")
    check(load(config_path) == _agent_config(path, manifest, metadata["agent_name"]),
          "agent config differs from frozen construction")
    check(metadata.get("runtime_profile") == manifest["runtime_profile"], "runtime profile differs")
    check(metadata.get("runtime_identity") == identity, "prepared runtime identity differs")
    runtime_path = path / "runtime-identity-receipt.json"
    runtime_receipt = load(runtime_path)
    check(sha(runtime_path) == metadata.get("runtime_receipt_sha256"), "runtime receipt hash differs")
    check(runtime_receipt.get("passed") is True and runtime_receipt.get("identity") == identity,
          "runtime receipt failed or differs")
    check(metadata.get("fresh_process") is True and metadata.get("resume_used") is False,
          "fresh process evidence failed")
    check(metadata.get("process_exit_code") == 0 and metadata.get("process_terminated") is True,
          "process exit failed")
    check(not metadata.get("timeout"), "process timed out")
    session_id = metadata["session_id"]
    for field, digest_field in (("session_file", "session_file_sha256"),
                                ("session_events_file", "session_events_file_sha256")):
        check(sha(Path(metadata[field])) == metadata.get(digest_field), f"{field} hash differs")
    session = load(Path(metadata["session_file"]))
    state = session.get("session_state", {})
    check(session.get("session_id") == session_id and state.get("agent_name") == metadata["agent_name"],
          "session identity differs")
    check(state.get("rts_model_state", {}).get("model_info", {}).get("model_id") == manifest["model"],
          "session model differs")
    turns = state.get("conversation_metadata", {}).get("user_turn_metadatas", [])
    check(len(turns) == 1 and turns[0].get("model") == manifest["model"], "turn count or model differs")
    prompt_receipt = validate_submitted_prompt(path, session_id, metadata["agent_name"])
    responses = prompt_receipt.pop("assistant_responses")
    check(prompt_receipt == load(path / "submitted-prompt-validation.json") and prompt_receipt["passed"],
          "exact submitted prompt receipt failed")
    check(len(responses) == 1, "session final response count differs")
    raw_path = path / "raw_response.txt"
    raw = raw_path.read_text(encoding="utf-8")
    check(len(responses) == 1 and responses[-1] == raw, "raw response differs from session final")
    check(sha(raw_path) == metadata.get("raw_response_sha256"), "raw response hash differs")
    stream_path = path / "stream.jsonl"
    stream_events = _events(stream_path.read_bytes())
    started = [event for event in stream_events if event.get("type") == "runStarted"]
    finished = [event for event in stream_events if event.get("type") == "runFinished"]
    check(len(started) == 1 and started[0].get("data", {}).get("engine") == "v2",
          "v2 start event differs")
    check(len(finished) == 1 and finished[0].get("data", {}).get("sessionId") == session_id,
          "finish event or session differs")
    stream_receipt = validate_stream_response(
        stream_path, Path(metadata["session_events_file"]), session_id=session_id,
        final_response=raw)
    stream_receipt_path = path / "stream-response-validation.json"
    check(stream_receipt == load(stream_receipt_path) and stream_receipt["passed"],
          "three-way stream/final response validation failed")
    check(sha(stream_receipt_path) == metadata.get("stream_response_receipt_sha256"),
          "stream receipt hash differs")
    invocation_path = path / "mcp-invocations-live.jsonl"
    invocations = [json.loads(line) for line in invocation_path.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
    check(sha(invocation_path) == metadata.get("mcp_invocation_log_sha256"), "MCP log hash differs")
    check(len(invocations) == metadata.get("mcp_invocation_count"), "MCP invocation count differs")
    check(all(entry.get("tool_name") in {"search_documents", "read_document",
                                              "lookup_value", "query_table"} for entry in invocations),
          "unregistered MCP tool invoked")
    evaluation = evaluate_response(task, raw)
    check(evaluation.receipt() == load(path / "evaluation.json"), "frozen evaluation differs")
    for field in ("native_strict", "delivered_valid", "outcome", "primary_success"):
        check(metadata.get(field) == getattr(evaluation, field), f"metadata {field} differs")
    delivered_path = path / "delivered.json"
    if evaluation.delivered_json is None:
        check(not delivered_path.exists(), "unexpected delivered JSON")
    else:
        check(delivered_path.is_file() and delivered_path.read_bytes() ==
              evaluation.delivered_json.encode("utf-8"), "delivered JSON differs")
    if metadata.get("validity_status") == "VALID":
        check(metadata.get("validation_errors") == [], "VALID run has validation errors")
    row = {"path": label, "task_id": task_id, "repetition": repetition,
           "stratum": task["stratum"], "start_timestamp": metadata["start_timestamp"],
           "end_timestamp": metadata["end_timestamp"], "session_id": session_id,
           "process_id": metadata["process_id"], "validity_status": metadata["validity_status"],
           "validation_errors": metadata.get("validation_errors"),
           "prompt_sha256": metadata["prompt_sha256"], "raw_response_sha256": sha(raw_path),
           "stream_sha256": sha(stream_path), "stream_aggregate_sha256": stream_receipt["aggregate_sha256"],
           "stream_final_sha256": stream_receipt["final_response_sha256"],
           "assistant_message_count": stream_receipt["assistant_message_count"],
           "evaluation": evaluation.receipt(), "audit_errors": errors}
    return row, errors


def aggregate(rows: list[dict], manifest: dict) -> dict:
    valid = [row for row in rows if row["validity_status"] == "VALID"]
    scores = [row["evaluation"] for row in valid]

    def totals(items: list[dict]) -> dict:
        return {"runs": len(items),
                "primary_success": sum(item["primary_success"] for item in items),
                "native_strict": sum(item["native_strict"] for item in items),
                "delivered_valid": sum(item["delivered_valid"] for item in items),
                "content_correct": sum(item["correct"] for item in items),
                "gate_rejected": sum(item["gate_decision"] == "REJECTED" for item in items),
                "correct_and_native_strict": sum(item["correct"] and item["native_strict"] for item in items)}

    by_stratum = {}
    for stratum in ("ratio", "threshold", "set", "exact_or_abstain"):
        by_stratum[stratum] = totals([row["evaluation"] for row in valid if row["stratum"] == stratum])
    pairs = defaultdict(dict)
    for row in valid:
        pairs[row["task_id"]][row["repetition"]] = row["evaluation"]
    agreement = {"primary_success": 0, "outcome": 0, "native_strict": 0,
                 "delivered_valid": 0}
    task_rows = []
    for task in manifest["tasks"]:
        identifier = task["task_id"]
        first, second = pairs[identifier][1], pairs[identifier][2]
        for field in agreement:
            agreement[field] += first[field] == second[field]
        task_rows.append({"task_id": identifier, "stratum": task["stratum"],
                          "r1": {key: first[key] for key in ("outcome", "native_strict",
                                                            "delivered_valid", "primary_success")},
                          "r2": {key: second[key] for key in ("outcome", "native_strict",
                                                             "delivered_valid", "primary_success")}})
    return {"schema_version": "ax-v5-official-analysis-v1",
            "experiment_id": "ax-exp-v5", "manifest_sha256": sha(FROZEN_MANIFEST),
            "completed_valid_runs": len(valid), "unique_tasks": len(pairs),
            "overall": totals(scores),
            "outcomes": dict(Counter(item["outcome"] for item in scores)),
            "gate_decisions": dict(Counter(item["gate_decision"] for item in scores)),
            "by_stratum": by_stratum,
            "repetition_agreement_task_count": agreement,
            "task_results": task_rows,
            "note": "v4 was incomplete and is not a comparison group; repetitions are not distinct tasks."}


def report(analysis: dict) -> str:
    overall = analysis["overall"]
    lines = [
        "# AX v5 공식 held-out 결과", "",
        "사전등록된 16개 새 과제 × 2회 = **32/32 VALID**. 실행 전수 감사 통과 후에만 아래 수치를 집계했다. v4는 미완료이므로 대조군으로 사용하지 않는다.", "",
        "## 전체", "",
        f"- 1차 지표, 정답과 전달 JSON 동시 충족: **{overall['primary_success']}/32**.",
        f"- 원문 엄격 JSON: **{overall['native_strict']}/32**. 게이트 후 전달 JSON: **{overall['delivered_valid']}/32**.",
        f"- 고정 내용 정답: **{overall['content_correct']}/32**. 게이트 거부: **{overall['gate_rejected']}/32**.",
        f"- 정답과 원문 엄격 JSON 동시 충족: **{overall['correct_and_native_strict']}/32**.",
        "", "## 층별", "",
        "| 층 | 유효 실행 | 1차 지표 | 원문 엄격 JSON | 전달 JSON | 내용 정답 |", "|---|---:|---:|---:|---:|---:|",
    ]
    labels = {"ratio": "비율", "threshold": "임계값", "set": "항목 집합",
              "exact_or_abstain": "정확 문자열·보류"}
    for key, label in labels.items():
        item = analysis["by_stratum"][key]
        lines.append(f"| {label} | {item['runs']} | {item['primary_success']} | {item['native_strict']} | {item['delivered_valid']} | {item['content_correct']} |")
    agreement = analysis["repetition_agreement_task_count"]
    lines.extend(["", "## 반복 일치와 해석", "",
                  f"- 같은 과제의 두 반복에서 1차 지표 일치: {agreement['primary_success']}/16과제; 내용 판정 일치: {agreement['outcome']}/16; 원문 형식 일치: {agreement['native_strict']}/16; 전달 가능성 일치: {agreement['delivered_valid']}/16.",
                  "- 두 반복은 32개의 독립 과제가 아니다. 새 자료·질문이므로 v3 또는 미완료 v4와 점수 차이를 인과 효과로 해석하지 않는다.",
                  "- 고정 채점은 등록된 답 표현·단위·허용오차에 따른다. `source_ids`의 의미적 정확성은 별도 수동 감사 지표로 등록하지 않았으므로 점수에 추가하지 않았다.",
                  "", "전수 실행 증거와 재계산 결과는 `AUDIT.json`, 세부 과제 결과는 `ANALYSIS.json`에 있다.", ""])
    return "\n".join(lines)


def main() -> int:
    manifest = load(FROZEN_MANIFEST)
    errors = validate_manifest(manifest)
    task_map = {task["task_id"]: task for task in manifest["tasks"]}
    order = {(task["task_id"], repetition): index
             for index, (repetition, task) in enumerate(
                 (pair for rep in (1, 2) for pair in ((rep, task) for task in manifest["tasks"]))) }
    dataset = resolve_runtime_dataset(manifest["runtime_profile"], V5 / "runtime_datasets.json")
    identity = runtime_identity(dataset)
    paths = [path.parent for root in (ARTIFACT_ROOT, RETRY_ROOT)
             for path in root.rglob("metadata.json") if path.parent.name in ("r1", "r2")]
    rows = []
    for path in paths:
        try:
            metadata = load(path / "metadata.json")
            key = (metadata.get("task_id"), metadata.get("repetition"))
            if key not in order:
                errors.append(f"unregistered slot: {path}")
                continue
            row, issues = inspect_attempt(path, task_map[key[0]], manifest, identity)
            rows.append(row)
            errors.extend(issues)
        except Exception as exc:
            errors.append(f"unable to audit {path}: {type(exc).__name__}: {exc}")
    rows.sort(key=lambda row: row["start_timestamp"])
    expected = len(manifest["tasks"]) * manifest["repetitions"]
    valid_counts = Counter((row["task_id"], row["repetition"]) for row in rows
                           if row["validity_status"] == "VALID")
    missing = [key for key in order if valid_counts[key] == 0]
    duplicate = [key for key, count in valid_counts.items() if count > 1]
    if missing:
        errors.append(f"missing valid slots: {missing}")
    if duplicate:
        errors.append(f"duplicate valid slots: {duplicate}")
    if len(rows) != expected:
        errors.append(f"attempt count {len(rows)} differs from planned {expected}")
    positions = [order[(row["task_id"], row["repetition"])] for row in rows]
    if positions != sorted(positions):
        errors.append("execution order differs from registered order")
    for before, after in zip(rows, rows[1:]):
        if before["end_timestamp"] > after["start_timestamp"]:
            errors.append(f"overlapping execution windows: {before['path']} and {after['path']}")
    sessions = [row["session_id"] for row in rows]
    if len(sessions) != len(set(sessions)):
        errors.append("duplicate Kiro session id")
    if any(row["validity_status"] != "VALID" for row in rows):
        errors.append("one or more attempts are INVALID")
    audit = {"schema_version": "ax-v5-official-audit-v1",
             "generated_at_utc": datetime.now(timezone.utc).isoformat(),
             "manifest_sha256": sha(FROZEN_MANIFEST), "passed": not errors,
             "expected_valid_slots": expected, "valid_slots": len(valid_counts),
             "attempt_count": len(rows), "unique_session_count": len(set(sessions)),
             "missing_slots": [list(key) for key in missing],
             "duplicate_valid_slots": [list(key) for key in duplicate],
             "errors": errors, "run_rows": rows}
    save_new(AUDIT, audit)
    if errors:
        print(json.dumps({"audit_passed": False, "errors": errors}, ensure_ascii=False))
        return 1
    analysis = aggregate(rows, manifest)
    save_new(ANALYSIS, analysis)
    save_new(RESULTS, report(analysis))
    save_new(PROGRESS, "# AX v5 공식 실행 진행\n\n32/32 VALID. 재시도 0회. 전수 감사 통과. 공식 결과는 `RESULTS.md`, 세부 집계는 `ANALYSIS.json`, 실행 증거는 `AUDIT.json`에 저장했다.\n")
    print(json.dumps({"audit_passed": True, "valid_slots": len(valid_counts),
                      "attempts": len(rows), "analysis_saved": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
