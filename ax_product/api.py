"""Minimal product HTTP boundary; no model runner is enabled by default."""

from __future__ import annotations

import math
import os
import json
import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Literal, Protocol
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator

from ax_mcp.runtime_dataset import RuntimeDatasetError, resolve_runtime_dataset
from ax_scanner.models import ScanReport
from ax_scanner.parsers import SUPPORTED_EXTENSIONS
from ax_scanner.ocr import detect_ocr_capability
from readiness_score import score_scan_report_file

from .batches import (
    BatchCreateRequest, BatchItem, BatchManager, BatchStateError, BatchStatus,
    BatchStore, DEFAULT_BATCH_ROOT, DuplicateBatchError,
)
from .models import DeliveryEnvelope, StrictProductModel, UnscoredObservation
from .onboarding import OnboardingAssessment, assess_onboarding
from .evidence import (
    EvidenceArtifactExistsError, EvidenceCheckLookup, EvidenceCheckResult,
    ToolResponseStore,
)
from .evidence_v3 import check_run_v3
from .console_contracts import (
    BusinessTaskApprovalSummary, BusinessTaskCatalog, BusinessTaskView,
    DatasetsResponse, FeaturedCasesResponse, ReadinessResponse, TasksResponse,
)
from .featured_cases import verified_featured_cases
from .findings import FindingsResponse, aggregate_findings, task_identity
from .results import (
    CompositeResultStore, DEFAULT_RESULTS_ROOT, DuplicateRunError,
    FinalResultExistsError, RunInProgressError,
)
from .runner import DEFAULT_DATASET_CONFIG, KiroProductRunner
from .request_validation import ResolvedRunRequest, validate_runner_request
from .retrieval_trace import RetrievalTrace, build_retrieval_trace
from .task_approvals import (
    BusinessTaskApprovalRegistry, validate_approval_registry,
)
from .tool_attempts import ToolAttemptStore
from .access_control import (
    ACCESS_ROOT_ENV, COOKIE_NAME, AccessControlError, AccessControlStore,
    AccessIdentity, AuthSessionResponse, BootstrapRequest, CreateUserRequest,
    LoginRequest, ProjectCreateRequest, ProjectMemberRequest, ProjectMemberView,
    ProjectTaskView, ProjectView, SessionRevocationResult, TaskCreateRequest,
    UserView,
)
from .governance import (
    ProjectAuditLog, ProjectDataInventory, ProjectPurgeRequest,
    ProjectPurgeResult, ProjectRetentionPolicyUpdate,
    ProjectRetentionPolicyView,
)
from .execution_control import (
    DataTransferApprovalRequest, DataTransferApprovalView,
    ExecutionPolicyUpdate, ModelConnectionStatus, ProjectExecutionControl,
    ProjectExecutionPolicyView,
)
from .poc_evaluation import (
    PocDecisionUpdate, PocEvaluationGate, PocEvaluationMetrics,
    PocEvaluationReport,
)
from .local_datasets import (
    DEFAULT_LOCAL_DATASETS_ROOT,
    LOCAL_DATASETS_ROOT_ENV,
    LocalDatasetDeleteResult,
    LocalDatasetError,
    LocalDatasetRequest,
    LocalDatasetScanResult,
    LocalDatasetStore,
    ProductCapabilities,
)


RUNNER_ENV = "AX_PRODUCT_RUNNER"
KIRO_CLI_ENV = "AX_KIRO_CLI"
RUN_TIMEOUT_ENV = "AX_PRODUCT_RUN_TIMEOUT_SECONDS"
DEFAULT_MODEL = "claude-sonnet-5"
FROZEN_RESULTS_ROOT_ENV = "AX_PRODUCT_FROZEN_RESULTS_ROOT"
ROOT = Path(__file__).resolve().parents[1]
PHASE6_FROZEN_V1_RESULTS_ROOT = ROOT / "artifacts" / "phase6_product_demo" / "runs"
PHASE6_FROZEN_V2_RESULTS_ROOT = ROOT / "artifacts" / "phase6_product_demo_v2" / "runs"
PHASE6_FROZEN_RESULTS_ROOT = ROOT / "artifacts" / "phase6_product_demo_v3" / "runs"
PHASE6_FROZEN_V4_RESULTS_ROOT = ROOT / "artifacts" / "phase6_product_demo_v4" / "runs"
DEFAULT_TASK_CATALOG = ROOT / "business_task_catalog.json"
DEFAULT_TASK_APPROVALS = ROOT / "business_task_approvals.json"
CURATED_DATASETS = (
    ("mini", "Mini · 샘플 데이터"),
    ("portfolio-hidden-conflict-before", "한빛유통 30개 파일 · Before"),
    ("portfolio-ceiling-after", "한빛유통 30개 파일 · After"),
    ("demo-return-before", "반품 정책 · Before"),
    ("demo-return-after", "반품 정책 · After"),
)


class RunRequest(StrictProductModel):
    dataset: str = Field(min_length=1)
    request_type: Literal["VERIFIED_BUSINESS_TASK", "TASK_CANDIDATE", "AD_HOC_QUESTION"]
    task_id: str | None = None
    question: str | None = None
    run_id: str | None = None
    model: str = DEFAULT_MODEL

    @model_validator(mode="after")
    def nonblank_fields(self) -> "RunRequest":
        for name in ("dataset", "task_id", "question", "model"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} must not be blank")
        if self.request_type == "VERIFIED_BUSINESS_TASK":
            if self.task_id is None or self.question is not None:
                raise ValueError("verified task requires task_id and forbids question")
        elif self.request_type == "TASK_CANDIDATE":
            if self.task_id is None or self.question is None:
                raise ValueError("task candidate requires task_id and question")
        elif self.question is None or self.task_id is not None:
            raise ValueError("ad-hoc question requires question and forbids task_id")
        return self


class RunningRun(StrictProductModel):
    run_id: str
    run_status: Literal["RUNNING"] = "RUNNING"
    dataset: str = "UNKNOWN"


class Runner(Protocol):
    def run(
        self, request: ResolvedRunRequest, *, run_id: str, results_root: Path
    ) -> None:
        """Wait for the MCP process to exit; it writes its envelope under results_root."""


class RunGate(Protocol):
    def assess(self, request: RunRequest, *, run_id: str) -> Literal["INVALID_RUN"] | None:
        """Make an explicit run validity decision, separate from runner exceptions."""


