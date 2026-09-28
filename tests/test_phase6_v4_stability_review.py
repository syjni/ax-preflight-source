from __future__ import annotations

import unittest

from scripts.analyze_phase6_v4_stability import analyze


class Phase6V4StabilityReviewTests(unittest.TestCase):
    def test_only_return_faq_changed_between_source_trees(self) -> None:
        result = analyze()

        self.assertEqual(result["before_file_count"], 30)
        self.assertEqual(result["after_file_count"], 30)
        self.assertEqual(
            [item["relative_path"] for item in result["changed_files"]],
            ["06_고객지원/FAQ_2026.txt"],
        )

    def test_three_lost_tasks_do_not_cite_changed_faq(self) -> None:
        result = analyze()

        self.assertEqual(
            result["lost_stability_task_ids"],
            [
                "TASK_BILLING_INVOICE_DEADLINE",
                "TASK_INVENTORY_MOST_AVAILABLE",
                "TASK_ORDER_MONTHLY_AMOUNT",
            ],
        )
        self.assertTrue(result["all_lost_tasks_exclude_changed_file_from_citations"])
        lost = [item for item in result["tasks"] if item["lost_stability"]]
        self.assertEqual(
            {item["attribution"] for item in lost},
            {"DATA_CAUSE_NOT_ESTABLISHED"},
        )


if __name__ == "__main__":
    unittest.main()
