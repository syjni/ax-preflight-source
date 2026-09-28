from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.assemble_ceiling_dataset import generate_ceiling_dataset
from scripts.validate_ceiling_dataset import validate_ceiling_benchmark


class CeilingControlProtectionTests(unittest.TestCase):
    def test_control_hash_baselines_prove_future_injection_can_protect_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate_ceiling_dataset(root)
            validation = validate_ceiling_benchmark(root)
        check = next(item for item in validation["checks"] if item["name"] == "control_source_hash_and_family_protection")
        self.assertTrue(check["passed"], check["detail"])
        self.assertEqual(check["detail"]["protected_source_count"], 4)


if __name__ == "__main__":
    unittest.main()
