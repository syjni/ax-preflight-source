"""Export product Pydantic JSON Schemas for later TypeScript generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import DeliveryEnvelope, SubmitAnswerInput, UnscoredObservation
from .onboarding import OnboardingAssessment
from .evidence import EvidenceCheckResult, ToolResponseRecord
from .findings import DataFinding, FindingsResponse
from .retrieval_trace import RetrievalTrace
from .tool_attempts import ToolAttemptRecord


SCHEMA_MODELS = (
    SubmitAnswerInput, DeliveryEnvelope, UnscoredObservation,
    ToolResponseRecord, ToolAttemptRecord, EvidenceCheckResult,
    OnboardingAssessment,
    RetrievalTrace,
    DataFinding, FindingsResponse,
)


def export_schemas(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for model in SCHEMA_MODELS:
        path = output_dir / f"{model.__name__}.schema.json"
        schema = model.model_json_schema()
        if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != schema:
            path.write_text(
                json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        paths.append(path)
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    for exported_path in export_schemas(args.output_dir):
        print(exported_path)
