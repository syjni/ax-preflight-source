from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from portable_path_order import frozen_sorted_files
from scripts.verify_phase6_demo import verify_phase6_demo
from scripts.verify_phase6_demo_v2 import (
    create_phase6_demo_v2,
    verify_phase6_demo_v2,
)


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT / "artifacts/phase6_product_demo"
V2_ROOT = ROOT / "artifacts/phase6_product_demo_v2"
V1_MANIFEST = V1_ROOT / "FROZEN_MANIFEST.json"
V2_MANIFEST = V2_ROOT / "FROZEN_MANIFEST.v2.json"


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in frozen_sorted_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class Phase6ProductDemoV2Tests(unittest.TestCase):
    def test_v1_and_v2_verifiers_pass_together(self) -> None:
        before = tree_hash(V1_ROOT)
        self.assertTrue(verify_phase6_demo(root=ROOT)["passed"])
        result = verify_phase6_demo_v2(root=ROOT)
        self.assertTrue(result["passed"])
        self.assertEqual(result["after_direct_match_count"], 3)
        self.assertEqual(result["before_unconfirmed_count"], 3)
        self.assertEqual(result["changed_evidence_count"], 2)
        self.assertEqual(tree_hash(V1_ROOT), before)

    def test_v2_manifest_is_parent_bound_and_contains_only_portable_paths(self) -> None:
        manifest = json.loads(V2_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["parent_manifest_sha256"],
            hashlib.sha256(V1_MANIFEST.read_bytes()).hexdigest(),
        )
        self.assertEqual(manifest["summary"]["after_direct_match_count"], 3)
        self.assertEqual(manifest["summary"]["changed_evidence_count"], 2)
        serialized = V2_MANIFEST.read_text(encoding="utf-8")
        self.assertNotIn("C:\\", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("ye" + "on5", serialized.casefold())

    def test_v2_is_write_once(self) -> None:
        before_v1 = tree_hash(V1_ROOT)
        before_v2 = tree_hash(V2_ROOT)
        with self.assertRaises(FileExistsError):
            create_phase6_demo_v2(root=ROOT)
        self.assertEqual(tree_hash(V1_ROOT), before_v1)
        self.assertEqual(tree_hash(V2_ROOT), before_v2)


if __name__ == "__main__":
    unittest.main()
