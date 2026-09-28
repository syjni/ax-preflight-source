from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from portable_path_order import frozen_sorted_files
from scripts.verify_phase6_demo_v2 import verify_phase6_demo_v2
from scripts.verify_phase6_demo_v3 import (
    create_phase6_demo_v3,
    verify_phase6_demo_v3,
)


ROOT = Path(__file__).resolve().parents[1]
V2_ROOT = ROOT / "artifacts/phase6_product_demo_v2"
V3_ROOT = ROOT / "artifacts/phase6_product_demo_v3"
V3_MANIFEST = V3_ROOT / "FROZEN_MANIFEST.v3.json"


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in frozen_sorted_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class Phase6ProductDemoV3Tests(unittest.TestCase):
    def test_v2_and_v3_verifiers_pass_together(self) -> None:
        before = tree_hash(V2_ROOT)
        self.assertTrue(verify_phase6_demo_v2(root=ROOT)["passed"])
        result = verify_phase6_demo_v3(root=ROOT)
        self.assertTrue(result["passed"])
        self.assertEqual(result["combined_run_count"], 26)
        self.assertEqual(result["portfolio_run_count"], 20)
        self.assertEqual(result["before_processable_task_count"], 6)
        self.assertEqual(result["before_blocked_task_count"], 4)
        self.assertEqual(result["after_processable_task_count"], 8)
        self.assertEqual(result["after_blocked_task_count"], 2)
        self.assertEqual(tree_hash(V2_ROOT), before)

    def test_v3_manifest_and_summary_are_portable(self) -> None:
        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "ax-phase6-product-demo-freeze-v3")
        self.assertEqual(manifest["combined_run_count"], 26)
        for path in (V3_MANIFEST, V3_ROOT / "SUMMARY.json", V3_ROOT / "STATIC_COMPARISON.json"):
            serialized = path.read_text(encoding="utf-8")
            self.assertNotIn("C:\\", serialized)
            self.assertNotIn("/Users/", serialized)
            self.assertNotIn("/home/", serialized)
            self.assertNotIn("ye" + "on5", serialized.casefold())

    def test_v3_is_write_once(self) -> None:
        before_v2 = tree_hash(V2_ROOT)
        before_v3 = tree_hash(V3_ROOT)
        with self.assertRaises(FileExistsError):
            create_phase6_demo_v3(root=ROOT)
        self.assertEqual(tree_hash(V2_ROOT), before_v2)
        self.assertEqual(tree_hash(V3_ROOT), before_v3)


if __name__ == "__main__":
    unittest.main()
