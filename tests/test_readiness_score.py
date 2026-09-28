from __future__ import annotations

import copy
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from readiness_score import canonical_json, calculate_readiness_score


def _file(file_id: str, *, status: str = "PARSED", modified_at: object = "2026-09-21T00:00:00Z") -> dict:
    return {"file_id": file_id, "parse_status": status, "modified_at": modified_at}


def _table(rows: int, null_ratios: list[float]) -> dict:
    return {
        "row_count": rows,
        "column_count": len(null_ratios),
        "columns": [{"null_ratio": ratio} for ratio in null_ratios],
    }


def _perfect_report(file_count: int = 1) -> dict:
    files = [_file(f"F{index}") for index in range(file_count)]
    return {
        "scan_metadata": {"file_count": file_count},
        "files": files,
        "tables": [_table(10, [0.0, 0.0])],
        "duplicates": [],
        "probable_version_groups": [],
        "unreadable_sources": [],
        "pii_findings": [],
    }


class ReadinessScoreTests(unittest.TestCase):
    def test_all_perfect_fixture_scores_100(self) -> None:
        result = calculate_readiness_score(_perfect_report())
        self.assertEqual(result["readiness_score"], 100.0)
        self.assertEqual(set(result["dimensions"].values()), {1.0})

    def test_parser_failure_lowers_accessibility(self) -> None:
        report = _perfect_report(2)
        report["files"][1]["parse_status"] = "ERROR"
        result = calculate_readiness_score(report)
        self.assertEqual(result["dimensions"]["accessibility"], 0.5)
        self.assertEqual(result["counts"]["accessibility"]["accessible_files"], 1)

    def test_ocr_required_lowers_accessibility(self) -> None:
        report = _perfect_report(2)
        report["unreadable_sources"] = [{"file_id": "F1", "requires_ocr": True}]
        result = calculate_readiness_score(report)
        self.assertEqual(result["dimensions"]["accessibility"], 0.5)

    def test_null_cells_lower_completeness(self) -> None:
        report = _perfect_report()
        report["tables"] = [_table(10, [0.0, 0.5])]
        result = calculate_readiness_score(report)
        self.assertEqual(result["dimensions"]["completeness"], 0.75)
        self.assertEqual(result["counts"]["completeness"]["estimated_missing_cells"], 5.0)

    def test_completeness_is_weighted_by_cells_not_tables(self) -> None:
        report = _perfect_report()
        report["tables"] = [_table(1, [1.0]), _table(100, [0.0])]
        result = calculate_readiness_score(report)
        self.assertEqual(result["dimensions"]["completeness"], 0.990099)
        self.assertNotEqual(result["dimensions"]["completeness"], 0.5)

    def test_no_table_policy_is_explicit(self) -> None:
        report = _perfect_report()
        report["tables"] = []
        result = calculate_readiness_score(report)
        self.assertEqual(result["dimensions"]["completeness"], 1.0)
        self.assertTrue(result["flags"]["completeness_not_applicable"])

    def test_one_exact_duplicate_lowers_redundancy(self) -> None:
        report = _perfect_report(2)
        report["duplicates"] = [{"file_ids": ["F0", "F1"]}]
        result = calculate_readiness_score(report)
        self.assertEqual(result["dimensions"]["redundancy"], 0.5)
        self.assertEqual(result["counts"]["redundancy"]["redundant_files"], 1)

    def test_probable_version_group_does_not_lower_redundancy(self) -> None:
        report = _perfect_report(2)
        report["probable_version_groups"] = [{"candidates": [{"file_id": "F0"}, {"file_id": "F1"}]}]
        result = calculate_readiness_score(report)
        self.assertEqual(result["dimensions"]["redundancy"], 1.0)

    def test_stale_file_lowers_timeliness_and_recent_file_does_not(self) -> None:
        report = _perfect_report(2)
        report["files"][0]["modified_at"] = "2025-09-20T00:00:00Z"
        result = calculate_readiness_score(report)
        self.assertEqual(result["dimensions"]["timeliness"], 0.5)
        self.assertEqual(result["counts"]["timeliness"]["stale_files"], 1)
        self.assertEqual(result["counts"]["timeliness"]["non_stale_files"], 1)

    def test_future_timestamp_is_valid_but_non_stale_false(self) -> None:
        report = _perfect_report(2)
        report["files"][1]["modified_at"] = "2026-09-22T00:00:00Z"
        result = calculate_readiness_score(report)
        self.assertEqual(result["dimensions"]["timeliness"], 0.5)
        self.assertEqual(result["flags"]["future_modified_at_count"], 1)
        self.assertEqual(result["counts"]["timeliness"]["files_with_valid_modified_at"], 2)

    def test_local_review_can_supply_its_own_reproducible_as_of_date(self) -> None:
        report = _perfect_report()
        report["files"][0]["modified_at"] = "2026-09-28T00:00:00Z"
        frozen = calculate_readiness_score(report)
        local = calculate_readiness_score(report, as_of_date=date(2026, 9, 29))
        self.assertEqual(frozen["flags"]["future_modified_at_count"], 1)
        self.assertEqual(local["flags"]["future_modified_at_count"], 0)
        self.assertEqual(local["as_of_date"], "2026-09-29")

    def test_missing_timestamp_is_excluded_and_flagged(self) -> None:
        report = _perfect_report(2)
        report["files"][1]["modified_at"] = None
        result = calculate_readiness_score(report)
        self.assertEqual(result["dimensions"]["timeliness"], 1.0)
        self.assertEqual(result["flags"]["missing_modified_at_count"], 1)
        self.assertEqual(result["counts"]["timeliness"]["files_with_valid_modified_at"], 1)

    def test_pii_finding_lowers_safety_and_no_finding_does_not(self) -> None:
        report = _perfect_report(2)
        baseline = calculate_readiness_score(report)
        report["pii_findings"] = [
            {"file_id": "F1", "pii_type": "email"},
            {"file_id": "F1", "pii_type": "phone"},
        ]
        changed = calculate_readiness_score(report)
        self.assertEqual(baseline["dimensions"]["safety"], 1.0)
        self.assertEqual(changed["dimensions"]["safety"], 0.5)
        self.assertEqual(changed["counts"]["safety"]["pii_affected_files"], 1)

    def test_repeated_execution_is_byte_identical(self) -> None:
        report = _perfect_report(3)
        first = canonical_json(calculate_readiness_score(report))
        second = canonical_json(calculate_readiness_score(copy.deepcopy(report)))
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))

    def test_changing_each_input_changes_only_its_dimension_and_scalar(self) -> None:
        baseline_report = _perfect_report(2)
        baseline = calculate_readiness_score(baseline_report)
        mutations = {
            "accessibility": lambda report: report["files"][1].update(parse_status="ERROR"),
            "completeness": lambda report: report.update(tables=[_table(10, [0.5])]),
            "redundancy": lambda report: report.update(duplicates=[{"file_ids": ["F0", "F1"]}]),
            "timeliness": lambda report: report["files"][1].update(modified_at="2020-01-01T00:00:00Z"),
            "safety": lambda report: report.update(pii_findings=[{"file_id": "F1"}]),
        }
        for expected_dimension, mutate in mutations.items():
            with self.subTest(expected_dimension=expected_dimension):
                report = copy.deepcopy(baseline_report)
                mutate(report)
                result = calculate_readiness_score(report)
                changed_dimensions = {
                    name
                    for name, value in result["dimensions"].items()
                    if value != baseline["dimensions"][name]
                }
                self.assertEqual(changed_dimensions, {expected_dimension})
                self.assertNotEqual(result["readiness_score"], baseline["readiness_score"])

    def test_pure_calculation_reads_no_artifacts(self) -> None:
        report = _perfect_report()
        with (
            patch.object(Path, "open", side_effect=AssertionError("artifact read")),
            patch.object(Path, "read_text", side_effect=AssertionError("artifact read")),
            patch.object(Path, "read_bytes", side_effect=AssertionError("artifact read")),
        ):
            result = calculate_readiness_score(report)
        self.assertEqual(result["readiness_score"], 100.0)


if __name__ == "__main__":
    unittest.main()
