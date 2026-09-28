from __future__ import annotations

import unittest

from scripts.run_candidate_portfolio import _profile_summary, run_id


class CandidatePortfolioTests(unittest.TestCase):
    def test_run_id_is_stable_and_result_store_compatible(self) -> None:
        value = run_id(
            "portfolio-hidden-conflict-before",
            "TASK_POLICY_RETURN_WINDOW",
            2,
        )
        self.assertEqual(
            value,
            "portfolio-portfolio-hidden-conflict-before-task_policy_return_window-r2",
        )
        self.assertLessEqual(len(value), 128)

    def test_profile_summary_keeps_rejections_and_finding_types_explicit(self) -> None:
        rows = [
            {
                "delivery_status": "DELIVERED",
                "payload_status": "ANSWERED",
                "abstention_reason": None,
                "evidence_verdict": "DIRECT_MATCH",
            },
            {
                "delivery_status": "DELIVERED",
                "payload_status": "ABSTAINED",
                "abstention_reason": "CONFLICTING_EVIDENCE",
                "evidence_verdict": "UNCONFIRMED",
            },
            {
                "delivery_status": "REJECTED",
                "payload_status": None,
                "abstention_reason": None,
                "evidence_verdict": None,
            },
        ]
        findings = {
            "diagnostics": {"task_count": 3, "blocked_task_count": 1},
            "findings": [
                {"finding_type": "CONFLICTING_SOURCES"},
                {"finding_type": "MISSING_INFORMATION"},
            ],
        }

        summary = _profile_summary(rows, findings)

        self.assertEqual(summary["outcomes"], {
            "ABSTAINED": 1, "ANSWERED": 1, "REJECTED": 1,
        })
        self.assertEqual(
            summary["abstention_reasons"], {"CONFLICTING_EVIDENCE": 1}
        )
        self.assertEqual(summary["finding_types"], {
            "CONFLICTING_SOURCES": 1, "MISSING_INFORMATION": 1,
        })

    def test_run_id_accepts_isolated_v4_namespace(self) -> None:
        value = run_id(
            "portfolio-ceiling-after", "TASK_CUSTOMER_COUNT", 3,
            namespace="phase6v4",
        )

        self.assertEqual(
            value,
            "phase6v4-portfolio-ceiling-after-task_customer_count-r3",
        )


if __name__ == "__main__":
    unittest.main()