def _dataset(profile: str, config_path: Path | None):
    try:
        return resolve_runtime_dataset(profile, config_path)
    except RuntimeDatasetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def create_app(*, results_root: Path = DEFAULT_RESULTS_ROOT,
               frozen_results_root: Path | None = None,
               dataset_config: Path | None = None, runner: Runner | None = None,
               gate: RunGate | None = None,
               include_inconsistency_findings: bool = True,
               finding_comparison_config: Path | None = None,
               task_catalog_path: Path = DEFAULT_TASK_CATALOG,
               task_approval_path: Path = DEFAULT_TASK_APPROVALS,
               batch_root: Path | None = None,
               local_dataset_store: LocalDatasetStore | None = None,
               access_control: AccessControlStore | None = None) -> FastAPI:
    app = FastAPI(title="AX Preflight API")
    lifecycle_lock = RLock()
    if local_dataset_store is not None:
        dataset_config = local_dataset_store.config_path
    store = CompositeResultStore(results_root, frozen_results_root)
    evidence_lookup = EvidenceCheckLookup(store)
    task_catalog = BusinessTaskCatalog.model_validate_json(
        Path(task_catalog_path).read_text(encoding="utf-8")
    )
    task_approvals = BusinessTaskApprovalRegistry.model_validate_json(
        Path(task_approval_path).read_text(encoding="utf-8")
    )
    validate_approval_registry(task_approvals, task_catalog)

    def raise_access_error(exc: AccessControlError) -> None:
        status = 404 if exc.code in {"PROJECT_NOT_FOUND", "TASK_NOT_FOUND", "USER_NOT_FOUND"} else (
            429 if exc.code == "LOGIN_RATE_LIMITED" else
            401 if exc.code in {"INVALID_CREDENTIALS", "SESSION_EXPIRED"} else
            422 if exc.code == "PII_CLASSIFICATION_REQUIRED" else
            409 if exc.code in {
                "BOOTSTRAP_CLOSED", "USERNAME_EXISTS",
                "EXECUTION_POLICY_REQUIRED", "MODEL_NOT_APPROVED",
                "EXECUTION_ALREADY_RECORDED", "PROJECT_LEGAL_HOLD",
                "AUDIT_LEDGER_INVALID",
            } else 403
        )
        headers = (
            {"Retry-After": str(access_control.login_lock_minutes * 60)}
            if exc.code == "LOGIN_RATE_LIMITED" and access_control is not None
            else None
        )
        raise HTTPException(
            status_code=status, detail=f"{exc.code} · {exc}", headers=headers
        ) from exc

    def identity_for(request: Request) -> AccessIdentity:
        identity = getattr(request.state, "access_identity", None)
        if not isinstance(identity, AccessIdentity):
            raise HTTPException(status_code=401, detail="AUTHENTICATION_REQUIRED")
        return identity

    def accessible_project_ids(identity: AccessIdentity) -> set[str]:
        assert access_control is not None
        return {project.project_id for project in access_control.projects(identity.user)}

    def model_connection_status() -> ModelConnectionStatus:
        if runner is None:
            return ModelConnectionStatus(
                runner_enabled=False,
                provider="KIRO_CLI",
                executable_status="UNAVAILABLE",
                default_model=DEFAULT_MODEL,
            )
        if isinstance(runner, KiroProductRunner):
            return ModelConnectionStatus(
                runner_enabled=True,
                provider="KIRO_CLI",
                executable_status=(
                    "AVAILABLE" if runner.configuration_available() else "UNAVAILABLE"
                ),
                timeout_seconds=max(1, math.ceil(runner.timeout_seconds)),
                default_model=DEFAULT_MODEL,
            )
        return ModelConnectionStatus(
            runner_enabled=True,
            provider="CONFIGURED_RUNNER",
            executable_status="NOT_CHECKED",
            default_model=DEFAULT_MODEL,
        )

    def local_project_id(dataset: str) -> str | None:
        if local_dataset_store is None or not local_dataset_store.contains(dataset):
            return None
        return local_dataset_store.project_id(dataset)

    def ensure_dataset_access(
        dataset: str, identity: AccessIdentity | None, *, write: bool = False
    ) -> str | None:
        project_id = local_project_id(dataset)
        if access_control is None or project_id is None:
            if access_control is not None and local_dataset_store is not None and local_dataset_store.contains(dataset):
                raise HTTPException(status_code=404, detail="LOCAL_DATASET_NOT_FOUND")
            return project_id
        if identity is None:
            raise HTTPException(status_code=401, detail="AUTHENTICATION_REQUIRED")
        try:
            access_control.require_project(identity.user, project_id, write=write)
        except AccessControlError as exc:
            raise_access_error(exc)
        return project_id

    def project_task_views(dataset: str, identity: AccessIdentity) -> list[BusinessTaskView] | None:
        if access_control is None:
            return None
        project_id = ensure_dataset_access(dataset, identity)
        if project_id is None:
            return None
        tasks = access_control.tasks(identity.user, project_id, dataset_profile=dataset)
        return [BusinessTaskView(
            task_id=task.task_id,
            category=task.category,
            question=task.question,
            description=task.description,
            status="VERIFIED" if task.status == "APPROVED" else "CANDIDATE",
            approval=(
                BusinessTaskApprovalSummary(
                    approval_id=task.approval_id or "",
                    owner_role=task.owner_role,
                    success_criteria=task.success_criteria,
                    approval_scope="CUSTOMER",
                    approved_by_role=task.approved_by_role or "PROJECT_OWNER",
                    approved_at=(task.approved_at or task.created_at).date().isoformat(),
                ) if task.status == "APPROVED" else None
            ),
        ) for task in tasks]

    def task_views(dataset: str, identity: AccessIdentity | None = None) -> list[BusinessTaskView]:
        if identity is not None:
            project_views = project_task_views(dataset, identity)
            if project_views is not None:
                return project_views
        approvals = task_approvals.for_dataset(dataset)
        views = []
        for task in task_catalog.tasks:
            approval = approvals.get(task.task_id)
            summary = None if approval is None else BusinessTaskApprovalSummary(
                approval_id=approval.approval_id,
                owner_role=approval.owner_role,
                success_criteria=approval.success_criteria,
                approval_scope=approval.approval_scope,
                approved_by_role=approval.approved_by_role,
                approved_at=approval.approved_at,
            )
            views.append(BusinessTaskView(
                task_id=task.task_id,
                category=task.category,
                question=task.question,
                description=task.description,
                status="VERIFIED" if approval is not None else "CANDIDATE",
                approval=summary,
            ))
        return views

    def final_with_evidence(run_id: str) -> DeliveryEnvelope:
        origin = store.origin(run_id)
        final = store.read(run_id)
        if origin == "frozen":
            return final
        try:
            evidence_lookup.writable.read(run_id)
        except (FileNotFoundError, ValueError):
            try:
                evidence_lookup.writable.write(check_run_v3(store.root, run_id))
            except EvidenceArtifactExistsError:
                pass
            except (OSError, ValueError):
                # Evidence processing can never replace or invalidate delivery.json.
                pass
        return final

    def final_or_runtime_error(run_id: str, request: RunRequest) -> DeliveryEnvelope:
        try:
            return final_with_evidence(run_id)
        except RunInProgressError:
            try:
                store.write(DeliveryEnvelope(
                    delivery_status="REJECTED", run_id=run_id, task_id=request.task_id,
                    model=request.model, reject_reason="RUNTIME_ERROR",
                ))
            except FinalResultExistsError:
                # A concurrent final writer won; its result remains authoritative.
                pass
            return final_with_evidence(run_id)

    def resolve_execution_request(
        request: RunRequest, identity: AccessIdentity | None = None
    ) -> ResolvedRunRequest:
        resolved_question = request.question
        dynamic_tasks = task_views(request.dataset, identity)
        if request.request_type == "VERIFIED_BUSINESS_TASK":
            approved_task = next(
                (task for task in dynamic_tasks if task.task_id == request.task_id and task.status == "VERIFIED"),
                None,
            )
            if approved_task is None:
                raise HTTPException(
                    status_code=409, detail="VERIFIED_TASK_NOT_ONBOARDED"
                )
            resolved_question = approved_task.question
        elif request.request_type == "TASK_CANDIDATE":
            candidate = next(
                (task for task in dynamic_tasks if task.task_id == request.task_id),
                None,
            )
            if candidate is None or candidate.question != request.question:
                raise HTTPException(
                    status_code=409, detail="TASK_CANDIDATE_MISMATCH"
                )
            resolved_question = candidate.question
        assert resolved_question is not None
        resolved = ResolvedRunRequest(
            dataset=request.dataset,
            request_type=request.request_type,
            task_id=request.task_id,
            question=resolved_question,
            model=request.model,
        )
        try:
            validate_runner_request(resolved)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return resolved

    def onboarding_for(dataset: str, identity: AccessIdentity | None = None) -> OnboardingAssessment:
        assessment = assess_onboarding(
            _dataset(dataset, dataset_config), task_catalog, task_approvals
        )
        if identity is None or local_project_id(dataset) is None:
            return assessment
        views = task_views(dataset, identity)
        verified = sum(task.status == "VERIFIED" for task in views)
        checks = [check for check in assessment.checks if check.code != "BUSINESS_TASK_REVIEW"]
        from .onboarding import OnboardingCheck
        checks.append(OnboardingCheck(
            code="BUSINESS_TASK_REVIEW",
            status="PASS" if views and verified == len(views) else "WARN",
            observed=verified,
            total=len(views),
        ))
        blockers = sum(check.status == "BLOCK" for check in checks)
        warnings = sum(check.status == "WARN" for check in checks)
        return assessment.model_copy(update={
            "status": "BLOCKED" if blockers else "REVIEW_REQUIRED" if warnings else "READY",
            "can_run": not blockers,
            "blocker_count": blockers,
            "warning_count": warnings,
            "checks": checks,
        })

    def execution_control_for(
        identity: AccessIdentity,
        project_id: str,
        dataset_profile: str | None,
        *,
        requested_model: str | None = None,
        requested_runs: int = 1,
        requested_concurrency: int = 1,
        batch_request: bool = False,
    ) -> ProjectExecutionControl:
        assert access_control is not None and local_dataset_store is not None
        try:
            access_control.require_project(identity.user, project_id)
        except AccessControlError as exc:
            raise_access_error(exc)
        if dataset_profile is not None:
            if (
                not local_dataset_store.contains(dataset_profile)
                or local_dataset_store.project_id(dataset_profile) != project_id
            ):
                raise HTTPException(status_code=404, detail="LOCAL_DATASET_NOT_FOUND")
        records = local_dataset_store.project_records(project_id)
        profiles = {profile for profile, _managed in records}
        _run_count, running_runs = store.writable.inventory_for_datasets(profiles)
        policy = access_control.execution_policy(identity.user, project_id)
        approval = (
            access_control.transfer_approval(
                identity.user, project_id, dataset_profile
            )
            if dataset_profile is not None else None
        )
        usage = access_control.execution_usage(
            identity.user, project_id, running_runs=running_runs
        )
        connection = model_connection_status()
        model = requested_model or (policy.model if policy else connection.default_model)
        blockers = []
        if not connection.runner_enabled:
            blockers.append("RUNNER_UNAVAILABLE")
        elif connection.executable_status == "UNAVAILABLE":
            blockers.append("RUNNER_EXECUTABLE_UNAVAILABLE")
        if policy is None:
            blockers.append("EXECUTION_POLICY_REQUIRED")
        if dataset_profile is None:
            blockers.append("DATASET_REQUIRED")
        elif approval is None:
            blockers.append("DATA_TRANSFER_APPROVAL_REQUIRED")
        elif approval.expires_at <= datetime.now(timezone.utc):
            blockers.append("DATA_TRANSFER_APPROVAL_EXPIRED")
        elif approval.model != model:
            blockers.append("MODEL_NOT_APPROVED")
        if policy is not None:
            if policy.model != model and "MODEL_NOT_APPROVED" not in blockers:
                blockers.append("MODEL_NOT_APPROVED")
            if batch_request and requested_runs > policy.max_batch_runs:
                blockers.append("BATCH_RUN_LIMIT_EXCEEDED")
            if usage is not None:
                if requested_runs > usage.remaining_run_capacity:
                    blockers.append("DAILY_RUN_LIMIT_REACHED")
                estimated_cost = requested_runs * policy.estimated_cost_per_run_cents
                if estimated_cost > usage.remaining_budget_cents:
                    blockers.append("DAILY_BUDGET_REACHED")
                if running_runs + requested_concurrency > policy.max_concurrent_runs:
                    blockers.append("CONCURRENCY_LIMIT_REACHED")
        return ProjectExecutionControl(
            project_id=project_id,
            dataset_profile=dataset_profile,
            connection=connection,
            policy=policy,
            transfer_approval=approval,
            usage=usage,
            can_execute=not blockers,
            blockers=blockers,
        )

    def require_execution_control(
        identity: AccessIdentity,
        project_id: str,
        dataset_profile: str,
        *,
        model: str,
        requested_runs: int = 1,
        requested_concurrency: int = 1,
        batch_request: bool = False,
    ) -> ProjectExecutionControl:
        control = execution_control_for(
            identity,
            project_id,
            dataset_profile,
            requested_model=model,
            requested_runs=requested_runs,
            requested_concurrency=requested_concurrency,
            batch_request=batch_request,
        )
        if control.blockers:
            blocker = control.blockers[0]
            status = 503 if blocker in {
                "RUNNER_UNAVAILABLE", "RUNNER_EXECUTABLE_UNAVAILABLE"
            } else 409
            raise HTTPException(status_code=status, detail=blocker)
        return control

    def execute_run(
        request: RunRequest, identity: AccessIdentity | None = None
    ) -> DeliveryEnvelope:
        # Reservation and destructive retention operations share this short
        # boundary. The model execution happens after release, while its RUNNING
        # state prevents a project purge until the run reaches a final result.
        with lifecycle_lock:
            project_id = ensure_dataset_access(request.dataset, identity, write=True)
            onboarding = onboarding_for(request.dataset, identity)
            if not onboarding.can_run:
                raise HTTPException(status_code=409, detail="ONBOARDING_BLOCKED")
            if runner is None:
                raise HTTPException(status_code=503, detail="RUNNER_UNAVAILABLE")
            resolved_request = resolve_execution_request(request, identity)
            if (
                project_id is not None
                and access_control is not None
                and identity is not None
            ):
                require_execution_control(
                    identity, project_id, request.dataset, model=request.model
                )
            run_id = request.run_id or uuid4().hex
            task_key, task_label = task_identity(
                request_type=request.request_type,
                task_id=request.task_id,
                question=resolved_request.question,
            )
            try:
                store.reserve(
                    run_id=run_id,
                    task_id=request.task_id,
                    model=request.model,
                    dataset=request.dataset,
                    task_key=task_key,
                    task_label=task_label,
                    request_type=request.request_type,
                )
                if (
                    project_id is not None
                    and access_control is not None
                    and identity is not None
                ):
                    try:
                        access_control.record_execution(
                            identity.user,
                            project_id,
                            request.dataset,
                            request.model,
                            run_id,
                        )
                    except Exception:
                        store.writable.discard_reservation(run_id)
                        raise
            except DuplicateRunError as exc:
                raise HTTPException(
                    status_code=409, detail="run_id already exists"
                ) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if gate is not None:
            try:
                verdict = gate.assess(request, run_id=run_id)
            except Exception:
                return final_or_runtime_error(run_id, request)
            if verdict == "INVALID_RUN":
                store.write(DeliveryEnvelope(
                    delivery_status="REJECTED",
                    run_id=run_id,
                    task_id=request.task_id,
                    model=request.model,
                    reject_reason="INVALID_RUN",
                ))
                return final_with_evidence(run_id)
            if verdict is not None:
                return final_or_runtime_error(run_id, request)
        try:
            runner.run(resolved_request, run_id=run_id, results_root=store.root)
        except Exception:
            # Cleanup errors cannot replace a final answer already on disk.
            return final_or_runtime_error(run_id, request)
        # A returned runner without a final MCP result has failed its contract.
        return final_or_runtime_error(run_id, request)

    def execute_batch_item(
        batch: BatchStatus, item: BatchItem, run_id: str
    ) -> DeliveryEnvelope:
        batch_identity = None
        if batch.requested_by_user_id is not None and access_control is not None:
            actor = access_control.user_by_id(batch.requested_by_user_id)
            batch_identity = AccessIdentity(
                user=actor,
                session_hash=f"internal-batch:{batch.batch_id}",
                csrf_hashes=[],
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        return execute_run(RunRequest(
            dataset=batch.dataset,
            request_type=item.request_type,
            task_id=item.task_id,
            question=(
                item.task_label if item.request_type == "TASK_CANDIDATE" else None
            ),
            run_id=run_id,
            model=batch.model,
        ), batch_identity)

    resolved_results_root = Path(results_root).resolve()
    if batch_root is not None:
        selected_batch_root = Path(batch_root).resolve()
    elif resolved_results_root == DEFAULT_RESULTS_ROOT.resolve():
        selected_batch_root = DEFAULT_BATCH_ROOT.resolve()
    else:
        # Test/custom run roots stay isolated without polluting the run directory.
        selected_batch_root = (
            resolved_results_root.parent
            / f".{resolved_results_root.name}-product-batches"
        )
    batch_manager = BatchManager(
        BatchStore(selected_batch_root), execute_batch_item, recover=runner is not None
    )

    def project_data_inventory(
        identity: AccessIdentity, project_id: str
    ) -> ProjectDataInventory:
        assert access_control is not None and local_dataset_store is not None
        try:
            access_control.require_project(identity.user, project_id)
            records = local_dataset_store.project_records(project_id)
            profiles = {profile for profile, _managed in records}
            run_count, running_count = store.writable.inventory_for_datasets(profiles)
            batch_count, active_batch_count = batch_manager.store.inventory_for_datasets(profiles)
            governance_counts = access_control.governance_counts(
                identity.user, project_id
            )
            _audit_status, audit_event_count = access_control.audit_integrity(
                identity.user, project_id
            )
            return ProjectDataInventory(
                project_id=project_id,
                local_dataset_count=len(records),
                managed_copy_count=sum(managed for _profile, managed in records),
                business_task_count=len(access_control.tasks(identity.user, project_id)),
                writable_run_count=run_count,
                running_run_count=running_count,
                batch_count=batch_count,
                active_batch_count=active_batch_count,
                audit_event_count=audit_event_count,
                retention_policy=access_control.retention_policy(
                    identity.user, project_id
                ),
                **governance_counts,
            )
        except AccessControlError as exc:
            raise_access_error(exc)

    def poc_evaluation_for(
        identity: AccessIdentity, project_id: str, dataset_profile: str
    ) -> PocEvaluationReport:
        assert access_control is not None and local_dataset_store is not None
        try:
            access_control.require_project(identity.user, project_id)
            if (
                not local_dataset_store.contains(dataset_profile)
                or local_dataset_store.project_id(dataset_profile) != project_id
            ):
                raise HTTPException(status_code=404, detail="LOCAL_DATASET_NOT_FOUND")
            project = next(
                item for item in access_control.projects(identity.user)
                if item.project_id == project_id
            )
            readiness_result = local_dataset_store.readiness(dataset_profile)
            onboarding_result = onboarding_for(dataset_profile, identity)
            project_tasks = access_control.tasks(
                identity.user, project_id, dataset_profile=dataset_profile
            )
            deliveries = store.writable.deliveries_for_datasets({dataset_profile})
            direct_evidence_runs = 0
            for delivery in deliveries:
                try:
                    if evidence_lookup.writable.read(delivery.run_id).verdict == "DIRECT_MATCH":
                        direct_evidence_runs += 1
                except (FileNotFoundError, ValueError):
                    continue
            findings_result = aggregate_findings(
                store,
                dataset_profile,
                comparison_config=finding_comparison_config,
                include_inconsistency_findings=include_inconsistency_findings,
            )
            metrics = PocEvaluationMetrics(
                readiness_score=readiness_result.readiness.readiness_score,
                onboarding_status=onboarding_result.status,
                registered_tasks=len(project_tasks),
                approved_tasks=sum(task.status == "APPROVED" for task in project_tasks),
                observed_runs=len(deliveries),
                answered_runs=sum(
                    delivery.delivery_status == "DELIVERED"
                    and delivery.payload is not None
                    and delivery.payload.status == "ANSWERED"
                    for delivery in deliveries
                ),
                abstained_runs=sum(
                    delivery.delivery_status == "DELIVERED"
                    and delivery.payload is not None
                    and delivery.payload.status == "ABSTAINED"
                    for delivery in deliveries
                ),
                rejected_runs=sum(
                    delivery.delivery_status == "REJECTED" for delivery in deliveries
                ),
                direct_evidence_runs=direct_evidence_runs,
                stable_tasks=findings_result.diagnostics.processable_task_count,
                open_findings=sum(
                    item.comparison_status != "NOT_REPRODUCED_AFTER"
                    for item in findings_result.findings
                ),
            )
            execution_control = execution_control_for(
                identity, project_id, dataset_profile
            )
            audit_status, audit_count = access_control.audit_integrity(
                identity.user, project_id
            )

            def gate(code: str, label: str, status: str, detail: str) -> PocEvaluationGate:
                return PocEvaluationGate(
                    code=code, label=label, status=status, detail=detail
                )

            gates = [
                gate(
                    "DATA_READINESS", "정적 데이터 준비도",
                    "PASS" if metrics.readiness_score >= 80 else "WARN",
                    f"관측 점수 {metrics.readiness_score:.0f}/100 · PoC 검토 기준 80점",
                ),
                gate(
                    "ONBOARDING", "실행 전 온보딩",
                    "PASS" if onboarding_result.status == "READY"
                    else "WARN" if onboarding_result.status == "REVIEW_REQUIRED"
                    else "BLOCK",
                    f"{onboarding_result.status} · 차단 {onboarding_result.blocker_count}개 · 검토 {onboarding_result.warning_count}개",
                ),
                gate(
                    "BUSINESS_SCOPE", "업무 범위 승인",
                    "BLOCK" if metrics.registered_tasks == 0
                    else "PASS" if metrics.approved_tasks == metrics.registered_tasks
                    else "WARN",
                    f"승인 {metrics.approved_tasks}/{metrics.registered_tasks}개",
                ),
                gate(
                    "EXECUTION_SAMPLE", "관측 실행 표본",
                    "PASS" if metrics.observed_runs >= 3
                    else "WARN" if metrics.observed_runs > 0 else "BLOCK",
                    f"완료 실행 {metrics.observed_runs}회 · 최소 검토 표본 3회",
                ),
                gate(
                    "DIRECT_EVIDENCE", "직접 근거 연결",
                    "PASS" if metrics.direct_evidence_runs > 0 else "BLOCK",
                    f"DIRECT_MATCH {metrics.direct_evidence_runs}회 · 답변 {metrics.answered_runs}회",
                ),
                gate(
                    "MODEL_BOUNDARY", "모델·데이터 전달 경계",
                    "PASS" if execution_control.can_execute else "BLOCK",
                    "실행 가능" if execution_control.can_execute
                    else f"차단: {', '.join(execution_control.blockers)}",
                ),
                gate(
                    "AUDIT_INTEGRITY", "감사 원장 무결성",
                    "BLOCK" if audit_status == "INVALID"
                    else "WARN" if audit_status == "LEGACY_UNSEALED"
                    else "PASS",
                    f"{audit_status} · 프로젝트 이벤트 {audit_count}건",
                ),
                gate(
                    "OPEN_FINDINGS", "열린 진단 신호",
                    "PASS" if metrics.open_findings == 0 else "WARN",
                    f"열린 신호 {metrics.open_findings}건 · 안정 처리 업무 {metrics.stable_tasks}개",
                ),
            ]
            recommendation = (
                "NO_GO" if any(item.status == "BLOCK" for item in gates)
                else "CONDITIONAL_GO" if any(item.status == "WARN" for item in gates)
                else "GO"
            )
            fingerprint_payload = {
                "project_id": project_id,
                "dataset_profile": dataset_profile,
                "metrics": metrics.model_dump(mode="json"),
                "gates": [
                    {"code": item.code, "status": item.status} for item in gates
                ],
                "recommendation": recommendation,
            }
            assessment_fingerprint = hashlib.sha256(
                json.dumps(
                    fingerprint_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            decision = access_control.poc_decision(
                identity.user, project_id, dataset_profile
            )
            expired = bool(
                decision and decision.expires_at <= datetime.now(timezone.utc)
            )
            current = bool(
                decision
                and not expired
                and hmac.compare_digest(
                    decision.assessment_fingerprint, assessment_fingerprint
                )
            )
            return PocEvaluationReport(
                project_id=project_id,
                project_name=project.name,
                dataset_profile=dataset_profile,
                dataset_name=readiness_result.dataset_name,
                generated_at=datetime.now(timezone.utc),
                assessment_fingerprint=assessment_fingerprint,
                metrics=metrics,
                gates=gates,
                recommendation=recommendation,
                decision=decision,
                decision_current=current,
                decision_expired=expired,
            )
        except AccessControlError as exc:
            raise_access_error(exc)

    public_api_paths = {
        "/api/capabilities", "/api/auth/session", "/api/auth/bootstrap", "/api/auth/login",
    }

    @app.middleware("http")
    async def enforce_access_boundary(request: Request, call_next):
        if access_control is None or not request.url.path.startswith("/api"):
            return await call_next(request)
        if request.url.path in public_api_paths:
            return await call_next(request)
        identity = access_control.authenticate(request.cookies.get(COOKIE_NAME))
        if identity is None:
            return JSONResponse(status_code=401, content={"detail": "AUTHENTICATION_REQUIRED"})
        request.state.access_identity = identity
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not access_control.csrf_valid(
            identity, request.headers.get("X-CSRF-Token")
        ):
            return JSONResponse(status_code=403, content={"detail": "CSRF_TOKEN_INVALID"})
        return await call_next(request)

    def set_session_cookie(response: Response, token: str) -> None:
        assert access_control is not None
        response.set_cookie(
            COOKIE_NAME, token, max_age=access_control.session_hours * 3600,
            httponly=True, secure=access_control.secure_cookie,
            samesite="strict", path="/",
        )

    @app.get("/api/auth/session", response_model=AuthSessionResponse)
    def auth_session(request: Request) -> AuthSessionResponse:
        if access_control is None:
            return AuthSessionResponse(
                authentication_required=False, authenticated=True,
                bootstrap_required=False,
            )
        identity = access_control.authenticate(request.cookies.get(COOKIE_NAME))
        if identity is None:
            return AuthSessionResponse(
                authenticated=False,
                bootstrap_required=access_control.bootstrap_required(),
            )
        csrf = access_control.rotate_csrf(identity)
        return AuthSessionResponse(
            authenticated=True, bootstrap_required=False, user=identity.user,
            csrf_token=csrf, expires_at=identity.expires_at,
        )

    @app.post("/api/auth/bootstrap", response_model=AuthSessionResponse, status_code=201)
    def bootstrap(request_body: BootstrapRequest, response: Response) -> AuthSessionResponse:
        if access_control is None:
            raise HTTPException(status_code=404, detail="AUTHENTICATION_DISABLED")
        try:
            user, _project, token, csrf, expires_at = access_control.bootstrap(request_body)
        except AccessControlError as exc:
            raise_access_error(exc)
        set_session_cookie(response, token)
        return AuthSessionResponse(
            authenticated=True, bootstrap_required=False, user=user,
            csrf_token=csrf, expires_at=expires_at,
        )

    @app.post("/api/auth/login", response_model=AuthSessionResponse)
    def login(request_body: LoginRequest, response: Response) -> AuthSessionResponse:
        if access_control is None:
            raise HTTPException(status_code=404, detail="AUTHENTICATION_DISABLED")
        try:
            user, token, csrf, expires_at = access_control.login(request_body)
        except AccessControlError as exc:
            raise_access_error(exc)
        set_session_cookie(response, token)
        return AuthSessionResponse(
            authenticated=True, bootstrap_required=False, user=user,
            csrf_token=csrf, expires_at=expires_at,
        )

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request, response: Response) -> None:
        assert access_control is not None
        access_control.logout(identity_for(request))
        response.delete_cookie(COOKIE_NAME, path="/", samesite="strict")

    @app.get("/api/users", response_model=list[UserView])
    def users(request: Request) -> list[UserView]:
        if access_control is None:
            raise HTTPException(status_code=404, detail="AUTHENTICATION_DISABLED")
        try:
            return access_control.users(identity_for(request).user)
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.post("/api/users", response_model=UserView, status_code=201)
    def create_user(request_body: CreateUserRequest, request: Request) -> UserView:
        assert access_control is not None
        try:
            return access_control.create_user(identity_for(request).user, request_body)
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.post(
        "/api/users/{user_id}/revoke-sessions",
        response_model=SessionRevocationResult,
    )
    def revoke_user_sessions(user_id: str, request: Request) -> SessionRevocationResult:
        assert access_control is not None
        try:
            return access_control.revoke_sessions(identity_for(request).user, user_id)
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.get("/api/projects", response_model=list[ProjectView])
    def projects(request: Request) -> list[ProjectView]:
        if access_control is None:
            return []
        return access_control.projects(identity_for(request).user)

    @app.post("/api/projects", response_model=ProjectView, status_code=201)
    def create_project(request_body: ProjectCreateRequest, request: Request) -> ProjectView:
        assert access_control is not None
        return access_control.create_project(identity_for(request).user, request_body)

    @app.get("/api/projects/{project_id}/members", response_model=list[ProjectMemberView])
    def project_members(project_id: str, request: Request) -> list[ProjectMemberView]:
        assert access_control is not None
        try:
            return access_control.members(identity_for(request).user, project_id)
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.post(
        "/api/projects/{project_id}/members", response_model=ProjectMemberView,
        status_code=201,
    )
    def add_project_member(
        project_id: str, request_body: ProjectMemberRequest, request: Request
    ) -> ProjectMemberView:
        assert access_control is not None
        try:
            return access_control.add_member(
                identity_for(request).user, project_id, request_body
            )
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.delete("/api/projects/{project_id}/members/{user_id}", status_code=204)
    def remove_project_member(project_id: str, user_id: str, request: Request) -> None:
        assert access_control is not None
        try:
            access_control.remove_member(identity_for(request).user, project_id, user_id)
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.get("/api/projects/{project_id}/tasks", response_model=list[ProjectTaskView])
    def project_tasks(
        project_id: str, request: Request, dataset_profile: str | None = None
    ) -> list[ProjectTaskView]:
        assert access_control is not None
        try:
            return access_control.tasks(
                identity_for(request).user, project_id,
                dataset_profile=dataset_profile,
            )
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.post(
        "/api/projects/{project_id}/tasks", response_model=ProjectTaskView,
        status_code=201,
    )
    def create_project_task(
        project_id: str, request_body: TaskCreateRequest, request: Request
    ) -> ProjectTaskView:
        assert access_control is not None
        with lifecycle_lock:
            identity = identity_for(request)
            if local_dataset_store is None or not local_dataset_store.contains(request_body.dataset_profile):
                raise HTTPException(status_code=422, detail="LOCAL_DATASET_REQUIRED")
            if local_dataset_store.project_id(request_body.dataset_profile) != project_id:
                raise HTTPException(status_code=404, detail="LOCAL_DATASET_NOT_FOUND")
            try:
                return access_control.create_task(identity.user, project_id, request_body)
            except AccessControlError as exc:
                raise_access_error(exc)

    @app.post(
        "/api/projects/{project_id}/tasks/{task_id}/approve",
        response_model=ProjectTaskView,
    )
    def approve_project_task(
        project_id: str, task_id: str, request: Request
    ) -> ProjectTaskView:
        assert access_control is not None
        try:
            return access_control.approve_task(identity_for(request).user, project_id, task_id)
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.get(
        "/api/projects/{project_id}/execution-control",
        response_model=ProjectExecutionControl,
    )
    def get_project_execution_control(
        project_id: str, request: Request, dataset_profile: str | None = None
    ) -> ProjectExecutionControl:
        if access_control is None or local_dataset_store is None:
            raise HTTPException(status_code=404, detail="EXECUTION_CONTROL_UNAVAILABLE")
        return execution_control_for(
            identity_for(request), project_id, dataset_profile
        )

    @app.put(
        "/api/projects/{project_id}/execution-policy",
        response_model=ProjectExecutionPolicyView,
    )
    def update_project_execution_policy(
        project_id: str, request_body: ExecutionPolicyUpdate, request: Request
    ) -> ProjectExecutionPolicyView:
        if access_control is None:
            raise HTTPException(status_code=404, detail="EXECUTION_CONTROL_UNAVAILABLE")
        try:
            return access_control.update_execution_policy(
                identity_for(request).user, project_id, request_body
            )
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.post(
        "/api/projects/{project_id}/data-transfer-approval",
        response_model=DataTransferApprovalView,
    )
    def approve_project_data_transfer(
        project_id: str,
        request_body: DataTransferApprovalRequest,
        request: Request,
    ) -> DataTransferApprovalView:
        if access_control is None or local_dataset_store is None:
            raise HTTPException(status_code=404, detail="EXECUTION_CONTROL_UNAVAILABLE")
        if (
            not local_dataset_store.contains(request_body.dataset_profile)
            or local_dataset_store.project_id(request_body.dataset_profile) != project_id
        ):
            raise HTTPException(status_code=404, detail="LOCAL_DATASET_NOT_FOUND")
        pii_count = (
            local_dataset_store.readiness(request_body.dataset_profile)
            .readiness.counts.safety.pii_affected_files
        )
        try:
            return access_control.approve_data_transfer(
                identity_for(request).user,
                project_id,
                request_body,
                pii_affected_file_count=pii_count,
            )
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.delete(
        "/api/projects/{project_id}/data-transfer-approval/{dataset_profile}",
        status_code=204,
    )
    def revoke_project_data_transfer(
        project_id: str, dataset_profile: str, request: Request
    ) -> None:
        if access_control is None:
            raise HTTPException(status_code=404, detail="EXECUTION_CONTROL_UNAVAILABLE")
        try:
            access_control.revoke_data_transfer(
                identity_for(request).user, project_id, dataset_profile
            )
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.get(
        "/api/projects/{project_id}/data-inventory",
        response_model=ProjectDataInventory,
    )
    def get_project_data_inventory(
        project_id: str, request: Request
    ) -> ProjectDataInventory:
        if local_dataset_store is None:
            raise HTTPException(status_code=404, detail="LOCAL_SCAN_UNAVAILABLE")
        return project_data_inventory(identity_for(request), project_id)

    @app.get(
        "/api/projects/{project_id}/audit-log",
        response_model=ProjectAuditLog,
    )
    def get_project_audit_log(
        project_id: str, request: Request, limit: int = 100
    ) -> ProjectAuditLog:
        if access_control is None:
            raise HTTPException(status_code=404, detail="PROJECT_GOVERNANCE_UNAVAILABLE")
        try:
            return access_control.audit_log(
                identity_for(request).user, project_id, limit=limit
            )
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.put(
        "/api/projects/{project_id}/retention-policy",
        response_model=ProjectRetentionPolicyView,
    )
    def update_project_retention_policy(
        project_id: str,
        request_body: ProjectRetentionPolicyUpdate,
        request: Request,
    ) -> ProjectRetentionPolicyView:
        if access_control is None:
            raise HTTPException(status_code=404, detail="PROJECT_GOVERNANCE_UNAVAILABLE")
        try:
            return access_control.update_retention_policy(
                identity_for(request).user, project_id, request_body
            )
        except AccessControlError as exc:
            raise_access_error(exc)

    @app.get(
        "/api/projects/{project_id}/poc-evaluation",
        response_model=PocEvaluationReport,
    )
    def get_project_poc_evaluation(
        project_id: str, dataset_profile: str, request: Request
    ) -> PocEvaluationReport:
        if access_control is None or local_dataset_store is None:
            raise HTTPException(status_code=404, detail="POC_EVALUATION_UNAVAILABLE")
        return poc_evaluation_for(
            identity_for(request), project_id, dataset_profile
        )

    @app.put(
        "/api/projects/{project_id}/poc-evaluation/decision",
        response_model=PocEvaluationReport,
    )
    def record_project_poc_decision(
        project_id: str,
        dataset_profile: str,
        request_body: PocDecisionUpdate,
        request: Request,
    ) -> PocEvaluationReport:
        if access_control is None or local_dataset_store is None:
            raise HTTPException(status_code=404, detail="POC_EVALUATION_UNAVAILABLE")
        identity = identity_for(request)
        report = poc_evaluation_for(identity, project_id, dataset_profile)
        if request_body.decision == "APPROVED" and report.recommendation != "GO":
            raise HTTPException(status_code=409, detail="POC_GO_GATES_REQUIRED")
        if (
            request_body.decision == "CONDITIONAL"
            and report.recommendation == "NO_GO"
        ):
            raise HTTPException(status_code=409, detail="POC_BLOCKERS_REMAIN")
        try:
            access_control.record_poc_decision(
                identity.user,
                project_id,
                dataset_profile,
                request_body,
                assessment_fingerprint=report.assessment_fingerprint,
            )
        except AccessControlError as exc:
            raise_access_error(exc)
        return poc_evaluation_for(identity, project_id, dataset_profile)

    @app.post(
        "/api/projects/{project_id}/purge",
        response_model=ProjectPurgeResult,
    )
    def purge_project(
        project_id: str, request_body: ProjectPurgeRequest, request: Request
    ) -> ProjectPurgeResult:
        if access_control is None or local_dataset_store is None:
            raise HTTPException(status_code=404, detail="PROJECT_GOVERNANCE_UNAVAILABLE")
        identity = identity_for(request)
        with lifecycle_lock:
            try:
                projects = access_control.projects(identity.user)
                project = next(
                    (item for item in projects if item.project_id == project_id), None
                )
                access_control.require_project(identity.user, project_id, owner=True)
            except AccessControlError as exc:
                raise_access_error(exc)
            if project is None:
                raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
            if not hmac.compare_digest(
                request_body.confirmation.encode("utf-8"), project.name.encode("utf-8")
            ):
                raise HTTPException(status_code=422, detail="PROJECT_NAME_CONFIRMATION_MISMATCH")
            inventory = project_data_inventory(identity, project_id)
            if inventory.running_run_count or inventory.active_batch_count:
                raise HTTPException(status_code=409, detail="PROJECT_DATA_IN_USE")
            if inventory.retention_policy.legal_hold:
                raise HTTPException(status_code=409, detail="PROJECT_LEGAL_HOLD")
            audit_status, _audit_count = access_control.audit_integrity(
                identity.user, project_id
            )
            if audit_status == "INVALID":
                raise HTTPException(status_code=409, detail="AUDIT_LEDGER_INVALID")
            records = local_dataset_store.project_records(project_id)
            profiles = {profile for profile, _managed in records}
            purge_receipt_id = f"purge_{uuid4().hex}"
            try:
                runs_deleted = store.writable.delete_for_datasets(profiles)
                batches_deleted = batch_manager.store.delete_for_datasets(profiles)
                for profile, _managed in records:
                    local_dataset_store.delete(profile)
                project_name, access_deleted = access_control.delete_project(
                    identity.user,
                    project_id,
                    purge_receipt_id=purge_receipt_id,
                )
            except (RunInProgressError, BatchStateError) as exc:
                raise HTTPException(status_code=409, detail="PROJECT_DATA_IN_USE") from exc
            except AccessControlError as exc:
                raise_access_error(exc)
            remaining_records = local_dataset_store.project_records(project_id)
            remaining_runs, _ = store.writable.inventory_for_datasets(profiles)
            remaining_batches, _ = batch_manager.store.inventory_for_datasets(profiles)
            if (
                remaining_records
                or remaining_runs
                or remaining_batches
                or access_control.project_exists(project_id)
                or access_control.audit_contains(project_id)
            ):
                raise HTTPException(status_code=500, detail="PROJECT_PURGE_VERIFICATION_FAILED")
            return ProjectPurgeResult(
                project_id=project_id,
                project_name=project_name,
                purge_receipt_id=purge_receipt_id,
                completed_at=datetime.now(timezone.utc),
                local_datasets_deleted=len(records),
                managed_copies_deleted=sum(managed for _profile, managed in records),
                writable_runs_deleted=runs_deleted,
                batches_deleted=batches_deleted,
                **access_deleted,
            )

    @app.get("/api/datasets", response_model=DatasetsResponse)
    def datasets(request: Request) -> dict:
        options = []
        for profile, display_label in CURATED_DATASETS:
            selected = _dataset(profile, dataset_config)
            options.append({
                "profile": profile,
                "dataset_name": selected.dataset_name,
                "display_label": display_label,
                "origin": "BUNDLED",
            })
        if local_dataset_store is not None:
            project_ids = None
            if access_control is not None:
                project_ids = accessible_project_ids(identity_for(request))
            options.extend(
                option.model_dump(mode="json")
                for option in local_dataset_store.options(project_ids)
            )
        return {"schema_version": "ax-datasets-response-v1", "datasets": options}

    @app.get("/api/capabilities", response_model=ProductCapabilities)
    def capabilities() -> ProductCapabilities:
        ocr = detect_ocr_capability()
        return ProductCapabilities(
            mode=(
                "LIVE" if runner is not None
                else "LOCAL_REVIEW" if local_dataset_store is not None
                else "API"
            ),
            local_dataset_scan=local_dataset_store is not None,
            local_file_upload=local_dataset_store is not None,
            ai_task_execution=runner is not None,
            bundled_demo=frozen_results_root is not None,
            supported_extensions=list(SUPPORTED_EXTENSIONS),
            max_upload_files=(
                local_dataset_store.max_files if local_dataset_store else 5_000
            ),
            max_upload_bytes=(
                local_dataset_store.max_bytes if local_dataset_store else 1_073_741_824
            ),
            ocr_available=ocr.available,
            ocr_engine=ocr.engine,
            ocr_languages=list(ocr.languages),
            ocr_install_hint=(
                None if ocr.available
                else "Docker 실행에는 한국어·영어 OCR이 포함됩니다. Windows 직접 실행은 Tesseract OCR과 kor·eng 언어팩을 설치하세요."
            ),
        )

    def local_scan_result(profile: str) -> LocalDatasetScanResult:
        assert local_dataset_store is not None
        return LocalDatasetScanResult(
            dataset=local_dataset_store.option(profile),
            audit=local_dataset_store.audit(profile),
            readiness=local_dataset_store.readiness(profile),
        )

    @app.post(
        "/api/local-datasets", response_model=LocalDatasetScanResult,
        status_code=201,
    )
    def create_local_dataset(
        request_body: LocalDatasetRequest, request: Request
    ) -> LocalDatasetScanResult:
        if local_dataset_store is None:
            raise HTTPException(status_code=403, detail="LOCAL_SCAN_UNAVAILABLE")
        if access_control is not None:
            if request_body.project_id is None:
                raise HTTPException(status_code=422, detail="PROJECT_REQUIRED")
            try:
                access_control.require_project(
                    identity_for(request).user, request_body.project_id, write=True
                )
            except AccessControlError as exc:
                raise_access_error(exc)
        try:
            with lifecycle_lock:
                if access_control is not None:
                    try:
                        access_control.require_project(
                            identity_for(request).user,
                            request_body.project_id or "",
                            write=True,
                        )
                    except AccessControlError as exc:
                        raise_access_error(exc)
                return local_scan_result(local_dataset_store.scan(request_body))
        except LocalDatasetError as exc:
            raise HTTPException(
                status_code=422, detail=f"{exc.code} · {exc}"
            ) from exc

    @app.post(
        "/api/local-datasets/upload", response_model=LocalDatasetScanResult,
        status_code=201,
    )
    async def upload_local_dataset(
        request: Request,
        files: list[UploadFile] = File(...),
        relative_paths: str = Form(...),
        display_name: str | None = Form(default=None),
        source_root_name: str | None = Form(default=None),
        project_id: str | None = Form(default=None),
    ) -> LocalDatasetScanResult:
        if local_dataset_store is None:
            raise HTTPException(status_code=403, detail="LOCAL_SCAN_UNAVAILABLE")
        if access_control is not None:
            if project_id is None:
                raise HTTPException(status_code=422, detail="PROJECT_REQUIRED")
            try:
                access_control.require_project(
                    identity_for(request).user, project_id, write=True
                )
            except AccessControlError as exc:
                raise_access_error(exc)
        try:
            decoded = json.loads(relative_paths)
            if (
                not isinstance(decoded, list)
                or not all(isinstance(value, str) for value in decoded)
                or len(decoded) != len(files)
            ):
                raise LocalDatasetError(
                    "INVALID_UPLOAD_MANIFEST",
                    "선택한 파일 목록과 상대 경로 목록이 일치하지 않습니다.",
                )
            upload_root, destinations = local_dataset_store.prepare_upload(decoded)
            total_bytes = 0
            try:
                for upload, destination in zip(files, destinations, strict=True):
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with destination.open("xb") as stream:
                        while chunk := await upload.read(1024 * 1024):
                            total_bytes += len(chunk)
                            if total_bytes > local_dataset_store.max_bytes:
                                raise LocalDatasetError(
                                    "SIZE_LIMIT_EXCEEDED",
                                    f"전체 파일 크기가 {local_dataset_store.max_bytes / 1_073_741_824:.1f} GiB를 초과합니다.",
                                )
                            stream.write(chunk)
                    await upload.close()
                with lifecycle_lock:
                    if access_control is not None:
                        try:
                            access_control.require_project(
                                identity_for(request).user,
                                project_id or "",
                                write=True,
                            )
                        except AccessControlError as exc:
                            raise_access_error(exc)
                    profile = local_dataset_store.scan_upload(
                        upload_root,
                        display_name=display_name,
                        source_root_name=source_root_name,
                        project_id=project_id,
                    )
            except Exception:
                local_dataset_store.discard_upload(upload_root)
                raise
            return local_scan_result(profile)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail="INVALID_UPLOAD_MANIFEST · 파일 경로 목록이 올바른 JSON이 아닙니다.",
            ) from exc
        except LocalDatasetError as exc:
            raise HTTPException(status_code=422, detail=f"{exc.code} · {exc}") from exc
        except OSError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"UPLOAD_WRITE_FAILED · 선택한 파일을 로컬 관리 폴더에 저장하지 못했습니다: {type(exc).__name__}",
            ) from exc
        finally:
            for upload in files:
                try:
                    await upload.close()
                except OSError:
                    pass

    @app.get(
        "/api/local-datasets/{profile}", response_model=LocalDatasetScanResult
    )
    def get_local_dataset(profile: str, request: Request) -> LocalDatasetScanResult:
        if local_dataset_store is None:
            raise HTTPException(status_code=403, detail="LOCAL_SCAN_UNAVAILABLE")
        ensure_dataset_access(
            profile, identity_for(request) if access_control is not None else None
        )
        try:
            return local_scan_result(profile)
        except LocalDatasetError as exc:
            raise HTTPException(status_code=404, detail=f"{exc.code} · {exc}") from exc

    @app.delete(
        "/api/local-datasets/{profile}", response_model=LocalDatasetDeleteResult
    )
    def delete_local_dataset(profile: str, request: Request) -> LocalDatasetDeleteResult:
        if local_dataset_store is None:
            raise HTTPException(status_code=403, detail="LOCAL_SCAN_UNAVAILABLE")
        with lifecycle_lock:
            identity = identity_for(request) if access_control is not None else None
            project_id = ensure_dataset_access(profile, identity, write=True)
            if access_control is not None and identity is not None and project_id is not None:
                try:
                    access_control.require_project(identity.user, project_id, owner=True)
                except AccessControlError as exc:
                    raise_access_error(exc)
            _run_count, running_count = store.writable.inventory_for_datasets({profile})
            _batch_count, active_batch_count = batch_manager.store.inventory_for_datasets({profile})
            if running_count or active_batch_count:
                raise HTTPException(status_code=409, detail="DATASET_IN_USE")
            try:
                runs_deleted = store.writable.delete_for_datasets({profile})
                batches_deleted = batch_manager.store.delete_for_datasets({profile})
                task_records_deleted = (
                    access_control.delete_dataset_tasks(identity.user, project_id, profile)
                    if access_control is not None and identity is not None and project_id is not None
                    else 0
                )
                result = local_dataset_store.delete(profile)
                return result.model_copy(update={
                    "task_records_deleted": task_records_deleted,
                    "run_records_deleted": runs_deleted,
                    "batch_records_deleted": batches_deleted,
                })
            except LocalDatasetError as exc:
                raise HTTPException(status_code=404, detail=f"{exc.code} · {exc}") from exc
            except (RunInProgressError, BatchStateError) as exc:
                raise HTTPException(status_code=409, detail="DATASET_IN_USE") from exc

    @app.get("/api/featured-cases", response_model=FeaturedCasesResponse)
    def featured_cases() -> FeaturedCasesResponse:
        return verified_featured_cases(store, evidence_lookup)

    @app.get("/api/readiness/{dataset}", response_model=ReadinessResponse)
    def readiness(dataset: str, request: Request) -> dict:
        ensure_dataset_access(
            dataset, identity_for(request) if access_control is not None else None
        )
        if local_dataset_store is not None and local_dataset_store.contains(dataset):
            return local_dataset_store.readiness(dataset).model_dump(mode="json")
        selected = _dataset(dataset, dataset_config)
        report = ScanReport.model_validate_json(selected.scan_report.read_text(encoding="utf-8"))
        observations = [UnscoredObservation(
            code="PROBABLE_VERSION_GROUP", severity="warning",
            message=f"Probable version group {group.normalized_name}: {len(group.candidates)} candidates",
            file_ids=[candidate.file_id for candidate in group.candidates],
        ).model_dump(mode="json") for group in report.probable_version_groups]
        return {"dataset": dataset, "dataset_name": selected.dataset_name,
                "readiness": score_scan_report_file(selected.scan_report),
                "unscored_observations": observations}

    @app.get(
        "/api/onboarding/{dataset}", response_model=OnboardingAssessment
    )
    def onboarding(dataset: str, request: Request) -> OnboardingAssessment:
        identity = identity_for(request) if access_control is not None else None
        ensure_dataset_access(dataset, identity)
        return onboarding_for(dataset, identity)

    @app.get("/api/tasks/{dataset}", response_model=TasksResponse)
    def tasks(dataset: str, request: Request) -> dict:
        identity = identity_for(request) if access_control is not None else None
        ensure_dataset_access(dataset, identity)
        _dataset(dataset, dataset_config)
        views = task_views(dataset, identity)
        return {
            "dataset": dataset,
            "catalog_status": (
                "VERIFIED_TASKS_AVAILABLE"
                if any(task.status == "VERIFIED" for task in views)
                else "CANDIDATES_AVAILABLE"
            ),
            "tasks": [task.model_dump(mode="json") for task in views],
        }

    @app.get("/api/findings/{dataset}", response_model=FindingsResponse)
    def findings(dataset: str, request: Request) -> FindingsResponse:
        ensure_dataset_access(
            dataset, identity_for(request) if access_control is not None else None
        )
        _dataset(dataset, dataset_config)
        return aggregate_findings(
            store, dataset, comparison_config=finding_comparison_config,
            include_inconsistency_findings=include_inconsistency_findings,
            comparison_version="v2",
        )

    @app.get("/api/runs/{run_id}", response_model=RunningRun | DeliveryEnvelope)
    def get_run(run_id: str, request: Request) -> RunningRun | DeliveryEnvelope:
        try:
            result = store.read(run_id)
            ensure_dataset_access(
                result.dataset,
                identity_for(request) if access_control is not None else None,
            )
            return result
        except RunInProgressError as exc:
            ensure_dataset_access(
                exc.dataset,
                identity_for(request) if access_control is not None else None,
            )
            return RunningRun(run_id=run_id, dataset=exc.dataset)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/api/runs/{run_id}/evidence-check", response_model=EvidenceCheckResult)
    def get_evidence_check(run_id: str, request: Request) -> EvidenceCheckResult:
        try:
            delivery = store.read(run_id)
            ensure_dataset_access(
                delivery.dataset,
                identity_for(request) if access_control is not None else None,
            )
            return evidence_lookup.read(run_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="evidence check not found") from exc

    @app.get("/api/runs/{run_id}/retrieval-trace", response_model=RetrievalTrace)
    def get_retrieval_trace(run_id: str, request: Request) -> RetrievalTrace:
        try:
            delivery = store.read(run_id)
            ensure_dataset_access(
                delivery.dataset,
                identity_for(request) if access_control is not None else None,
            )
            if store.origin(run_id) == "frozen":
                assert store.frozen is not None
                response_root = store.frozen.root
            else:
                response_root = store.root
            records = ToolResponseStore(response_root).read(run_id)
            attempts = ToolAttemptStore(response_root).read(run_id)
            return build_retrieval_trace(delivery, records, attempts)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="retrieval trace not found") from exc

    @app.post("/api/run", response_model=DeliveryEnvelope)
    def run(request_body: RunRequest, request: Request) -> DeliveryEnvelope:
        return execute_run(
            request_body, identity_for(request) if access_control is not None else None
        )

    @app.post("/api/batches", response_model=BatchStatus, status_code=202)
    def create_batch(request_body: BatchCreateRequest, request: Request) -> BatchStatus:
        identity = identity_for(request) if access_control is not None else None
        with lifecycle_lock:
            project_id = ensure_dataset_access(
                request_body.dataset, identity, write=True
            )
            onboarding = onboarding_for(request_body.dataset, identity)
            if not onboarding.can_run:
                raise HTTPException(status_code=409, detail="ONBOARDING_BLOCKED")
            if runner is None:
                raise HTTPException(status_code=503, detail="RUNNER_UNAVAILABLE")
            planned_runs = len(request_body.tasks) * request_body.repetitions
            if (
                project_id is not None
                and access_control is not None
                and identity is not None
            ):
                require_execution_control(
                    identity,
                    project_id,
                    request_body.dataset,
                    model=request_body.model,
                    requested_runs=planned_runs,
                    batch_request=True,
                )
            resolved_questions = {}
            for task in request_body.tasks:
                resolved = resolve_execution_request(RunRequest(
                    dataset=request_body.dataset,
                    request_type=task.request_type,
                    task_id=task.task_id,
                    question=task.question,
                    model=request_body.model,
                ), identity)
                resolved_questions[task.task_id] = resolved.question
            try:
                return batch_manager.create(
                    request_body,
                    resolved_questions,
                    project_id=project_id,
                    requested_by_user_id=(
                        identity.user.user_id if project_id is not None and identity else None
                    ),
                )
            except DuplicateBatchError as exc:
                raise HTTPException(
                    status_code=409, detail="batch_id already exists"
                ) from exc

    @app.get("/api/batches/{batch_id}", response_model=BatchStatus)
    def get_batch(batch_id: str, request: Request) -> BatchStatus:
        try:
            batch = batch_manager.read(batch_id)
            ensure_dataset_access(
                batch.dataset,
                identity_for(request) if access_control is not None else None,
            )
            return batch
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="batch not found") from exc

    def batch_action(
        action: str, batch_id: str, identity: AccessIdentity | None
    ) -> BatchStatus:
        if runner is None:
            raise HTTPException(status_code=503, detail="RUNNER_UNAVAILABLE")
        try:
            existing = batch_manager.read(batch_id)
            project_id = ensure_dataset_access(existing.dataset, identity, write=True)
            if (
                action in {"resume", "retry_failed"}
                and project_id is not None
                and identity is not None
            ):
                requested_runs = sum(
                    item.status == "QUEUED"
                    if action == "resume"
                    else item.status == "FAILED" and item.attempt < existing.max_attempts
                    for item in existing.items
                )
                if requested_runs:
                    require_execution_control(
                        identity,
                        project_id,
                        existing.dataset,
                        model=existing.model,
                        requested_runs=requested_runs,
                        batch_request=True,
                    )
            operation = getattr(batch_manager, action)
            return operation(batch_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="batch not found") from exc
        except BatchStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/batches/{batch_id}/pause", response_model=BatchStatus)
    def pause_batch(batch_id: str, request: Request) -> BatchStatus:
        return batch_action("pause", batch_id, identity_for(request) if access_control is not None else None)

    @app.post("/api/batches/{batch_id}/resume", response_model=BatchStatus)
    def resume_batch(batch_id: str, request: Request) -> BatchStatus:
        return batch_action("resume", batch_id, identity_for(request) if access_control is not None else None)

    @app.post("/api/batches/{batch_id}/cancel", response_model=BatchStatus)
    def cancel_batch(batch_id: str, request: Request) -> BatchStatus:
        return batch_action("cancel", batch_id, identity_for(request) if access_control is not None else None)

    @app.post("/api/batches/{batch_id}/retry", response_model=BatchStatus)
    def retry_batch(batch_id: str, request: Request) -> BatchStatus:
        return batch_action("retry_failed", batch_id, identity_for(request) if access_control is not None else None)

    return app


