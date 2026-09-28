"""Estimate the spoken duration of the quoted main demo script."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs" / "DEMO_SCRIPT.md"


def main() -> None:
    text = SCRIPT.read_text(encoding="utf-8").split("## 예상 질문", 1)[0]
    spoken_blocks = re.findall(r"“(.*?)”", text, flags=re.DOTALL)
    spoken = " ".join(" ".join(block.split()) for block in spoken_blocks)
    characters = len(spoken)
    payload = {
        "spoken_blocks": len(spoken_blocks),
        "characters_with_spaces": characters,
        "seconds_at_300_characters_per_minute": round(characters / 300 * 60),
        "seconds_at_330_characters_per_minute": round(characters / 330 * 60),
        "target_seconds": 180,
    }
    for key, value in payload.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
