from __future__ import annotations

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


def parse_file(path: Path, file_id: str, *, ocr_min_chars_per_page: int = 20) -> ParsedContent:
    extension = path.suffix.lower()
    if extension not in PARSERS:
        raise KeyError(extension)
    return PARSERS[extension](path, file_id, ocr_min_chars_per_page=ocr_min_chars_per_page)