def _verified_frozen_results_root_from_env(*, required: bool = False) -> Path | None:
    configured = os.environ.get(FROZEN_RESULTS_ROOT_ENV)
    if configured is None:
        if required:
            raise RuntimeError(
                f"{FROZEN_RESULTS_ROOT_ENV} is required for the read-only app factory"
            )
        return None
    if not configured.strip() or configured != configured.strip():
        raise RuntimeError(f"{FROZEN_RESULTS_ROOT_ENV} must be a nonblank, unpadded path")
    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    v2 = PHASE6_FROZEN_V2_RESULTS_ROOT.resolve()
    v3 = PHASE6_FROZEN_RESULTS_ROOT.resolve()
    v4 = PHASE6_FROZEN_V4_RESULTS_ROOT.resolve()
    if candidate not in {v2, v3, v4}:
        raise RuntimeError(
            f"{FROZEN_RESULTS_ROOT_ENV} must identify a verified Phase 6 runs root: "
            f"{v2}, {v3}, or {v4}"
        )
    try:
        if candidate == v4:
            from scripts.verify_phase6_demo_v4 import verify_phase6_demo_v4

            verify_phase6_demo_v4(root=ROOT)
        elif candidate == v3:
            from scripts.verify_phase6_demo_v3 import verify_phase6_demo_v3

            verify_phase6_demo_v3(root=ROOT)
        else:
            from scripts.verify_phase6_demo_v2 import verify_phase6_demo_v2

            verify_phase6_demo_v2(root=ROOT)
    except Exception as exc:
        raise RuntimeError("Phase 6 frozen results verification failed") from exc
    return candidate


