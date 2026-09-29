"""Export Pydantic JSON Schemas consumed by the Results Console."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api import RunRequest, RunningRun
from .batches import BatchCreateRequest, BatchStatus
from .console_contracts import (
    DatasetsResponse, FeaturedCasesResponse, ReadinessResponse, TasksResponse,
)
from .models import DeliveryEnvelope, SubmitAnswerInput, UnscoredObservation
from .onboarding import OnboardingAssessment
from .evidence import EvidenceCheckResult
from .findings import FindingsResponse
from .retrieval_trace import RetrievalTrace
from .local_datasets import (
    LocalDatasetDeleteResult,
    LocalDatasetRequest,
    LocalDatasetScanResult,
    ProductCapabilities,
)
from .access_control import (
    AuthSessionResponse, BootstrapRequest, CreateUserRequest, LoginRequest,
    ProjectCreateRequest, ProjectMemberRequest, ProjectMemberView,
    ProjectTaskView, ProjectView, SessionRevocationResult, TaskCreateRequest,
    UserView,
)
from .governance import (
    DeletionOperationView, ProjectAuditEvent, ProjectAuditLog, ProjectDataInventory,
    ProjectPurgeRequest, ProjectPurgeResult, ProjectRetentionPolicyUpdate,
    ProjectRetentionPolicyView,
)
from .execution_control import (
    DataTransferApprovalRequest, DataTransferApprovalView,
    ExecutionPolicyUpdate, ModelConnectionStatus, ProjectExecutionControl,
    ProjectExecutionPolicyView, ProjectExecutionUsage,
)
from .poc_evaluation import (
    PocDecisionUpdate, PocDecisionView, PocEvaluationGate,
    PocEvaluationMetrics, PocEvaluationReport,
)


MODELS = (
    DatasetsResponse, FeaturedCasesResponse, ReadinessResponse, TasksResponse,
    RunRequest, RunningRun,
    DeliveryEnvelope, SubmitAnswerInput, UnscoredObservation,
    EvidenceCheckResult, OnboardingAssessment,
    RetrievalTrace,
    FindingsResponse,
    BatchCreateRequest, BatchStatus,
    ProductCapabilities, LocalDatasetRequest, LocalDatasetScanResult,
    LocalDatasetDeleteResult,
    AuthSessionResponse, BootstrapRequest, CreateUserRequest, LoginRequest,
    ProjectCreateRequest, ProjectMemberRequest, ProjectMemberView,
    ProjectTaskView, ProjectView, SessionRevocationResult, TaskCreateRequest,
    UserView,
    DeletionOperationView, ProjectAuditEvent, ProjectAuditLog, ProjectDataInventory,
    ProjectPurgeRequest, ProjectPurgeResult, ProjectRetentionPolicyUpdate,
    ProjectRetentionPolicyView,
    DataTransferApprovalRequest, DataTransferApprovalView,
    ExecutionPolicyUpdate, ModelConnectionStatus, ProjectExecutionControl,
    ProjectExecutionPolicyView, ProjectExecutionUsage,
    PocDecisionUpdate, PocDecisionView, PocEvaluationGate,
    PocEvaluationMetrics, PocEvaluationReport,
)


def export_schemas(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        path = output_dir / f"{model.__name__}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    export_schemas(parser.parse_args().output_dir)
