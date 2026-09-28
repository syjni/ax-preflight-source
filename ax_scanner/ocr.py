"""Optional local OCR support for scanned PDF pages.

The Python dependencies are portable, while the Tesseract executable is an
explicit runtime capability.  Missing OCR never makes a folder scan fail: the
PDF parser reports the exact capability state so the product can offer the
reviewer a next action.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class OcrCapability:
    available: bool
    engine: str | None
    languages: tuple[str, ...]
    reason: str | None = None


@dataclass(frozen=True)
class OcrPageResult:
    page_number: int
    text: str
    confidence: float | None


@lru_cache(maxsize=1)
def detect_ocr_capability() -> OcrCapability:
    try:
        import pytesseract

        version = str(pytesseract.get_tesseract_version()).splitlines()[0]
        languages = tuple(sorted(pytesseract.get_languages(config="")))
    except Exception as exc:  # executable/package availability is environmental
        return OcrCapability(
            available=False,
            engine=None,
            languages=(),
            reason=f"{type(exc).__name__}: {str(exc)[:240]}",
        )
    if not any(language != "osd" for language in languages):
        return OcrCapability(
            available=False,
            engine=f"Tesseract {version}",
            languages=languages,
            reason="Tesseract has no text recognition language data installed",
        )
    return OcrCapability(
        available=True,
        engine=f"Tesseract {version}",
        languages=languages,
    )


def preferred_ocr_language(languages: Iterable[str]) -> str:
    available = set(languages)
    preferred = [language for language in ("kor", "eng") if language in available]
    if preferred:
        return "+".join(preferred)
    alternatives = sorted(language for language in available if language != "osd")
    return alternatives[0] if alternatives else "eng"


def ocr_pdf_pages(
    path: Path,
    page_numbers: list[int],
    *,
    language: str,
    dpi: int = 200,
) -> list[OcrPageResult]:
    """Render and OCR selected one-based PDF pages without changing the PDF."""
    import fitz
    import pytesseract
    from PIL import Image

    results: list[OcrPageResult] = []
    scale = dpi / 72
    with fitz.open(path) as document:
        for page_number in page_numbers:
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB
            )
            with Image.open(BytesIO(pixmap.tobytes("png"))) as image:
                data = pytesseract.image_to_data(
                    image,
                    lang=language,
                    output_type=pytesseract.Output.DICT,
                    config="--psm 6",
                )
            lines: dict[tuple[int, int, int], list[str]] = {}
            confidences: list[float] = []
            for index, raw_text in enumerate(data.get("text", [])):
                token = str(raw_text).strip()
                if not token:
                    continue
                key = (
                    int(data["block_num"][index]),
                    int(data["par_num"][index]),
                    int(data["line_num"][index]),
                )
                lines.setdefault(key, []).append(token)
                try:
                    confidence = float(data["conf"][index])
                except (KeyError, TypeError, ValueError):
                    continue
                if confidence >= 0:
                    confidences.append(confidence)
            text = "\n".join(" ".join(tokens) for tokens in lines.values())
            results.append(OcrPageResult(
                page_number=page_number,
                text=text,
                confidence=(
                    round(sum(confidences) / len(confidences), 1)
                    if confidences else None
                ),
            ))
    return results
