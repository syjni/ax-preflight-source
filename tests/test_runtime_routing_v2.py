from __future__ import annotations

import json
import os
import unittest
from datetime import datetime
from pathlib import Path

from ax_mcp.runtime_dataset import resolve_runtime_dataset, runtime_identity
from scripts.generate_before_variants import _copy_and_transform, verify_deterministic
from scripts.runtime_binding import resolve_runtime_binding
from scripts.validate_runtime_routing import validate_routing


ROOT = Path(__file__).resolve().parents[1]


def test_before_copy_uses_frozen_scan_time_instead_of_archive_time(tmp_path: Path) -> None:
    ceiling = tmp_path / "ceiling"
    target = tmp_path / "before"
    source = ceiling / "policy.txt"
    source.parent.mkdir(parents=True)
    source.write_text("current policy", encoding="utf-8")
    archive_time_ns = 1_800_000_000_000_000_000
    os.utime(source, ns=(archive_time_ns, archive_time_ns))
    frozen_time = "2026-09-21T00:00:00Z"

    _copy_and_transform(
        ceiling,
        target,
        ["policy.txt"],
        {"files": [{"relative_path": "policy.txt", "modified_at": frozen_time}]},
    )

    expected_ns = int(
        datetime.fromisoformat(frozen_time.replace("Z", "+00:00")).timestamp()
        * 1_000_000_000
    )
    copied_stat = (target / "policy.txt").stat()
    assert copied_stat.st_mtime_ns == expected_ns


class RuntimeRoutingV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bindings = json.loads((ROOT / "task_runtime_bindings.json").read_text(encoding="utf-8"))
        cls.spec = json.loads((ROOT / "DEFECT_INJECTION_SPEC_V2.json").read_text(encoding="utf-8"))
        cls.entries = {entry["task_id"]: entry for entry in cls.bindings["bindings"]}

    def test_all_16_tasks_have_before_and_ceiling_bindings(self) -> None:
        self.assertEqual(len(self.entries), 16)
        for entry in self.entries.values():
            self.assertEqual(set(entry["runtime_profiles"]), {"Before", "Ceiling"})
            self.assertEqual(entry["runtime_profiles"]["Ceiling"], "ceiling")

    def test_treated_and_control_semantics_are_pre_registered(self) -> None:
        treated = [entry for entry in self.entries.values() if entry["task_group"] == "treated"]
        controls = [entry for entry in self.entries.values() if entry["task_group"] == "control"]
        self.assertEqual(len(treated), 12)
        self.assertEqual(len(controls), 4)
        for entry in treated:
            self.assertNotEqual(entry["runtime_profiles"]["Before"], "ceiling")
            self.assertIsNotNone(entry["defect_variant_id"])
        for entry in controls:
            self.assertEqual(entry["runtime_profiles"]["Before"], "ceiling")
            self.assertIsNone(entry["defect_variant_id"])

    def test_treated_bindings_match_frozen_task_to_defect_sources(self) -> None:
        frozen = json.loads((ROOT / "task_to_defect_manifest.json").read_text(encoding="utf-8"))
        frozen_by_task = {entry["task_id"]: entry for entry in frozen["task_defects"]}
        variants = {item["variant_id"]: item for item in self.spec["variants"]}
        for task_id, binding in self.entries.items():
            if binding["task_group"] != "treated":
                continue
            self.assertEqual(
                sorted(variants[binding["defect_variant_id"]]["affected_sources"]),
                sorted(frozen_by_task[task_id]["affected_sources"]),
            )

    def test_control_before_and_ceiling_runtime_identities_are_equal(self) -> None:
        for task_id, entry in self.entries.items():
            if entry["task_group"] != "control":
                continue
            before = resolve_runtime_binding(task_id, "Before")
            ceiling = resolve_runtime_binding(task_id, "Ceiling")
            self.assertEqual(before.runtime_profile, ceiling.runtime_profile)
            self.assertEqual(
                runtime_identity(resolve_runtime_dataset(before.runtime_profile)),
                runtime_identity(resolve_runtime_dataset(ceiling.runtime_profile)),
            )

    def test_ceiling_runtime_identity_is_exactly_v1(self) -> None:
        frozen = json.loads((ROOT / "experiment/frozen/ax-exp-v1-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime_identity(resolve_runtime_dataset("ceiling")), frozen["ceiling_runtime_identity"])

    def test_all_variant_receipts_prove_intended_only_readiness_change(self) -> None:
        self.assertEqual(len(self.spec["variants"]), 8)
        for variant in self.spec["variants"]:
            receipt = json.loads((ROOT / variant["diff_receipt"]).read_text(encoding="utf-8"))
            self.assertTrue(all(receipt["checks"].values()), receipt)
            dimensions = receipt["readiness"]["dimension_diff"]
            changed = {name for name, values in dimensions.items() if values["before"] != values["ceiling"]}
            self.assertEqual(changed, {"accessibility"})

    def test_static_routing_invariants_check_all_32_routes(self) -> None:
        result = validate_routing(ROOT)
        # The execution-count check is a pre-run guard, not a static routing invariant.
        self.assertIn("held_out_execution_count_zero", result["invariant_checks"])
        static_invariants = {
            name: passed
            for name, passed in result["invariant_checks"].items()
            if name != "held_out_execution_count_zero"
        }
        self.assertTrue(all(static_invariants.values()), static_invariants)
        self.assertEqual(result["summary"]["before_bindings"], 16)
        self.assertEqual(result["summary"]["ceiling_bindings"], 16)
        self.assertEqual(result["summary"]["runtime_identity_mismatches"], 0)
        self.assertEqual(result["summary"]["leakage_violations"], 0)
        self.assertEqual(len(result["routes"]), 32)

    @unittest.skipUnless(
        os.name == "nt",
        "frozen ax-exp-v2 regeneration preserves its original Windows path order",
    )
    def test_before_generation_is_byte_deterministic(self) -> None:
        registry_before = (ROOT / "runtime_datasets.json").read_bytes()
        result = verify_deterministic(ROOT)
        self.assertTrue(result["passed"], result)
        self.assertEqual((ROOT / "runtime_datasets.json").read_bytes(), registry_before)


if __name__ == "__main__":
    unittest.main()
