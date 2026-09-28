import pytest

from scripts.run_phase6_demo_v4 import EXPECTED_RUN_COUNT, estimate_runtime
from scripts.run_phase6_demo_v4 import PROFILES
from scripts.verify_phase6_demo_v4 import (
    Phase6V4VerificationError,
    _pilot_evidence_reproducible,
    _sha256_canonical_crlf_text,
    _validate_pilot_summary,
)
from ax_product.evidence import EvidenceCheckResult


def test_v4_estimate_uses_all_v3_portfolio_durations() -> None:
    result = estimate_runtime()

    assert result["historical_run_count"] == 20
    assert result["planned_run_count"] == EXPECTED_RUN_COUNT == 60
    assert result["estimated_minutes"] > 0
    assert result["planning_minutes_with_25_percent_buffer"] > result["estimated_minutes"]


def test_v4_runtime_config_hash_is_portable_across_newlines(tmp_path) -> None:
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{\n  "profile": "demo"\n}\n')
    crlf.write_bytes(b'{\r\n  "profile": "demo"\r\n}\r\n')

    assert _sha256_canonical_crlf_text(lf) == _sha256_canonical_crlf_text(crlf)


def test_v4_freeze_requires_exact_three_by_two_by_ten_matrix() -> None:
    task_ids = [f"TASK_{index:02d}" for index in range(10)]
    rows = [
        {
            "dataset": profile,
            "task_id": task_id,
            "repetition": repetition,
            "run_id": f"phase6v4-{profile}-{task_id.lower()}-r{repetition}",
        }
        for profile in PROFILES
        for task_id in task_ids
        for repetition in range(1, 4)
    ]
    summary = {
        "completed_at": "2026-09-27T00:00:00Z",
        "profiles": PROFILES,
        "repetitions": 3,
        "run_namespace": "phase6v4",
        "task_ids": task_ids,
        "runs": rows,
    }

    _validate_pilot_summary(summary)
    with pytest.raises(Phase6V4VerificationError):
        _validate_pilot_summary({**summary, "runs": rows[:-1]})


def test_v4_accepts_prior_v2_rule_label_only_when_direct_evidence_is_identical() -> None:
    common = {
        "schema_version": "ax-evidence-check-v1",
        "run_id": "run-1",
        "delivery_sha256": "0" * 64,
        "verdict": "DIRECT_MATCH",
        "cited_source_ids": ["TABLE_1"],
        "matched_source_ids": ["TABLE_1"],
        "unmatched_source_ids": [],
        "evidence": [{
            "sequence": 1,
            "tool_name": "query_table",
            "source_ids": ["TABLE_1"],
            "match": "DIRECT_VALUE",
        }],
        "derivation": None,
        "unconfirmed_is_not_incorrect": True,
    }
    stored = EvidenceCheckResult(**{
        **common, "limitations": ["Evidence Checker v2: old rule."],
    })
    current = EvidenceCheckResult(**{
        **common, "limitations": ["Evidence Checker v2: refined rule."],
    })
    baseline = current.model_copy(update={"verdict": "UNCONFIRMED"})

    assert _pilot_evidence_reproducible(stored, baseline, current)
    changed = stored.model_copy(update={"matched_source_ids": []})
    assert not _pilot_evidence_reproducible(changed, baseline, current)