def _dataset_config_from_env() -> Path:
    return Path(
        os.environ.get("AX_RUNTIME_DATASET_CONFIG", str(DEFAULT_DATASET_CONFIG))
    ).resolve()


def _local_dataset_root_from_env() -> Path:
    configured = Path(
        os.environ.get(LOCAL_DATASETS_ROOT_ENV, str(DEFAULT_LOCAL_DATASETS_ROOT))
    )
    return (
        configured.resolve()
        if configured.is_absolute()
        else (ROOT / configured).resolve()
    )


def _access_control_from_env(local_root: Path) -> AccessControlStore:
    configured = os.environ.get(ACCESS_ROOT_ENV)
    if configured is None:
        root = local_root / "access_control"
    else:
        candidate = Path(configured)
        root = candidate if candidate.is_absolute() else ROOT / candidate
    return AccessControlStore(root.resolve())


def create_app_from_env() -> FastAPI:
    """Create the explicitly configured deployment app.

    The module-level ``app`` below intentionally does not call this factory, so
    importing ``ax_product.api:app`` retains the safe RUNNER_UNAVAILABLE default.
    """
    frozen_results_root = _verified_frozen_results_root_from_env()
    mode = os.environ.get(RUNNER_ENV)
    if mode != "kiro":
        raise RuntimeError(f"{RUNNER_ENV}=kiro is required for the opt-in app factory")
    timeout_text = os.environ.get(RUN_TIMEOUT_ENV, "300")
    try:
        timeout_seconds = float(timeout_text)
    except ValueError as exc:
        raise RuntimeError(f"{RUN_TIMEOUT_ENV} must be a positive finite number") from exc
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise RuntimeError(f"{RUN_TIMEOUT_ENV} must be a positive finite number")
    base_dataset_config = _dataset_config_from_env()
    local_dataset_store = LocalDatasetStore(
        base_config=base_dataset_config,
        root=_local_dataset_root_from_env(),
    )
    access_control = _access_control_from_env(local_dataset_store.root)
    runner = KiroProductRunner(
        dataset_config=local_dataset_store.config_path,
        executable=os.environ.get(KIRO_CLI_ENV),
        timeout_seconds=timeout_seconds,
    )
    return create_app(
        dataset_config=local_dataset_store.config_path,
        frozen_results_root=frozen_results_root,
        runner=runner,
        local_dataset_store=local_dataset_store,
        access_control=access_control,
    )


