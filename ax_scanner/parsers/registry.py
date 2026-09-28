from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .base import ParsedContent
from .docx import parse_docx
from .pdf import parse_pdf
from .tabular import parse_csv, parse_xlsx
from .text import parse_txt


Parser = Callable[..., ParsedContent]

PARSERS: dict[str, Parser] = {
    ".txt": parse_txt,
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".csv": parse_csv,
    ".xlsx": parse_xlsx,
}
SUPPORTED_EXTENSIONS = tuple(PARSERS)
PDF_ENHANCEMENTS_ENV = "AX_SCANNER_PDF_ENHANCEMENTS"


def parse_file(
    path: Path,
    file_id: str,
    *,
    ocr_min_chars_per_page: int = 20,
    pdf_enhancements: bool | None = None,
) -> ParsedContent:
    extension = path.suffix.lower()
    if extension not in PARSERS:
        raise KeyError(extension)
    enhancements = (
        os.environ.get(PDF_ENHANCEMENTS_ENV, "on").strip().casefold() != "off"
        if pdf_enhancements is None else pdf_enhancements
    )
    return PARSERS[extension](
        path,
        file_id,
        ocr_min_chars_per_page=ocr_min_chars_per_page,
        pdf_enhancements=enhancements,
    )
