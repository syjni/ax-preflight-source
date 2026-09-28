from __future__ import annotations

import argparse
import json
from pathlib import Path

from .blind_gate import ROOT, prepare_blind_gate, validate_blind_gate


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or validate the blind Kiro runtime gate")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--prepare", action="store_true", help="freeze inputs and create NOT_RUN gate artifacts")
    args = parser.parse_args()
    result = prepare_blind_gate(args.root) if args.prepare else validate_blind_gate(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

