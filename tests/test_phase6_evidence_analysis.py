from scripts.analyze_phase6_evidence_gaps import analyze


def test_frozen_v3_gap_analysis_reaches_majority_without_mutating_snapshot() -> None:
    result = analyze()

    assert result["stored_unconfirmed_run_count"] == 19
    assert result["newly_direct_match_count"] == 11
    assert result["remaining_unconfirmed_count"] == 8
    assert result["source_snapshot_modified"] is False
    assert result["root_cause_counts"] == {
        "ABSTENTION_EXPLANATION_NOT_LEXICALLY_PRESENT": 4,
        "COMPLETE_TABLE_MAPPING": 2,
        "COMPLETE_TABLE_PREDICATE": 1,
        "CROSS_LANGUAGE_OR_SEMANTIC_PARAPHRASE": 2,
        "QUERY_AGGREGATE_VALUE": 6,
        "STRUCTURED_SCALAR_VALUE": 2,
        "UNCITED_ABSTENTION": 2,
    }
