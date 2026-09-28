"""Verify Phase 5 did not mutate frozen v5, ax-evaluation, or readiness v1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiment/frozen/ax-exp-v5-manifest.json"
OUTPUT = ROOT / "artifacts/phase5_evidence_checker_v1/FROZEN_HASH_VERIFICATION.json"
EXPECTED = {
    ".kiro/agents/ax-evaluation.json": "7977a1da0361a54f9be5d2b3bb91c25b7944e9185403b72f767c0806b5f61844",
    "EXPERIMENT_FREEZE.md": "1ccc0a68467e504772123a541f417132c08584d842a1829e0b3f3c230fa17fb2",
    "EXPERIMENT_FREEZE_V2.md": "461db1416b26520751acfa8f71d2e5f9481bf1a01d4fa41f3a59fff72f94c27f",
    "EXPERIMENT_FREEZE_V3.md": "def640a190f1cc31fec5e526c6d8991484bfe258eb2250c672141eb146d1a5eb",
    "readiness_score.py": "5b3dd7e7b94d230b855981f1b487b35efc655ed11a3d84d02be7278ba3fc8319",
    "READINESS_SCORE_SPEC.md": "4212c2314136f3c42b828717588e01952d882e392feb9f37e41558438cc07c44",
    "experiment/frozen/ax-exp-v1-manifest.json": "3202f9df178f07610b09f9a4cb318c0da0b63653e81f9a7f1cc8b6fd62f4d358",
    "experiment/frozen/ax-exp-v2-manifest.json": "b4531692548dea5d53b2cf1639e170dc659797548a29289d99d2f9a94c9c8c42",
    "experiment/frozen/ax-exp-v3-manifest.json": "57225746fdd1b6cc3682896026e0bd82171d57d0d0f33523e3e7791f72cf5a69",
    "experiment/frozen/ax-exp-v4-manifest.json": "9189c846389dd39659a8eb53a4fe42d1717c1275b52d3ab7e871d1838485589c",
    "experiment/frozen/ax-exp-v5-manifest.json": "18decb9ba3a073edde09c4de5cd08d4df04f21935ae819c6d7f2a9de03c2e06c",
    "artifacts/heldout_ax-exp-v5/RESULTS.md": "81de289a0bf44e5978bd4477d5d5b46d0c48b4e655dbef1695bab49aa3090793",
    "artifacts/heldout_ax-exp-v5/ANALYSIS.json": "6ca03c0ee22e3fc596604066cf012cfa9118350186191ca30be11fd5ac5d7d9c",
    "artifacts/heldout_ax-exp-v5/AUDIT.json": "2896939025a23179c95eb1e04f72ed1f768541eb78d6fbc2cc890312dcc65ebd",
    "artifacts/heldout_ax-exp-v5/PROGRESS.md": "56d706eee785b327cbd191eee5c1f12009346a6c31aaf09d6eee53d5724f6639",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = dict(EXPECTED)
    for item in (*manifest["dataset_files"], *manifest["frozen_files"]):
        expected[item["path"]] = item["sha256"]
    checks = []
    for relative, expected_sha in sorted(expected.items()):
        path = ROOT / relative
        actual = sha(path) if path.is_file() else None
        checks.append({
            "path": relative, "expected_sha256": expected_sha,
            "actual_sha256": actual, "match": actual == expected_sha,
        })
    payload = {
        "schema_version": "ax-phase5-preservation-check-v1",
        "hash_algorithm": "SHA-256", "passed": all(item["match"] for item in checks),
        "checked_files": len(checks), "mismatches": [item for item in checks if not item["match"]],
        "checks": checks,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(json.dumps({
        "passed": payload["passed"], "checked_files": len(checks),
        "mismatch_count": len(payload["mismatches"]),
    }))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
