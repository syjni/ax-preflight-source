from __future__ import annotations

from .detection import DetectedPII


def mask_text(text: str, findings: list[DetectedPII]) -> str:
    """Mask already-detected spans; detection and replacement remain independently testable."""
    output = []
    cursor = 0
    for finding in sorted(findings, key=lambda item: item.start):
        if finding.start < cursor:
            raise ValueError("PII findings overlap or are not ordered")
        output.append(text[cursor : finding.start])
        output.append(finding.masked_token)
        cursor = finding.end
    output.append(text[cursor:])
    return "".join(output)

