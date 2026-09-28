from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime_dataset import DEFAULT_CONFIG, RuntimeDatasetError, resolve_runtime_dataset, runtime_identity, validate_runtime_resource_leakage


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify and report the selected AX MCP runtime dataset")
    parser.add_argument("--dataset-profile", help="profile from runtime_datasets.json; defaults to AX_RUNTIME_DATASET")
    parser.add_argument("--dataset-config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        dataset = resolve_runtime_dataset(args.dataset_profile, args.dataset_config)
        identity = runtime_identity(dataset)
        leakage = validate_runtime_resource_leakage(dataset)
    except RuntimeDatasetError as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    result = {"passed": leakage["passed"], "identity": identity, "runtime_leakage": leakage}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
