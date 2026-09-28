"""Minimal product HTTP boundary; no model runner is enabled by default."""

from __future__ import annotations

import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, Protocol
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import Field, model_validator

from ax_mcp.runtime_dataset import RuntimeDatasetError, resolve_runtime_dataset
from ax_scanner.models import ScanReport
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


RUNNER_ENV = "AX_PRODUCT_RUNNER"
KIRO_CLI_ENV = "AX_KIRO_CLI"
RUN_TIMEOUT_ENV = "AX_PRODUCT_RUN_TIMEOUT_SECONDS"
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
    model: str = "claude-sonnet-5"

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
               batch_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="AX Preflight API")
    store = CompositeResultStore(results_root, frozen_results_root)
    evidence_lookup = EvidenceCheckLookup(store)
    task_catalog = BusinessTaskCatalog.model_validate_json(
        Path(task_catalog_path).read_text(encoding="utf-8")
    )
    task_approvals = BusinessTaskApprovalRegistry.model_validate_json(
        Path(task_approval_path).read_text(encoding="utf-8")
    )
    validate_approval_registry(task_approvals, task_catalog)

    def task_views(dataset: str) -> list[BusinessTaskView]:
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

    def resolve_execution_request(request: RunRequest) -> ResolvedRunRequest:
        resolved_question = request.question
        if request.request_type == "VERIFIED_BUSINESS_TASK":
            approval = task_approvals.for_dataset(request.dataset).get(
                request.task_id or ""
            )
            approved_task = next(
                (task for task in task_catalog.tasks if task.task_id == request.task_id),
                None,
            )
            if approval is None or approved_task is None:
                raise HTTPException(
                    status_code=409, detail="VERIFIED_TASK_NOT_ONBOARDED"
                )
            resolved_question = approved_task.question
        elif request.request_type == "TASK_CANDIDATE":
            candidate = next(
                (task for task in task_catalog.tasks if task.task_id == request.task_id),
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

    def execute_run(request: RunRequest) -> DeliveryEnvelope:
        onboarding = assess_onboarding(
            _dataset(request.dataset, dataset_config), task_catalog, task_approvals
        )
        if not onboarding.can_run:
            raise HTTPException(status_code=409, detail="ONBOARDING_BLOCKED")
        if runner is None:
            raise HTTPException(status_code=503, detail="RUNNER_UNAVAILABLE")
        resolved_request = resolve_execution_request(request)
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
        return execute_run(RunRequest(
            dataset=batch.dataset,
            request_type=item.request_type,
            task_id=item.task_id,
            question=(
                item.task_label if item.request_type == "TASK_CANDIDATE" else None
            ),
            run_id=run_id,
            model=batch.model,
        ))

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

    @app.get("/api/datasets", response_model=DatasetsResponse)
    def datasets() -> dict:
        options = []
        for profile, display_label in CURATED_DATASETS:
            selected = _dataset(profile, dataset_config)
            options.append({
                "profile": profile,
                "dataset_name": selected.dataset_name,
                "display_label": display_label,
            })
        return {"schema_version": "ax-datasets-response-v1", "datasets": options}

    @app.get("/api/featured-cases", response_model=FeaturedCasesResponse)
    def featured_cases() -> FeaturedCasesResponse:
        return verified_featured_cases(store, evidence_lookup)

    @app.get("/api/readiness/{dataset}", response_model=ReadinessResponse)
    def readiness(dataset: str) -> dict:
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
    def onboarding(dataset: str) -> OnboardingAssessment:
        return assess_onboarding(
            _dataset(dataset, dataset_config), task_catalog, task_approvals
        )

    @app.get("/api/tasks/{dataset}", response_model=TasksResponse)
    def tasks(dataset: str) -> dict:
        _dataset(dataset, dataset_config)
        views = task_views(dataset)
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
    def findings(dataset: str) -> FindingsResponse:
        _dataset(dataset, dataset_config)
        return aggregate_findings(
            store, dataset, comparison_config=finding_comparison_config,
            include_inconsistency_findings=include_inconsistency_findings,
            comparison_version="v2",
        )

    @app.get("/api/runs/{run_id}", response_model=RunningRun | DeliveryEnvelope)
    def get_run(run_id: str) -> RunningRun | DeliveryEnvelope:
        try:
            return store.read(run_id)
        except RunInProgressError as exc:
            return RunningRun(run_id=run_id, dataset=exc.dataset)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/api/runs/{run_id}/evidence-check", response_model=EvidenceCheckResult)
    def get_evidence_check(run_id: str) -> EvidenceCheckResult:
        try:
            return evidence_lookup.read(run_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="evidence check not found") from exc

    @app.get("/api/runs/{run_id}/retrieval-trace", response_model=RetrievalTrace)
    def get_retrieval_trace(run_id: str) -> RetrievalTrace:
        try:
            delivery = store.read(run_id)
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
    def run(request: RunRequest) -> DeliveryEnvelope:
        return execute_run(request)

    @app.post("/api/batches", response_model=BatchStatus, status_code=202)
    def create_batch(request: BatchCreateRequest) -> BatchStatus:
        onboarding = assess_onboarding(
            _dataset(request.dataset, dataset_config), task_catalog, task_approvals
        )
        if not onboarding.can_run:
            raise HTTPException(status_code=409, detail="ONBOARDING_BLOCKED")
        if runner is None:
            raise HTTPException(status_code=503, detail="RUNNER_UNAVAILABLE")
        resolved_questions = {}
        for task in request.tasks:
            resolved = resolve_execution_request(RunRequest(
                dataset=request.dataset,
                request_type=task.request_type,
                task_id=task.task_id,
                question=task.question,
                model=request.model,
            ))
            resolved_questions[task.task_id] = resolved.question
        try:
            return batch_manager.create(request, resolved_questions)
        except DuplicateBatchError as exc:
            raise HTTPException(
                status_code=409, detail="batch_id already exists"
            ) from exc

    @app.get("/api/batches/{batch_id}", response_model=BatchStatus)
    def get_batch(batch_id: str) -> BatchStatus:
        try:
            return batch_manager.read(batch_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="batch not found") from exc

    def batch_action(action: str, batch_id: str) -> BatchStatus:
        if runner is None:
            raise HTTPException(status_code=503, detail="RUNNER_UNAVAILABLE")
        try:
            operation = getattr(batch_manager, action)
            return operation(batch_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="batch not found") from exc
        except BatchStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/batches/{batch_id}/pause", response_model=BatchStatus)
    def pause_batch(batch_id: str) -> BatchStatus:
        return batch_action("pause", batch_id)

    @app.post("/api/batches/{batch_id}/resume", response_model=BatchStatus)
    def resume_batch(batch_id: str) -> BatchStatus:
        return batch_action("resume", batch_id)

    @app.post("/api/batches/{batch_id}/cancel", response_model=BatchStatus)
    def cancel_batch(batch_id: str) -> BatchStatus:
        return batch_action("cancel", batch_id)

    @app.post("/api/batches/{batch_id}/retry", response_model=BatchStatus)
    def retry_batch(batch_id: str) -> BatchStatus:
        return batch_action("retry_failed", batch_id)

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
    dataset_config = Path(
        os.environ.get("AX_RUNTIME_DATASET_CONFIG", str(DEFAULT_DATASET_CONFIG))
    ).resolve()
    runner = KiroProductRunner(
        dataset_config=dataset_config,
        executable=os.environ.get(KIRO_CLI_ENV),
        timeout_seconds=timeout_seconds,
    )
    return create_app(
        dataset_config=dataset_config,
        frozen_results_root=frozen_results_root,
        runner=runner,
    )


def create_read_only_app_from_env() -> FastAPI:
    """Serve verified Phase 6 reads while keeping POST explicitly unavailable."""
    frozen_results_root = _verified_frozen_results_root_from_env(required=True)
    dataset_config = Path(
        os.environ.get("AX_RUNTIME_DATASET_CONFIG", str(DEFAULT_DATASET_CONFIG))
    ).resolve()
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


app = create_app()
