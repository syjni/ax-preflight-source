#!/usr/bin/env python3
"""Canonical Ceiling integrity validator entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import validate_ceiling_benchmark as base


def validate_ceiling_benchmark(root: Path = base.ROOT) -> dict[str, Any]:
    return base.validate_ceiling_benchmark(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate canonical AX Ceiling integrity artifacts")
    parser.add_argument("--root", type=Path, default=base.ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_ceiling_benchmark(args.root)
    output = args.output or (args.root / "ceiling_validation.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "passed": result["passed"]}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
