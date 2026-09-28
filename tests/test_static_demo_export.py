from __future__ import annotations

import json

import pytest

from scripts.export_static_demo import DEFAULT_OUTPUT, _validate_featured_cases, build_static_demo_snapshot


def test_checked_in_static_demo_matches_verified_api() -> None:
    expected = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    observed = build_static_demo_snapshot()

    assert observed == expected
    assert observed["read_only"] is True
    assert observed["schema_version"] == "ax-static-demo-v5"
    assert observed["default_dataset"] == "portfolio-hidden-conflict-before"
    assert len(observed["runs"]) == 60
    assert len(observed["evidence"]) == 60
    assert len(observed["retrieval_traces"]) == 60
    assert len(observed["onboarding"]) == 5
    assert all(
        assessment["can_run"] for assessment in observed["onboarding"].values()
    )
    assert len(observed["featured_cases"]) == 1

    case = observed["featured_cases"][0]
    before = case["before"]
    after = case["after"]
    assert observed["runs"][before["run_id"]]["payload"]["status"] == "ABSTAINED"
    assert observed["runs"][after["run_id"]]["payload"]["answer"] == "30일"
    assert observed["evidence"][after["run_id"]]["verdict"] == "DIRECT_MATCH"
    trace = observed["retrieval_traces"][after["run_id"]]
    assert trace["schema_version"] == "ax-retrieval-trace-v2"
    assert [step["tool_name"] for step in trace["steps"]] == [
        "search_documents", "read_document"
    ]
    assert all(step["status"] == "SUCCESS" for step in trace["steps"])
    assert any(step["cited_source_ids"] for step in trace["steps"])


def test_featured_case_validation_rejects_answer_drift() -> None:
    snapshot = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    after = snapshot["featured_cases"][0]["after"]
    snapshot["runs"][after["run_id"]]["payload"]["answer"] = "14일"

    with pytest.raises(ValueError, match="no longer answers 30 days"):
        _validate_featured_cases(snapshot)
