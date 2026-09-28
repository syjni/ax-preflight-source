#!/usr/bin/env python3
"""Compatibility entry point for the canonical Ceiling generator.

No benchmark-specific runtime hint or extra workbook sheet is added here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import generate_ceiling_dataset as base


def generate_ceiling_dataset(output_root: Path = base.ROOT) -> dict[str, Path]:
    return base.generate_ceiling_dataset(output_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the canonical deterministic AX Ceiling dataset")
    parser.add_argument("--output-root", type=Path, default=base.ROOT)
    args = parser.parse_args()
    paths = generate_ceiling_dataset(args.output_root)
    print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