def create_read_only_app_from_env() -> FastAPI:
    """Serve verified Phase 6 reads while keeping POST explicitly unavailable."""
    frozen_results_root = _verified_frozen_results_root_from_env(required=True)
    dataset_config = _dataset_config_from_env()
    writable_results = TemporaryDirectory(prefix="ax-preflight-read-only-")
    try:
        read_only_app = create_app(
            results_root=Path(writable_results.name),
            dataset_config=dataset_config,
            frozen_results_root=frozen_results_root,
            include_inconsistency_findings=(
                frozen_results_root.resolve()
                == PHASE6_FROZEN_V4_RESULTS_ROOT.resolve()
            ),
        )
    except Exception:
        writable_results.cleanup()
        raise
    # Keep the isolated directory alive for exactly as long as the app. GET
    # handlers may use the composite store, but can never see developer runs.
    read_only_app.state.isolated_writable_results = writable_results
    return read_only_app


def create_local_review_app_from_env() -> FastAPI:
    """Serve the verified example and let a reviewer scan their own local folder.

    Model-backed run creation stays disabled.  Only generated scan reports and
    the local registry are written; source files remain untouched.
    """
    frozen_results_root = _verified_frozen_results_root_from_env(required=True)
    local_dataset_store = LocalDatasetStore(
        base_config=_dataset_config_from_env(),
        root=_local_dataset_root_from_env(),
    )
    access_control = _access_control_from_env(local_dataset_store.root)
    writable_results = TemporaryDirectory(prefix="ax-preflight-local-review-")
    try:
        local_review_app = create_app(
            results_root=Path(writable_results.name),
            dataset_config=local_dataset_store.config_path,
            frozen_results_root=frozen_results_root,
            include_inconsistency_findings=(
                frozen_results_root.resolve()
                == PHASE6_FROZEN_V4_RESULTS_ROOT.resolve()
            ),
            local_dataset_store=local_dataset_store,
            access_control=access_control,
        )
    except Exception:
        writable_results.cleanup()
        raise
    local_review_app.state.isolated_writable_results = writable_results
    local_review_app.state.local_dataset_store = local_dataset_store
    local_review_app.state.access_control = access_control
    return local_review_app


app = create_app()
