#!/usr/bin/env python3
"""Compatibility alias for the canonical Ceiling integrity validator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import validate_ceiling_benchmark as base


def validate_ceiling_benchmark(root: Path = base.ROOT) -> dict[str, Any]:
    return base.validate_ceiling_benchmark(root)
