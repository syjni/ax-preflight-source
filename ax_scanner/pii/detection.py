from __future__ import annotations

import re
from dataclasses import dataclass

from ax_scanner.models import PIIType


@dataclass(frozen=True)
class DetectedPII:
    pii_type: PIIType
    start: int
    end: int
    masked_token: str


_PATTERNS = [
    (
        PIIType.RESIDENT_REGISTRATION_NUMBER,
        re.compile(r"(?<!\d)\d{6}-?[1-4]\d{6}(?!\d)"),
        "[RRN_MASKED]",
    ),
    (
        PIIType.PHONE,
        re.compile(r"(?<!\d)(?:02[- ]?\d{3,4}[- ]?\d{4}|01[016789][- ]?\d{3,4}[- ]?\d{4}|0[3-6][1-5][- ]?\d{3,4}[- ]?\d{4})(?!\d)"),
        "[PHONE_MASKED]",
    ),
    (
        PIIType.EMAIL,
        re.compile(r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w.-])"),
        "[EMAIL_MASKED]",
    ),
    (
        PIIType.ACCOUNT_NUMBER_CANDIDATE,
        re.compile(r"(?<!\d)\d{2,6}[- ]+\d{2,6}[- ]+\d{4,6}(?:[- ]+\d{1,4})?(?!\d)"),
        "[ACCOUNT_MASKED]",
    ),
]


def detect_pii(text: str) -> list[DetectedPII]:
    """Return deterministic, non-overlapping candidates without modifying text."""
    accepted: list[DetectedPII] = []
    occupied: list[tuple[int, int]] = []
    for pii_type, pattern, token in _PATTERNS:
        for match in pattern.finditer(text):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in occupied):
                continue
            accepted.append(DetectedPII(pii_type=pii_type, start=span[0], end=span[1], masked_token=token))
            occupied.append(span)
    return sorted(accepted, key=lambda finding: (finding.start, finding.end, finding.pii_type.value))
