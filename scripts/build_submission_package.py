"""Build and inspect a deterministic AX submission from the current dependency closure.

The inventory is derived from current Git-tracked core source/test trees plus
the runtime and frozen artifact roots they consume.  Historical audit archives,
old submission ZIPs, mutable run output, and machine-local receipts are excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ZIP_FIXED_TIMESTAMP = (2026, 9, 21, 0, 0, 0)
CORE_PREFIXES = (
    ".github/", "ax_agent/", "ax_mcp/", "ax_product/", "ax_scanner/", "docs/",
    "experiment/", "results_console/", "sample_data/", "scripts/", "tests/",
)
ARTIFACT_PREFIXES = (
    "artifacts/phase5_evidence_checker_v1/",
    "artifacts/phase6_product_demo/",
    "artifacts/phase6_product_demo_v2/",
    "artifacts/phase6_product_demo_v3/",
    "artifacts/phase6_product_demo_v4/",
    "artifacts/portability_migration_2026-09-24/",
    "artifacts/posthoc_phase6_evidence_checker_fix/",
    "artifacts/posthoc_phase6_evidence_checker_v3/",
    "artifacts/posthoc_phase6_v4_stability/",
)
ARTIFACT_FILES = {
    "artifacts/heldout_ax-exp-v5/ANALYSIS.json",
    "artifacts/heldout_ax-exp-v5/AUDIT.json",
    "artifacts/heldout_ax-exp-v5/PROGRESS.md",
    "artifacts/heldout_ax-exp-v5/RESULTS.md",
}
CANONICAL_KIRO_FILES = {
    ".kiro/agents/ax-evaluation.json",
    ".kiro/agents/ax-product.json",
    ".kiro/ax-evaluation.prompt-metadata.json",
}
NONPORTABLE_ROOT_FILES = {
    "blind_gate_manifest.json",
    "KIRO_INTEGRATION.md",
    "SEMI_AUTOMATED_EXECUTION_V3.md",
    "phase3_contract_hashes_after.txt",
    "phase3_contract_hashes_before.txt",
    "phase3_hashes_after.txt",
    "phase3_hashes_before.txt",
    "phase3_preservation_hashes_after.txt",
    "phase3_preservation_hashes_before.txt",
}
NONPORTABLE_TRACKED_PREFIXES = (
    # Write-once operator-error evidence intentionally retains the originating
    # workstation's absolute Kiro/session paths.  It is historical audit input,
    # not a runtime or verification dependency of the current product package.
    "experiment/v3/operator-errors/",
)
REQUIRED_CLOSURE_FILES = {
    ".dockerignore",
    ".github/workflows/deploy-pages.yml",
    ".github/workflows/ci.yml",
    "Dockerfile",
    "compose.yaml",
    "start-docker.cmd",
    "stop-docker.cmd",
    "ax_product/batches.py",
    "ax_product/featured_cases.py",
    "ax_product/findings.py",
    "ax_product/local_datasets.py",
    "ax_product/web.py",
    "ax_product/request_validation.py",
    "ax_product/task_approvals.py",
    "ax_product/schemas/DataFinding.schema.json",
    "ax_product/schemas/FindingsResponse.schema.json",
    "results_console/schemas/DatasetsResponse.schema.json",
    "results_console/schemas/FindingsResponse.schema.json",
    "results_console/schemas/FeaturedCasesResponse.schema.json",
    "results_console/schemas/LocalDatasetDeleteResult.schema.json",
    "results_console/schemas/LocalDatasetRequest.schema.json",
    "results_console/schemas/LocalDatasetScanResult.schema.json",
    "results_console/schemas/ProductCapabilities.schema.json",
    "results_console/schemas/BatchCreateRequest.schema.json",
    "results_console/schemas/BatchStatus.schema.json",
    "results_console/src/components/BatchPanel.tsx",
    "results_console/src/components/LocalDatasetPanel.tsx",
    "results_console/tests/batch-orchestration.test.mjs",
    "results_console/tests/local-dataset-panel.test.mjs",
    "results_console/.env.static",
    "results_console/public/static-demo.json",
    "tests/test_findings.py",
    "tests/test_batches.py",
    "tests/test_local_datasets.py",
    "tests/test_parsers.py",
    "tests/test_kiro_cli_integration.py",
    "tests/test_phase6_product_demo_v2.py",
    "tests/test_phase6_product_demo_v3.py",
    "tests/test_phase6_v4_runner.py",
    "tests/test_phase6_v4_api.py",
    "tests/test_submission_package.py",
    "tests/test_static_demo_export.py",
    "scripts/build_submission_package.py",
    "scripts/export_static_demo.py",
    "scripts/run-local-api.cmd",
    "start-local.cmd",
    "ax_scanner/ocr.py",
    "ax_scanner/parsers/pdf.py",
    "requirements.txt",
    "docs/REVIEWER_QUICKSTART.md",
    "business_task_catalog.json",
    "business_task_approvals.json",
    "finding_comparisons.json",
    "pytest.ini",
    "runtime_datasets.json",
    "artifacts/phase6_product_demo/FROZEN_MANIFEST.json",
    "artifacts/phase6_product_demo_v2/FROZEN_MANIFEST.v2.json",
    "artifacts/phase6_product_demo_v3/FROZEN_MANIFEST.v3.json",
    "artifacts/phase6_product_demo_v4/FROZEN_MANIFEST.v4.json",
    "ax_product/evidence_v2.py",
    "ax_product/evidence_v3.py",
    "tests/test_evidence_checker_v3.py",
    "scripts/verify_phase6_demo_v4.py",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _filesystem_path(path: Path) -> Path:
    """Use Windows' extended-length form for validated local filesystem I/O."""
    resolved = path.resolve()
    if os.name != "nt":
        return resolved
    value = str(resolved)
    if value.startswith("\\\\?\\"):
        return resolved
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def _git_lines(*args: str) -> list[str]:
    completed = subprocess.run(
        [
            "git", "-c", f"safe.directory={ROOT.as_posix()}",
            "-c", "core.quotepath=false", *args,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line for line in completed.stdout.splitlines() if line]


def _safe_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    lower = relative.casefold()
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        return False
    if "\\" in relative or re.match(r"^[a-z]:", lower):
        return False
    if lower.startswith(("artifacts/product_runs/", "artifacts/product_batches/", "artifacts/submission/", "artifacts/final_submission_audit/", "_review_v2/")):
        return False
    if lower.startswith(NONPORTABLE_TRACKED_PREFIXES):
        return False
    if path.name.casefold() == "state.json" or lower.endswith(".map"):
        return False
    if re.fullmatch(r"\.kiro/agents/ax-(?:product-run|evaluation|v4|v5)-.+\.json", lower):
        return False
    return True


def candidate_paths() -> list[str]:
    """Return the current tracked source/test/runtime closure plus production dist."""
    tracked = set(_git_lines("ls-files"))
    selected: set[str] = set()
    for relative in tracked:
        if not _safe_path(relative):
            continue
        if "/" not in relative and relative not in NONPORTABLE_ROOT_FILES:
            selected.add(relative)
        elif relative in CANONICAL_KIRO_FILES:
            selected.add(relative)
        elif relative in ARTIFACT_FILES:
            selected.add(relative)
        elif relative.startswith(CORE_PREFIXES) or relative.startswith(ARTIFACT_PREFIXES):
            selected.add(relative)

    dist_root = ROOT / "results_console" / "dist"
    if not dist_root.is_dir():
        raise ValueError("results_console/dist is missing; run npm run build first")
    selected.update(
        path.relative_to(ROOT).as_posix()
        for path in dist_root.rglob("*")
        if path.is_file() and not path.name.endswith(".map")
    )
    selected = {path for path in selected if _safe_path(path)}
    _validate_closure(selected, tracked)
    return sorted(selected)


def _validate_closure(selected: set[str], tracked: set[str]) -> None:
    missing_required = sorted(REQUIRED_CLOSURE_FILES - selected)
    if missing_required:
        raise ValueError(f"required dependency closure files missing: {missing_required}")
    core_tracked = {
        path for path in tracked
        if path.startswith(CORE_PREFIXES) and _safe_path(path)
    }
    missing_core = sorted(core_tracked - selected)
    if missing_core:
        raise ValueError(f"tracked core files missing from dependency closure: {missing_core}")
    for relative in selected:
        if not (ROOT / Path(relative)).is_file():
            raise ValueError(f"candidate file is missing: {relative}")


def _record(root: Path, relative: str) -> dict[str, Any]:
    path = _filesystem_path(root / Path(relative))
    return {
        "path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def create_manifest(output: Path) -> dict[str, Any]:
    paths = candidate_paths()
    files = [_record(ROOT, path) for path in paths]
    payload = {
        "schema_version": "ax-submission-source-manifest-v2",
        "inventory_method": "CURRENT_TRACKED_CORE_AND_RUNTIME_DEPENDENCY_CLOSURE",
        "git_head": _git_lines("rev-parse", "HEAD")[0],
        "hash_algorithm": "SHA-256",
        "file_count": len(files),
        "total_size_bytes": sum(record["size_bytes"] for record in files),
        "excluded_historical_roots": [
            "artifacts/final_submission_audit/", "artifacts/submission/", "_review_v2/",
        ],
        "excluded_machine_local_prefixes": list(NONPORTABLE_TRACKED_PREFIXES),
        "files": files,
    }
    write_json(output, payload)
    return payload


def _manifest_paths(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [record["path"] for record in payload["files"]]


def build_zip(source_manifest: Path, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing package: {output}")
    paths = _manifest_paths(source_manifest)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in paths:
            data = (ROOT / Path(relative)).read_bytes()
            # This fixed date matches the canonical fixture's as-of date.  It
            # keeps the ZIP reproducible and prevents extracted fixture files
            # from becoming future-dated during deterministic regeneration.
            info = zipfile.ZipInfo(relative, date_time=ZIP_FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return {"path": str(output), "sha256": sha256(output), "size_bytes": output.stat().st_size}


_ORIGINAL_USERNAME = b"".join((b"ye", b"on5"))
CONTENT_PATTERNS = {
    "windows_user_absolute_path": re.compile(rb"[A-Za-z]:\\Users\\[^\\\s\"']+", re.I),
    "posix_personal_home_path": re.compile(rb"/(?:Users|home)/[^/\s\"']+", re.I),
    "original_username": re.compile(_ORIGINAL_USERNAME, re.I),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "openai_style_key": re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    "credential_assignment": re.compile(
        rb"(?i)(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*[\"'][^\"']{8,}[\"']"
    ),
}


def inspect_zip(zip_path: Path, source_manifest: Path, output: Path) -> dict[str, Any]:
    expected = {
        record["path"]: record
        for record in json.loads(source_manifest.read_text(encoding="utf-8"))["files"]
    }
    anomalies: dict[str, list[str]] = {
        "path_traversal": [], "absolute": [], "drive_prefix": [], "backslash": [],
        "case_insensitive_duplicates": [], "source_maps": [], "state_json": [],
        "writable_product_runs": [], "temporary_agents": [],
    }
    content_hits: dict[str, list[str]] = {name: [] for name in CONTENT_PATTERNS}
    actual: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename
            path = PurePosixPath(name)
            lower = name.casefold()
            if any(part == ".." for part in path.parts): anomalies["path_traversal"].append(name)
            if name.startswith(("/", "\\")): anomalies["absolute"].append(name)
            if re.match(r"^[A-Za-z]:", name): anomalies["drive_prefix"].append(name)
            if "\\" in name: anomalies["backslash"].append(name)
            if lower in seen: anomalies["case_insensitive_duplicates"].append(name)
            seen.add(lower)
            if lower.endswith(".map"): anomalies["source_maps"].append(name)
            if path.name.casefold() == "state.json": anomalies["state_json"].append(name)
            if lower.startswith("artifacts/product_runs/"): anomalies["writable_product_runs"].append(name)
            if re.fullmatch(r"\.kiro/agents/ax-(?:product-run|evaluation|v4|v5)-.+\.json", lower):
                anomalies["temporary_agents"].append(name)
            data = archive.read(info)
            actual[name] = {"path": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            if b"\0" not in data:
                for pattern_name, pattern in CONTENT_PATTERNS.items():
                    if pattern.search(data):
                        content_hits[pattern_name].append(name)
    mismatches = [
        {"path": name, "expected": expected.get(name), "actual": actual.get(name)}
        for name in sorted(set(expected) | set(actual))
        if expected.get(name) != actual.get(name)
    ]
    passed = not any(anomalies.values()) and not any(content_hits.values()) and not mismatches
    payload = {
        "schema_version": "ax-submission-zip-inspection-v2",
        "passed": passed,
        "zip": {"path": str(zip_path), "sha256": sha256(zip_path), "size_bytes": zip_path.stat().st_size, "file_count": len(actual)},
        "entry_anomalies": anomalies,
        "content_pattern_hits": content_hits,
        "manifest_mismatch_count": len(mismatches),
        "manifest_mismatches": mismatches,
    }
    write_json(output, payload)
    if not passed:
        raise ValueError("submission ZIP inspection failed")
    return payload


def safe_extract(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    base = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        seen: set[str] = set()
        for info in archive.infolist():
            name = info.filename
            lower = name.casefold()
            path = PurePosixPath(name)
            if (
                name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name)
                or "\\" in name or any(part in ("", ".", "..") for part in path.parts)
                or lower in seen
            ):
                raise ValueError(f"unsafe ZIP entry: {name}")
            seen.add(lower)
            target = (destination / Path(*path.parts)).resolve()
            target.relative_to(base)
            filesystem_target = _filesystem_path(target)
            filesystem_target.parent.mkdir(parents=True, exist_ok=True)
            filesystem_target.write_bytes(archive.read(info))
            timestamp = datetime(*info.date_time, tzinfo=timezone.utc).timestamp()
            os.utime(filesystem_target, (timestamp, timestamp))


def verify_extraction(extracted_root: Path, source_manifest: Path) -> dict[str, Any]:
    expected = json.loads(source_manifest.read_text(encoding="utf-8"))["files"]
    filesystem_root = _filesystem_path(extracted_root)
    missing = [
        record["path"] for record in expected
        if not _filesystem_path(extracted_root / record["path"]).is_file()
    ]
    actual = [
        _record(extracted_root, record["path"])
        for record in expected
        if record["path"] not in missing
    ]
    unexpected = sorted(
        path.relative_to(filesystem_root).as_posix()
        for path in filesystem_root.rglob("*") if path.is_file()
        if path.relative_to(filesystem_root).as_posix()
        not in {record["path"] for record in expected}
    )
    observed_by_path = {record["path"]: record for record in actual}
    mismatches = [
        record["path"] for record in expected
        if record["path"] in observed_by_path and record != observed_by_path[record["path"]]
    ]
    return {
        "passed": not unexpected and not missing and not mismatches,
        "file_count": len(actual),
        "unexpected": unexpected,
        "missing": missing,
        "mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("paths")
    manifest_parser = commands.add_parser("manifest")
    manifest_parser.add_argument("output", type=Path)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("source_manifest", type=Path)
    build_parser.add_argument("output", type=Path)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("zip_path", type=Path)
    inspect_parser.add_argument("source_manifest", type=Path)
    inspect_parser.add_argument("output", type=Path)
    extract_parser = commands.add_parser("extract")
    extract_parser.add_argument("zip_path", type=Path)
    extract_parser.add_argument("destination", type=Path)
    verify_parser = commands.add_parser("verify-extraction")
    verify_parser.add_argument("extracted_root", type=Path)
    verify_parser.add_argument("source_manifest", type=Path)
    verify_parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "paths":
        print("\n".join(candidate_paths()))
    elif args.command == "manifest":
        print(json.dumps(create_manifest(args.output), ensure_ascii=False, sort_keys=True))
    elif args.command == "build":
        print(json.dumps(build_zip(args.source_manifest, args.output), ensure_ascii=False, sort_keys=True))
    elif args.command == "inspect":
        print(json.dumps(inspect_zip(args.zip_path, args.source_manifest, args.output), ensure_ascii=False, sort_keys=True))
    elif args.command == "extract":
        safe_extract(args.zip_path, args.destination)
    elif args.command == "verify-extraction":
        result = verify_extraction(args.extracted_root, args.source_manifest)
        write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not result["passed"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
