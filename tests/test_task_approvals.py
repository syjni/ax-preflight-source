from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ax_product.api import RunRequest, create_app
from ax_product.console_contracts import BusinessTaskCatalog
from ax_product.models import DeliveryEnvelope, SubmitAnswerInput
from ax_product.results import ResultStore
from ax_product.task_approvals import (
    BusinessTaskApprovalRegistry,
    question_sha256,
    validate_approval_registry,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG = BusinessTaskCatalog.model_validate_json(
    (ROOT / "business_task_catalog.json").read_text(encoding="utf-8")
)
RETURN_QUESTION = "현재 반품 가능 기간은 며칠인가요?"


def approval_payload(**overrides: object) -> dict:
    approval = {
        "approval_id": "CUSTOMER_RETURN_V1",
        "dataset_profile": "mini",
        "task_id": "TASK_POLICY_RETURN_WINDOW",
        "owner_role": "고객지원 정책 담당자",
        "success_criteria": ["현행 반품 가능 기간과 근거를 함께 반환한다."],
        "approval_scope": "CUSTOMER",
        "approved_by_role": "고객 업무 책임자",
        "approved_at": "2026-09-28",
        "question_sha256": question_sha256(RETURN_QUESTION),
    }
    approval.update(overrides)
    return {
        "schema_version": "ax-business-task-approvals-v1",
        "approvals": [approval],
    }


class RecordingRunner:
    def __init__(self) -> None:
        self.requests = []

    def run(self, request: RunRequest, *, run_id: str, results_root: Path) -> None:
        self.requests.append(request)
        ResultStore(results_root).write(DeliveryEnvelope(
            delivery_status="DELIVERED",
            run_id=run_id,
            dataset=request.dataset,
            task_id=request.task_id,
            model=request.model,
            payload=SubmitAnswerInput(
                status="ANSWERED",
                answer="30일",
                answer_kind="EXACT_TEXT",
                explanation="승인된 업무 질문으로 실행한 테스트 답변입니다.",
                source_ids=["SOURCE_TEST"],
            ),
            source_link_status="NOT_CHECKED",
        ))


def write_registry(path: Path, payload: dict) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return path


def test_registry_rejects_duplicate_scope_and_stale_question() -> None:
    duplicate = approval_payload()
    duplicate["approvals"].append({
        **duplicate["approvals"][0], "approval_id": "CUSTOMER_RETURN_V2"
    })
    with pytest.raises(ValueError, match="one approval"):
        BusinessTaskApprovalRegistry.model_validate(duplicate)

    stale = BusinessTaskApprovalRegistry.model_validate(
        approval_payload(question_sha256="0" * 64)
    )
    with pytest.raises(ValueError, match="is stale"):
        validate_approval_registry(stale, CATALOG)


def test_verified_task_is_scoped_resolved_and_executable(tmp_path: Path) -> None:
    approval_path = write_registry(tmp_path / "approvals.json", approval_payload())
    runner = RecordingRunner()
    client = TestClient(create_app(
        results_root=tmp_path / "results",
        runner=runner,
        task_approval_path=approval_path,
    ))

    tasks = client.get("/api/tasks/mini")
    assert tasks.status_code == 200
    assert tasks.json()["catalog_status"] == "VERIFIED_TASKS_AVAILABLE"
    approved = next(
        item for item in tasks.json()["tasks"]
        if item["task_id"] == "TASK_POLICY_RETURN_WINDOW"
    )
    assert approved["status"] == "VERIFIED"
    assert approved["approval"] == {
        "approval_id": "CUSTOMER_RETURN_V1",
        "owner_role": "고객지원 정책 담당자",
        "success_criteria": ["현행 반품 가능 기간과 근거를 함께 반환한다."],
        "approval_scope": "CUSTOMER",
        "approved_by_role": "고객 업무 책임자",
        "approved_at": "2026-09-28",
    }
    assert next(
        item for item in tasks.json()["tasks"]
        if item["task_id"] == "TASK_ORDER_MONTHLY_AMOUNT"
    )["approval"] is None

    onboarding = client.get("/api/onboarding/mini").json()
    review = next(
        item for item in onboarding["checks"]
        if item["code"] == "BUSINESS_TASK_REVIEW"
    )
    assert (review["observed"], review["total"], review["status"]) == (1, 10, "WARN")

    response = client.post("/api/run", json={
        "dataset": "mini",
        "request_type": "VERIFIED_BUSINESS_TASK",
        "task_id": "TASK_POLICY_RETURN_WINDOW",
        "run_id": "approved-run",
    })
    assert response.status_code == 200
    assert response.json()["task_id"] == "TASK_POLICY_RETURN_WINDOW"
    assert len(runner.requests) == 1
    assert runner.requests[0].request_type == "VERIFIED_BUSINESS_TASK"
    assert runner.requests[0].question == RETURN_QUESTION
    context = json.loads(
        (tmp_path / "results" / "approved-run" / "run-context.json")
        .read_text(encoding="utf-8")
    )
    assert context["task_label"] == RETURN_QUESTION


def test_verified_task_fails_closed_outside_approved_dataset(tmp_path: Path) -> None:
    approval_path = write_registry(tmp_path / "approvals.json", approval_payload())
    runner = RecordingRunner()
    client = TestClient(create_app(
        results_root=tmp_path / "results",
        runner=runner,
        task_approval_path=approval_path,
    ))

    response = client.post("/api/run", json={
        "dataset": "demo-return-after",
        "request_type": "VERIFIED_BUSINESS_TASK",
        "task_id": "TASK_POLICY_RETURN_WINDOW",
    })
    assert response.status_code == 409
    assert response.json()["detail"] == "VERIFIED_TASK_NOT_ONBOARDED"
    assert runner.requests == []
    assert not (tmp_path / "results").exists()


def test_app_startup_rejects_stale_approval(tmp_path: Path) -> None:
    approval_path = write_registry(
        tmp_path / "approvals.json",
        approval_payload(question_sha256="f" * 64),
    )
    with pytest.raises(ValueError, match="is stale"):
        create_app(
            results_root=tmp_path / "results",
            task_approval_path=approval_path,
        )
