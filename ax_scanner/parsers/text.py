from __future__ import annotations

from pathlib import Path

from .base import ParsedContent


def parse_txt(path: Path, file_id: str, **_: object) -> ParsedContent:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return ParsedContent(parser="txt", text=path.read_text(encoding=encoding), metadata={"encoding": encoding})
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"Unable to decode text file with utf-8 or cp949: {last_error}")

