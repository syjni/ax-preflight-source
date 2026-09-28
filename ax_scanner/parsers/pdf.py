from __future__ import annotations

import os
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from ax_scanner.ocr import (
    detect_ocr_capability,
    ocr_pdf_pages,
    preferred_ocr_language,
)
from ax_scanner.profiling import profile_rows

from .base import ParsedContent


OCR_MODE_ENV = "AX_PRODUCT_OCR_MODE"
OCR_MAX_PAGES_ENV = "AX_PRODUCT_OCR_MAX_PAGES"
DEFAULT_OCR_MAX_PAGES = 50


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _pdf_tables(path: Path, file_id: str) -> tuple[list, str, str | None]:
    tables = []
    try:
        with pdfplumber.open(path) as document:
            for page_number, page in enumerate(document.pages, start=1):
                for table_number, rows in enumerate(page.extract_tables() or [], start=1):
                    if not rows or not any(any(cell not in (None, "") for cell in row) for row in rows):
                        continue
                    tables.append(profile_rows(
                        rows,
                        file_id=file_id,
                        sheet_name=f"PDF p{page_number} table {table_number}",
                    ))
    except Exception as exc:
        return [], "ERROR", f"{type(exc).__name__}: {str(exc)[:240]}"
    return tables, "COMPLETED", None


def parse_pdf(
    path: Path,
    file_id: str,
    *,
    ocr_min_chars_per_page: int = 20,
    pdf_enhancements: bool = True,
    **_: object,
) -> ParsedContent:
    reader = PdfReader(str(path))
    page_text = [(page.extract_text() or "").strip() for page in reader.pages]
    if not pdf_enhancements:
        # Historical experiment regeneration must remain byte-identical to the
        # original scanner contract. Current product scans leave this enabled.
        text = "\n\n".join(part for part in page_text if part)
        compact_chars = sum(not char.isspace() for char in text)
        threshold = max(
            ocr_min_chars_per_page,
            len(reader.pages) * ocr_min_chars_per_page,
        )
        requires_ocr = compact_chars < threshold
        return ParsedContent(
            parser="pdf",
            text=text,
            metadata={
                "page_count": len(reader.pages),
                "non_whitespace_char_count": compact_chars,
                "ocr_threshold": threshold,
            },
            requires_ocr=requires_ocr,
            unreadable_reason=(
                "PDF_TEXT_BELOW_OCR_THRESHOLD" if requires_ocr else None
            ),
        )
    low_text_pages = [
        index
        for index, text in enumerate(page_text, start=1)
        if sum(not char.isspace() for char in text) < ocr_min_chars_per_page
    ]
    mode = os.environ.get(OCR_MODE_ENV, "auto").strip().casefold()
    if mode not in {"auto", "off"}:
        mode = "off"
    capability = detect_ocr_capability()
    max_pages = _positive_int_env(OCR_MAX_PAGES_ENV, DEFAULT_OCR_MAX_PAGES)
    ocr_status = "NOT_REQUIRED"
    ocr_language = None
    ocr_results = []
    ocr_error = None
    if low_text_pages:
        if mode == "off":
            ocr_status = "DISABLED"
        elif len(low_text_pages) > max_pages:
            ocr_status = "PAGE_LIMIT_EXCEEDED"
        elif not capability.available:
            ocr_status = "UNAVAILABLE"
            ocr_error = capability.reason
        else:
            ocr_language = preferred_ocr_language(capability.languages)
            try:
                ocr_results = ocr_pdf_pages(
                    path, low_text_pages, language=ocr_language
                )
                for result in ocr_results:
                    page_text[result.page_number - 1] = result.text
                ocr_status = "COMPLETED"
            except Exception as exc:
                ocr_status = "FAILED"
                ocr_error = f"{type(exc).__name__}: {str(exc)[:240]}"

    unresolved_pages = [
        index
        for index in low_text_pages
        if sum(not char.isspace() for char in page_text[index - 1])
        < ocr_min_chars_per_page
    ]
    text = "\n\n".join(part for part in page_text if part)
    compact_chars = sum(not char.isspace() for char in text)
    threshold = max(ocr_min_chars_per_page, len(reader.pages) * ocr_min_chars_per_page)
    requires_ocr = bool(unresolved_pages)
    tables, table_status, table_error = _pdf_tables(path, file_id)
    confidences = [
        result.confidence for result in ocr_results if result.confidence is not None
    ]
    return ParsedContent(
        parser="pdf",
        text=text,
        tables=tables,
        metadata={
            "page_count": len(reader.pages),
            "non_whitespace_char_count": compact_chars,
            "ocr_threshold": threshold,
            "ocr_status": ocr_status,
            "ocr_engine": capability.engine,
            "ocr_languages": list(capability.languages),
            "ocr_language": ocr_language,
            "ocr_candidate_page_numbers": low_text_pages,
            "ocr_processed_page_numbers": [result.page_number for result in ocr_results],
            "ocr_unresolved_page_numbers": unresolved_pages,
            "ocr_mean_confidence": (
                round(sum(confidences) / len(confidences), 1)
                if confidences else None
            ),
            "ocr_page_results": [
                {
                    "page_number": result.page_number,
                    "text_char_count": len(result.text),
                    "confidence": result.confidence,
                }
                for result in ocr_results
            ],
            "ocr_error": ocr_error,
            "pdf_table_extraction_status": table_status,
            "pdf_table_count": len(tables),
            "pdf_table_error": table_error,
        },
        requires_ocr=requires_ocr,
        # Preserve the established scanner contract.  The exact OCR runtime
        # state is available in metadata["ocr_status"].
        unreadable_reason="PDF_TEXT_BELOW_OCR_THRESHOLD" if requires_ocr else None,
    )
