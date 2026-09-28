from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ax_scanner.models import TableProfile


@dataclass
class ParsedContent:
    parser: str
    text: str = ""
    tables: list[TableProfile] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    requires_ocr: bool = False
    unreadable_reason: str | None = None

