from __future__ import annotations

import re
import unicodedata
from typing import Any


_CORPORATE_MARKERS = re.compile(r"(?:\(\s*주\s*\)|주식회사)", re.IGNORECASE)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).lower().strip()
    return re.sub(r"\s+", " ", text)


def normalize_canonical_value(value: Any) -> str:
    """Lightweight canonicalization from plan section 10; deliberately not fuzzy."""
    text = _CORPORATE_MARKERS.sub("", normalize_text(value))
    return "".join(character for character in text if character.isalnum())


def char_ngram_tokens(text: str) -> list[str]:
    compact = "".join(character for character in normalize_text(text) if character.isalnum())
    return [compact[index : index + n] for n in (2, 3) for index in range(max(0, len(compact) - n + 1))]
