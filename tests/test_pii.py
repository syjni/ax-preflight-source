from __future__ import annotations

import unittest

from ax_scanner.models import PIIType
from ax_scanner.pii import detect_pii, mask_text


class PIITests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (
            "주민번호 900101-1234567, 전화 010-1234-5678, "
            "메일 owner@example.com, 계좌 110-123-456789"
        )

    def test_detects_each_mvp_pattern_without_overlap(self) -> None:
        findings = detect_pii(self.text)
        self.assertEqual(
            {finding.pii_type for finding in findings},
            {
                PIIType.RESIDENT_REGISTRATION_NUMBER,
                PIIType.PHONE,
                PIIType.EMAIL,
                PIIType.ACCOUNT_NUMBER_CANDIDATE,
            },
        )
        for left, right in zip(findings, findings[1:]):
            self.assertLessEqual(left.end, right.start)

    def test_masking_is_separate_and_removes_raw_values(self) -> None:
        findings = detect_pii(self.text)
        masked = mask_text(self.text, findings)
        for raw in ("900101-1234567", "010-1234-5678", "owner@example.com", "110-123-456789"):
            self.assertNotIn(raw, masked)
        self.assertIn("[RRN_MASKED]", masked)
        self.assertIn("[PHONE_MASKED]", masked)
        self.assertIn("[EMAIL_MASKED]", masked)
        self.assertIn("[ACCOUNT_MASKED]", masked)

    def test_account_candidate_does_not_capture_iso_dates(self) -> None:
        findings = detect_pii("주문일 2026-08-03, 정산일 2026-08-29")
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
