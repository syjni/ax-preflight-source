from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.assemble_ceiling_dataset import generate_ceiling_dataset


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


class CanonicalCeilingRegenerationTests(unittest.TestCase):
    def test_canonical_generation_is_byte_deterministic_including_control_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            first = parent / "first"
            second = parent / "second"
            generate_ceiling_dataset(first)
            generate_ceiling_dataset(second)
            self.assertEqual(_hashes(first), _hashes(second))


if __name__ == "__main__":
    unittest.main()
