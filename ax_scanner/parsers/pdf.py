from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from .base import ParsedContent


def parse_pdf(path: Path, file_id: str, *, ocr_min_chars_per_page: int = 20, **_: object) -> ParsedContent:
    reader = PdfReader(str(path))
    page_text = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(part for part in page_text if part)
    compact_chars = sum(not char.isspace() for char in text)
    threshold = max(ocr_min_chars_per_page, len(reader.pages) * ocr_min_chars_per_page)
    requires_ocr = compact_chars < threshold
    return ParsedContent(
        parser="pdf",
        text=text,
        metadata={"page_count": len(reader.pages), "non_whitespace_char_count": compact_chars, "ocr_threshold": threshold},
        requires_ocr=requires_ocr,
        unreadable_reason="PDF_TEXT_BELOW_OCR_THRESHOLD" if requires_ocr else None,
    )

