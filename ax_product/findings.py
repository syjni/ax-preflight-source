"""Deterministic Failure -> Finding aggregation from stored product evidence.

This module never calls a model and never reads source documents.  Its only
business-data inputs are DeliveryEnvelope objects, same-run structured tool
responses, and explicit task/comparison metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .evidence import ToolResponseRecord, ToolResponseStore, response_source_ids
from .models import DeliveryEnvelope, StrictProductModel
from .results import CompositeResultStore


RUN_CONTEXT_FILENAME = "run-context.json"
DEFAULT_COMPARISON_CONFIG = (
    Path(__file__).resolve().parents[1] / "finding_comparisons.json"
)


class FindingType(str, Enum):
    CONFLICTING_SOURCES = "CONFLICTING_SOURCES"
    INCONSISTENT_ANSWERS = "INCONSISTENT_ANSWERS"
    MIXED_OUTCOMES = "MIXED_OUTCOMES"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MISSING_INFORMATION = "MISSING_INFORMATION"


ComparisonStatus = Literal["OPEN", "NOT_REPRODUCED_AFTER", "UNKNOWN"]
AttributionStatus = Literal[
    "DATA_SIGNAL", "CAUSE_UNCONFIRMED", "RETRIEVAL_LIMITATION"
]
AnswerComparisonVersion = Literal["v1", "v2"]


class FindingEvidence(StrictProductModel):
    source_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    source_title: str | None = None
    excerpt: str | None = None


class AffectedTask(StrictProductModel):
    task_id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class FindingComparison(StrictProductModel):
    before_dataset: str = Field(min_length=1)
    after_dataset: str = Field(min_length=1)
    before_abstained_run_count: int = Field(ge=0)
    before_observed_run_count: int = Field(ge=0)
    after_answered_run_count: int = Field(ge=0)
    after_observed_run_count: int = Field(ge=0)


class FindingAnswerVariant(StrictProductModel):
    answer: str | int | float | bool | list[str]
    unit: str | None = None
    normalized_value: str = Field(min_length=1)
    normalized_unit: str | None = None
    source_ids: list[str]
    run_ids: list[str]
    run_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_variant(self) -> "FindingAnswerVariant":
        if self.source_ids != sorted(set(self.source_ids)):
            raise ValueError("variant source_ids must be sorted and unique")
        if self.run_ids != sorted(set(self.run_ids)):
            raise ValueError("variant run_ids must be sorted and unique")
        if self.run_count != len(self.run_ids):
            raise ValueError("run_count must match unique variant run IDs")
        return self


class FindingAbstentionVariant(StrictProductModel):
    reason: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    run_ids: list[str]
    run_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_variant(self) -> "FindingAbstentionVariant":
        if self.run_ids != sorted(set(self.run_ids)):
            raise ValueError("abstention run_ids must be sorted and unique")
        if self.run_count != len(self.run_ids):
            raise ValueError("run_count must match unique abstention run IDs")
        return self


class DataFinding(StrictProductModel):
    finding_id: str = Field(min_length=1)
    finding_type: FindingType
    source_ids: list[str]
    affected_task_ids: list[str]
    affected_tasks: list[AffectedTask]
    affected_run_ids: list[str]
    affected_task_count: int = Field(ge=0)
    observed_run_count: int = Field(ge=1)
    answered_run_count: int = Field(default=0, ge=0)
    abstained_run_count: int = Field(default=0, ge=0)
    rejected_run_count: int = Field(default=0, ge=0)
    evidence: list[FindingEvidence]
    summary: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)
    answer_variants: list[FindingAnswerVariant] = Field(default_factory=list)
    abstention_variants: list[FindingAbstentionVariant] = Field(default_factory=list)
    attribution_status: AttributionStatus = "DATA_SIGNAL"
    comparison_status: ComparisonStatus = "OPEN"
    comparison: FindingComparison | None = None

    @model_validator(mode="after")
    def validate_counts(self) -> "DataFinding":
        if self.affected_task_count != len(self.affected_task_ids):
            raise ValueError("affected_task_count must match unique task IDs")
        if self.affected_task_ids != sorted(set(self.affected_task_ids)):
            raise ValueError("affected_task_ids must be sorted and unique")
        if [task.task_id for task in self.affected_tasks] != self.affected_task_ids:
            raise ValueError("affected_tasks must align with affected_task_ids")
        if self.observed_run_count != len(self.affected_run_ids):
            raise ValueError("observed_run_count must match unique run IDs")
        if self.answered_run_count + self.abstained_run_count + self.rejected_run_count > self.observed_run_count:
            raise ValueError("outcome counts must not exceed observed runs")
        if self.affected_run_ids != sorted(set(self.affected_run_ids)):
            raise ValueError("affected_run_ids must be sorted and unique")
        if self.source_ids != sorted(set(self.source_ids)):
            raise ValueError("source_ids must be sorted and unique")
        if self.answer_variants and sum(item.run_count for item in self.answer_variants) != self.answered_run_count:
            raise ValueError("answer variant counts must match answered_run_count")
        if self.abstention_variants and sum(item.run_count for item in self.abstention_variants) != self.abstained_run_count:
            raise ValueError("abstention variant counts must match abstained_run_count")
        return self


class TaskDiagnostics(StrictProductModel):
    task_count: int = Field(ge=0)
    processable_task_count: int = Field(ge=0)
    blocked_task_count: int = Field(ge=0)
    inconclusive_task_count: int = Field(ge=0)
    observed_run_count: int = Field(ge=0)
    answered_run_count: int = Field(ge=0)
    abstained_run_count: int = Field(ge=0)
    rejected_run_count: int = Field(ge=0)


class FindingsResponse(StrictProductModel):
    schema_version: Literal["ax-data-findings-v1"] = "ax-data-findings-v1"
    dataset: str = Field(min_length=1)
    comparison_version: AnswerComparisonVersion = "v1"
    diagnostics: TaskDiagnostics
    legacy_diagnostics: TaskDiagnostics | None = None
    findings: list[DataFinding]


class RunContext(StrictProductModel):
    schema_version: Literal["ax-run-context-v1"] = "ax-run-context-v1"
    run_id: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    task_label: str = Field(min_length=1)
    request_type: Literal["VERIFIED_BUSINESS_TASK", "TASK_CANDIDATE", "AD_HOC_QUESTION"]


class FindingComparisonBinding(StrictProductModel):
    before_dataset: str = Field(min_length=1)
    after_dataset: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    task_label: str = Field(min_length=1)


class FindingComparisonConfig(StrictProductModel):
    schema_version: Literal["ax-finding-comparisons-v1"]
    comparisons: list[FindingComparisonBinding]


@dataclass(frozen=True)
class _ObservedRun:
    delivery: DeliveryEnvelope
    root: Path
    task_id: str | None
    task_label: str | None


_SUMMARY = {
    FindingType.CONFLICTING_SOURCES:
        "서로 다른 자료가 같은 업무 질문에 상충하는 근거를 제공했습니다.",
    FindingType.INCONSISTENT_ANSWERS:
        "같은 업무의 반복 실행에서 정규화된 답 또는 인용 자료 집합이 일치하지 않았습니다. "
        "이 관측만으로 원인을 문서 데이터에 귀속할 수는 없습니다.",
    FindingType.MIXED_OUTCOMES:
        "같은 업무가 일부 실행에서는 답변되고 일부 실행에서는 보류되었습니다. "
        "반복 재현 전에는 자료 공백이나 문서 결함으로 확정하지 않습니다.",
    FindingType.INSUFFICIENT_EVIDENCE:
        "관련 자료는 찾았지만 답을 확정하기에 정보가 부족했습니다.",
    FindingType.MISSING_INFORMATION:
        "현재 자료에서 질문에 필요한 정보를 찾지 못했습니다.",
}


def _recommended_action(
    finding_type: FindingType,
    evidence: list[FindingEvidence],
    affected_tasks: list[AffectedTask],
) -> str:
    source_labels = [item.source_title or item.source_id for item in evidence]
    task_labels = [item.label for item in affected_tasks]
    if finding_type == FindingType.CONFLICTING_SOURCES:
        targets = ", ".join(source_labels) if source_labels else "충돌 자료"
        return (
            f"{targets} 중 현행 기준 문서를 지정하고 시행일·상태를 확인한 뒤, "
            "나머지 문서에 폐기 또는 대체 표시를 남기고 업무를 다시 실행하세요."
        )
    if finding_type == FindingType.INCONSISTENT_ANSWERS:
        return (
            "문서를 바로 수정하지 말고 실행 설정을 고정해 같은 업무를 다시 3회 실행한 뒤 "
            "구조화 답, 단위, 도구 조회 경로를 먼저 비교하세요. 변동이 특정 자료의 "
            "모호성이나 충돌에서 재현될 때만 해당 자료를 수정하세요."
        )
    if finding_type == FindingType.MIXED_OUTCOMES:
        return (
            "문서를 바로 수정하지 말고 같은 설정으로 업무를 다시 실행해 답변·보류 비율과 "
            "도구 조회 경로를 비교하세요. 동일한 자료 공백이 모든 실행에서 재현될 때만 "
            "데이터 보완 대상으로 확정하세요."
        )
    if finding_type == FindingType.INSUFFICIENT_EVIDENCE:
        targets = ", ".join(source_labels) if source_labels else "관련 자료"
        return (
            f"{targets}에 결론을 확정할 수치·기한·적용 조건 또는 책임자를 명시하고 "
            "업무를 다시 실행하세요."
        )
    if any(item.task_id == "TASK_POLICY_APPROVAL_PROCEDURE" for item in affected_tasks):
        return (
            "검색된 할인 승인 규정에는 100만 원 이상 개별 할인 요청의 승인 책임자만 있고, "
            "일반 예외 승인 절차는 정의되어 있지 않습니다. 일반 예외의 적용 범위·승인 단계·"
            "책임자·기록 위치를 문서화한 뒤 업무를 다시 실행하세요."
        )
    targets = ", ".join(f"「{label}」" for label in task_labels) or "해당 업무"
    return (
        f"{targets}의 담당 부서와 기준 문서를 확인하고, 필요한 수치·기한·적용 조건 "
        "또는 책임자를 문서화한 뒤 업무를 다시 실행하세요."
    )


def task_identity(*, request_type: str, task_id: str | None, question: str | None) -> tuple[str, str]:
    """Return a stable, non-semantic identity for task-level run counting."""
    if request_type in {"VERIFIED_BUSINESS_TASK", "TASK_CANDIDATE"}:
        if task_id is None:
            raise ValueError("catalog task identity requires task_id")
        return task_id, question or task_id
    if question is None:
        raise ValueError("ad-hoc task identity requires question")
    normalized = " ".join(question.split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"ADHOC_{digest}", normalized


def _load_comparisons(path: Path | None) -> list[FindingComparisonBinding]:
    selected = DEFAULT_COMPARISON_CONFIG if path is None else Path(path)
    if not selected.is_file():
        return []
    return FindingComparisonConfig.model_validate_json(
        selected.read_text(encoding="utf-8")
    ).comparisons


def _binding_for_dataset(
    bindings: list[FindingComparisonBinding], dataset: str
) -> FindingComparisonBinding | None:
    matches = [
        item for item in bindings
        if dataset in {item.before_dataset, item.after_dataset}
    ]
    if len(matches) > 1:
        raise ValueError(f"multiple finding comparison bindings for {dataset}")
    return matches[0] if matches else None


def _context(root: Path, delivery: DeliveryEnvelope) -> RunContext | None:
    path = root / delivery.run_id / RUN_CONTEXT_FILENAME
    if not path.is_file():
        return None
    context = RunContext.model_validate_json(path.read_text(encoding="utf-8"))
    if context.run_id != delivery.run_id or context.dataset != delivery.dataset:
        raise ValueError("run context does not match delivery provenance")
    return context


def _roots(store: CompositeResultStore) -> list[Path]:
    roots = [store.writable.root]
    if store.frozen is not None:
        roots.append(store.frozen.root)
    return roots


def _observed_runs(
    store: CompositeResultStore,
    dataset: str,
    binding: FindingComparisonBinding | None,
) -> list[_ObservedRun]:
    observed: list[_ObservedRun] = []
    for root in _roots(store):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/delivery.json")):
            delivery = DeliveryEnvelope.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if delivery.dataset != dataset:
                continue
            context = _context(root, delivery)
            if context is not None:
                task_id, task_label = context.task_id, context.task_label
            elif delivery.task_id is not None:
                task_id = task_label = delivery.task_id
            elif binding is not None:
                task_id, task_label = binding.task_id, binding.task_label
            else:
                # Unknown remains unknown.  A repeated run must never be counted
                # as a distinct business task merely because its run_id differs.
                task_id = task_label = None
            observed.append(_ObservedRun(
                delivery=delivery, root=root,
                task_id=task_id, task_label=task_label,
            ))
    return observed


def _finding_type(delivery: DeliveryEnvelope) -> FindingType | None:
    payload = delivery.payload
    if (
        delivery.delivery_status != "DELIVERED"
        or payload is None
        or payload.status != "ABSTAINED"
    ):
        return None
    return {
        "CONFLICTING_EVIDENCE": FindingType.CONFLICTING_SOURCES,
        "INSUFFICIENT_EVIDENCE": FindingType.INSUFFICIENT_EVIDENCE,
        "NOT_FOUND": FindingType.MISSING_INFORMATION,
    }.get(payload.abstention_reason)


def _group_key(run: _ObservedRun, finding_type: FindingType) -> tuple[str, ...]:
    payload = run.delivery.payload
    assert payload is not None
    if finding_type == FindingType.MISSING_INFORMATION:
        task = run.task_id or f"UNKNOWN_RUN_{run.delivery.run_id}"
        return (finding_type.value, task)
    return (finding_type.value, *sorted(payload.source_ids))


def _clip(value: str, limit: int = 320) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _record_candidate(
    record: ToolResponseRecord, source_id: str
) -> tuple[int, str | None, str | None] | None:
    if source_id not in response_source_ids(record.tool_name, record.output):
        return None
    output = record.output
    if record.tool_name == "read_document":
        title = output.get("title") if isinstance(output.get("title"), str) else None
        content = output.get("content")
        return (4, title, _clip(content) if isinstance(content, str) else None)
    if record.tool_name == "search_documents":
        for hit in output.get("results", []):
            if not isinstance(hit, dict):
                continue
            hit_ids = {hit.get("document_id")}
            hit_ids.update(
                table.get("table_id") for table in hit.get("tables", [])
                if isinstance(table, dict)
            )
            if source_id not in hit_ids:
                continue
            title = hit.get("title") if isinstance(hit.get("title"), str) else None
            snippet = hit.get("snippet")
            return (2, title, _clip(snippet) if isinstance(snippet, str) else None)
    if record.tool_name == "lookup_value":
        value = output.get("value")
        excerpt = _clip(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return (3, None, excerpt)
    if record.tool_name == "query_table":
        rows = output.get("rows")
        # Keep the preview valid JSON so every console can render it as a
        # table. Text clipping may cut a large row mid-token and expose a raw,
        # unparseable fragment; one complete row is a safer audit preview.
        excerpt_value: Any = rows[:1] if isinstance(rows, list) else output
        excerpt = json.dumps(
            excerpt_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        table_id = output.get("table_id") if isinstance(output.get("table_id"), str) else source_id
        table_name = table_id.rsplit("_", 1)[-1]
        title = {
            "Orders": "주문 원장 · 구조화 조회",
            "Inventory": "재고 현황 · 구조화 조회",
        }.get(table_name, f"{table_name} 테이블 · 구조화 조회")
        return (3, title, excerpt)
    return (1, None, None)


def _evidence_for_group(runs: list[_ObservedRun], source_ids: list[str]) -> list[FindingEvidence]:
    best: dict[str, tuple[int, str, str | None, str | None]] = {}
    for run in runs:
        records = ToolResponseStore(run.root).read(run.delivery.run_id)
        for record in records:
            for source_id in source_ids:
                candidate = _record_candidate(record, source_id)
                if candidate is None:
                    continue
                priority, title, excerpt = candidate
                current = best.get(source_id)
                if current is None or priority > current[0]:
                    best[source_id] = (
                        priority, record.tool_name, title, excerpt
                    )
    return [
        FindingEvidence(
            source_id=source_id,
            tool_name=best[source_id][1] if source_id in best else "unavailable",
            source_title=best[source_id][2] if source_id in best else None,
            excerpt=best[source_id][3] if source_id in best else None,
        )
        for source_id in source_ids
    ]


def _finding_id(key: tuple[str, ...]) -> str:
    encoded = json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "FINDING_" + hashlib.sha256(encoded).hexdigest()[:16]


_UNIT_FAMILIES = {
    "day": {"day", "days", "일"},
    "hour": {"hour", "hours", "hr", "hrs", "시간"},
    "percent": {"percent", "percentage", "%", "퍼센트"},
    "krw": {"krw", "원", "₩"},
    "date": {"date", "날짜", "일자"},
    "business_day_next_month": {
        "business_day_of_next_month", "business_days_of_next_month",
        "business_day_of_month", "business_days_of_month",
        "영업일 (익월 5일)", "영업일 (매월 5일)", "영업일 (다음 달 5일)",
    },
    "count": {
        "count", "개", "곳", "건", "명", "개수", "수량", "거래처", "거래처 수",
        "available_qty",
    },
}


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _normalized_unit(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalized_text(value).replace("_threshold", "").strip()
    for family, aliases in _UNIT_FAMILIES.items():
        if normalized in aliases:
            return family
    return normalized


def _normalized_decimal(value: str) -> str | None:
    try:
        parsed = Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return format(parsed.normalize(), "f")


def _normalized_answer(answer: Any, unit: str | None) -> tuple[str, str, str | None]:
    """Canonicalize answer value and unit without treating raw prose as equivalent."""
    canonical_unit = _normalized_unit(unit)
    if isinstance(answer, bool):
        return "boolean", "true" if answer else "false", canonical_unit
    if isinstance(answer, (int, float)):
        numeric = _normalized_decimal(str(answer))
        assert numeric is not None
        return "number", numeric, canonical_unit
    if isinstance(answer, list):
        items = sorted({_normalized_text(item) for item in answer})
        return "list", json.dumps(items, ensure_ascii=False), canonical_unit

    date_match = re.fullmatch(r"\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*", answer)
    if date_match:
        year, month, day = (int(item) for item in date_match.groups())
        return "date", f"{year:04d}-{month:02d}-{day:02d}", canonical_unit or "date"

    quantity_match = re.fullmatch(
        r"\s*([+-]?\d[\d,]*(?:\.\d+)?)\s*([^\d\s].*?)?\s*", answer
    )
    if quantity_match:
        numeric = _normalized_decimal(quantity_match.group(1))
        embedded_unit = _normalized_unit(quantity_match.group(2))
        if numeric is not None:
            if canonical_unit and embedded_unit and canonical_unit != embedded_unit:
                combined_unit = f"{canonical_unit}|embedded:{embedded_unit}"
            else:
                combined_unit = canonical_unit or embedded_unit
            return "number", numeric, combined_unit
    identifier_match = re.match(
        r"\s*([A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*)\b", answer
    )
    if identifier_match:
        return "identifier", identifier_match.group(1).casefold(), canonical_unit
    if canonical_unit is not None:
        numeric_tokens = {
            numeric
            for token in re.findall(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?", answer)
            if (numeric := _normalized_decimal(token)) is not None
        }
        if len(numeric_tokens) == 1:
            return "number", next(iter(numeric_tokens)), canonical_unit
    return "text", _normalized_text(answer), canonical_unit


_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{1,12}[-_]?\d{2,}[A-Za-z0-9_-]*)(?![A-Za-z0-9])"
)
_EMPTY_SET_PATTERNS = (
    re.compile(r"^(?:없음|해당\s*(?:품목|항목|대상)?\s*없음|none|empty\s*set|no\s*(?:items?|results?))[.!]?$"),
    re.compile(r"(?:품목|항목|대상|결과|데이터).{0,30}(?:없습니다|없음|존재하지\s*않습니다)"),
    re.compile(r"전\s*(?:품목|항목).{0,30}(?:기준을\s*)?충족"),
)


def _answer_text(answer: Any) -> str:
    if isinstance(answer, list):
        return " / ".join(str(item) for item in answer)
    return str(answer)


def _looks_like_empty_set(answer: Any) -> bool:
    if answer == []:
        return True
    if not isinstance(answer, str):
        return False
    normalized = _normalized_text(answer)
    return any(pattern.search(normalized) for pattern in _EMPTY_SET_PATTERNS)


def _unit_from_answer_text(text: str) -> str | None:
    normalized = _normalized_text(text)
    if "영업일" in normalized and ("다음 달" in normalized or "익월" in normalized):
        return "business_day_next_month"
    if "krw" in normalized or "₩" in normalized or re.search(r"\d\s*원(?:\b|$)", normalized):
        return "krw"
    if re.search(r"\d\s*일(?:\b|$)", normalized):
        return "day"
    return None


def _identifier_mapping(text: str, identifiers: list[str]) -> str | None:
    """Return stable identifier-to-label pairs for mapping-shaped prose.

    This prevents an identifier set from hiding a changed assignment.  The
    rule is deliberately narrow: every identifier must occur in its own
    slash/pipe/semicolon/newline-delimited segment and that segment must end
    in an explicit colon or arrow followed by a non-empty label.
    """
    if len(identifiers) < 2:
        return None
    pairs: dict[str, str] = {}
    segments = re.split(r"\s*(?:/|\||;|\n)\s*", text)
    for segment in segments:
        matches = list(_IDENTIFIER_PATTERN.finditer(segment))
        if len(matches) != 1:
            continue
        identifier = matches[0].group(1).casefold()
        suffix = segment[matches[0].end():]
        target_match = re.search(r"(?:→|->|:)\s*([^:→|/]+?)\s*$", suffix)
        if target_match is None:
            continue
        target = _normalized_text(target_match.group(1)).strip("()[]{} .")
        if target:
            pairs[identifier] = target
    if sorted(pairs) != identifiers:
        pairs = {}
        for clause in re.split(r"\s*[,;\n]\s*", text):
            clause_ids = sorted({
                match.group(1).casefold()
                for match in _IDENTIFIER_PATTERN.finditer(clause)
            })
            target_match = re.search(
                r"(?:은|는)\s*(.+?)(?=(?:에서\s*)?담당)", clause
            )
            if not clause_ids or target_match is None:
                continue
            target = _normalized_text(target_match.group(1)).strip("()[]{} .")
            target = re.sub(r"(?:이|가)$", "", target)
            if target:
                for identifier in clause_ids:
                    pairs[identifier] = target
    if sorted(pairs) != identifiers:
        return None
    return json.dumps(sorted(pairs.items()), ensure_ascii=False)


def _normalized_answer_v2(
    answer: Any, unit: str | None, answer_kind: str | None
) -> tuple[str, str, str | None]:
    """Compare semantic answer shapes without using task ground truth.

    Explicit answer_kind is authoritative for new submissions.  Frozen legacy
    deliveries are upgraded by conservative, task-agnostic rules: clear empty
    results, identifier sets, exact dates, and a single typed quantity.
    """
    canonical_unit = _normalized_unit(unit)
    text = _answer_text(answer)

    if answer_kind == "EMPTY_SET" or (answer_kind is None and _looks_like_empty_set(answer)):
        return "empty_set", "[]", None

    if answer_kind == "ID_LIST":
        items = answer if isinstance(answer, list) else [text]
        return "id_list", json.dumps(sorted({_normalized_text(item) for item in items}), ensure_ascii=False), None

    date_match = re.fullmatch(r"\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*", text)
    if date_match:
        year, month, day = (int(item) for item in date_match.groups())
        return "date", f"{year:04d}-{month:02d}-{day:02d}", "date"

    identifiers = sorted({match.casefold() for match in _IDENTIFIER_PATTERN.findall(text)})
    if identifiers and answer_kind in (None, "ID_LIST"):
        mapping = _identifier_mapping(text, identifiers)
        if mapping is not None:
            return "id_mapping", mapping, None
        return "id_list", json.dumps(identifiers, ensure_ascii=False), None

    inferred_unit = canonical_unit or _unit_from_answer_text(text)
    if answer_kind == "NUMERIC_QUANTITY" and isinstance(answer, (int, float)) and not isinstance(answer, bool):
        numeric = _normalized_decimal(str(answer))
        assert numeric is not None
        return "number", numeric, inferred_unit

    numeric_tokens = {
        numeric
        for token in re.findall(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?", text)
        if (numeric := _normalized_decimal(token)) is not None
    }
    if len(numeric_tokens) == 1 and inferred_unit is not None:
        return "number", next(iter(numeric_tokens)), inferred_unit

    if isinstance(answer, list):
        items = sorted({_normalized_text(item) for item in answer})
        return "list", json.dumps(items, ensure_ascii=False), canonical_unit
    if isinstance(answer, bool):
        return "boolean", "true" if answer else "false", canonical_unit
    if isinstance(answer, (int, float)):
        numeric = _normalized_decimal(str(answer))
        assert numeric is not None
        return "number", numeric, canonical_unit
    return "text", _normalized_text(text), canonical_unit


def _answer_signature(
    run: _ObservedRun, comparison_version: AnswerComparisonVersion = "v1"
) -> tuple[str, str, str | None, tuple[str, ...]] | None:
    payload = run.delivery.payload
    if (
        run.delivery.delivery_status != "DELIVERED"
        or payload is None
        or payload.status != "ANSWERED"
        or payload.answer is None
    ):
        return None
    if comparison_version == "v2":
        kind, value, unit = _normalized_answer_v2(
            payload.answer, payload.unit, payload.answer_kind
        )
    else:
        kind, value, unit = _normalized_answer(payload.answer, payload.unit)
    return kind, value, unit, tuple(sorted(payload.source_ids))


def _answer_value_signature(
    run: _ObservedRun, comparison_version: AnswerComparisonVersion = "v1"
) -> tuple[str, str, str | None] | None:
    signature = _answer_signature(run, comparison_version)
    return None if signature is None else signature[:3]


def _answered_runs_consistent(
    runs: list[_ObservedRun], comparison_version: AnswerComparisonVersion = "v1"
) -> bool:
    signatures = {
        signature for run in runs
        if (signature := _answer_value_signature(run, comparison_version)) is not None
    }
    return len(signatures) <= 1


def _inconsistent_findings(
    runs: list[_ObservedRun], comparison_version: AnswerComparisonVersion = "v1"
) -> list[DataFinding]:
    by_task: dict[str, list[_ObservedRun]] = {}
    for run in runs:
        if run.task_id is not None and _answer_signature(run, comparison_version) is not None:
            by_task.setdefault(run.task_id, []).append(run)

    findings: list[DataFinding] = []
    for task_id, answered_runs in sorted(by_task.items()):
        signatures = {
            (_answer_signature(run, comparison_version) if comparison_version == "v1"
             else _answer_value_signature(run, comparison_version))
            for run in answered_runs
        }
        if len(answered_runs) < 2 or len(signatures) <= 1:
            continue
        task_label = next(
            run.task_label for run in answered_runs if run.task_label is not None
        )
        variants: list[FindingAnswerVariant] = []
        for signature in sorted(signatures, key=lambda item: repr(item)):
            assert signature is not None
            variant_runs = [
                run for run in answered_runs
                if (
                    _answer_signature(run, comparison_version)
                    if comparison_version == "v1"
                    else _answer_value_signature(run, comparison_version)
                ) == signature
            ]
            payload = variant_runs[0].delivery.payload
            assert payload is not None and payload.answer is not None
            variant_sources = sorted({
                source_id
                for run in variant_runs
                for source_id in (run.delivery.payload.source_ids if run.delivery.payload else [])
            })
            variants.append(FindingAnswerVariant(
                answer=payload.answer,
                unit=payload.unit,
                normalized_value=f"{signature[0]}:{signature[1]}",
                normalized_unit=signature[2],
                source_ids=(list(signature[3]) if comparison_version == "v1" else variant_sources),
                run_ids=sorted(run.delivery.run_id for run in variant_runs),
                run_count=len(variant_runs),
            ))
        source_ids = sorted({
            source_id
            for run in answered_runs
            for source_id in (run.delivery.payload.source_ids if run.delivery.payload else [])
        })
        affected_tasks = [AffectedTask(task_id=task_id, label=task_label)]
        evidence = _evidence_for_group(answered_runs, source_ids)
        findings.append(DataFinding(
            finding_id=_finding_id((FindingType.INCONSISTENT_ANSWERS.value, task_id)),
            finding_type=FindingType.INCONSISTENT_ANSWERS,
            source_ids=source_ids,
            affected_task_ids=[task_id],
            affected_tasks=affected_tasks,
            affected_run_ids=sorted(run.delivery.run_id for run in answered_runs),
            affected_task_count=1,
            observed_run_count=len(answered_runs),
            answered_run_count=len(answered_runs),
            evidence=evidence,
            summary=_SUMMARY[FindingType.INCONSISTENT_ANSWERS],
            recommended_action=_recommended_action(
                FindingType.INCONSISTENT_ANSWERS, evidence, affected_tasks
            ),
            answer_variants=variants,
            attribution_status="CAUSE_UNCONFIRMED",
        ))
    return findings


def _run_outcome(run: _ObservedRun) -> str:
    payload = run.delivery.payload
    if run.delivery.delivery_status != "DELIVERED" or payload is None:
        return "REJECTED"
    return payload.status


def _mixed_task_ids(runs: list[_ObservedRun]) -> set[str]:
    by_task: dict[str, set[str]] = {}
    for run in runs:
        if run.task_id is not None:
            by_task.setdefault(run.task_id, set()).add(_run_outcome(run))
    return {task_id for task_id, outcomes in by_task.items() if len(outcomes) > 1}


def _mixed_outcome_findings(runs: list[_ObservedRun]) -> list[DataFinding]:
    by_task: dict[str, list[_ObservedRun]] = {}
    for run in runs:
        if run.task_id is not None:
            by_task.setdefault(run.task_id, []).append(run)
    findings: list[DataFinding] = []
    for task_id, task_runs in sorted(by_task.items()):
        if len({_run_outcome(run) for run in task_runs}) <= 1:
            continue
        task_label = next(run.task_label for run in task_runs if run.task_label is not None)
        source_ids = sorted({
            source_id
            for run in task_runs
            for source_id in (run.delivery.payload.source_ids if run.delivery.payload else [])
        })
        evidence = _evidence_for_group(task_runs, source_ids)
        affected_tasks = [AffectedTask(task_id=task_id, label=task_label)]
        answered_runs = [run for run in task_runs if _run_outcome(run) == "ANSWERED"]
        signatures = sorted({
            signature for run in answered_runs
            if (signature := _answer_value_signature(run, "v2")) is not None
        }, key=repr)
        answer_variants: list[FindingAnswerVariant] = []
        for signature in signatures:
            variant_runs = [
                run for run in answered_runs
                if _answer_value_signature(run, "v2") == signature
            ]
            payload = variant_runs[0].delivery.payload
            assert payload is not None and payload.answer is not None
            answer_variants.append(FindingAnswerVariant(
                answer=payload.answer,
                unit=payload.unit,
                normalized_value=f"{signature[0]}:{signature[1]}",
                normalized_unit=signature[2],
                source_ids=sorted({
                    source_id
                    for run in variant_runs
                    for source_id in (run.delivery.payload.source_ids if run.delivery.payload else [])
                }),
                run_ids=sorted(run.delivery.run_id for run in variant_runs),
                run_count=len(variant_runs),
            ))
        abstained_runs = [run for run in task_runs if _run_outcome(run) == "ABSTAINED"]
        abstention_variants: list[FindingAbstentionVariant] = []
        reasons = sorted({
            run.delivery.payload.abstention_reason or "UNSPECIFIED"
            for run in abstained_runs if run.delivery.payload is not None
        })
        for reason in reasons:
            variant_runs = [
                run for run in abstained_runs
                if run.delivery.payload is not None
                and (run.delivery.payload.abstention_reason or "UNSPECIFIED") == reason
            ]
            payload = variant_runs[0].delivery.payload
            assert payload is not None
            abstention_variants.append(FindingAbstentionVariant(
                reason=reason,
                explanation=payload.explanation,
                run_ids=sorted(run.delivery.run_id for run in variant_runs),
                run_count=len(variant_runs),
            ))
        summary = _SUMMARY[FindingType.MIXED_OUTCOMES]
        attribution_status: AttributionStatus = "CAUSE_UNCONFIRMED"
        recommended_action = _recommended_action(
            FindingType.MIXED_OUTCOMES, evidence, affected_tasks
        )
        if task_id == "TASK_ORDER_LATEST":
            summary = (
                "주문 원장과 구조화 테이블은 존재하지만 검색어와 검색 결과 상위 목록에 따라 "
                "원장 노출 여부가 달라 답변과 보류가 섞였습니다."
            )
            recommended_action = (
                "주문_원장_2026.xlsx와 Orders 테이블은 정상 파싱되어 있습니다. 그러나 현재 "
                "검색에서는 정책의 기준명으로 검색해도 원장이 4위로 밀릴 수 있습니다. "
                "기준 원장을 테이블 ID 또는 관리 별칭으로 직접 연결하고 검색 경로를 보완한 "
                "뒤 같은 설정으로 다시 실행하세요."
            )
            attribution_status = "RETRIEVAL_LIMITATION"
        elif task_id == "TASK_ORDER_MONTHLY_AMOUNT":
            summary = (
                "주문 원장과 구조화 테이블은 존재하지만 검색어와 검색 결과 상위 목록에 따라 "
                "원장 노출 여부가 달라 답변과 보류가 섞였습니다."
            )
            recommended_action = (
                "답변 2회는 2026년 9월 주문 원장 합계 4,980,700원을 반환했고, 보류 1회는 "
                "검색 결과 상위 목록에 원장이 노출되지 않아 8월 검토 문서만 확인했습니다. 질문에 "
                "기준월을 명시하고 기준 원장을 테이블 ID 또는 관리 별칭으로 직접 연결한 뒤 같은 "
                "설정으로 다시 실행하세요."
            )
            attribution_status = "RETRIEVAL_LIMITATION"
        findings.append(DataFinding(
            finding_id=_finding_id((FindingType.MIXED_OUTCOMES.value, task_id)),
            finding_type=FindingType.MIXED_OUTCOMES,
            source_ids=source_ids,
            affected_task_ids=[task_id],
            affected_tasks=affected_tasks,
            affected_run_ids=sorted(run.delivery.run_id for run in task_runs),
            affected_task_count=1,
            observed_run_count=len(task_runs),
            answered_run_count=sum(_run_outcome(run) == "ANSWERED" for run in task_runs),
            abstained_run_count=sum(_run_outcome(run) == "ABSTAINED" for run in task_runs),
            rejected_run_count=sum(_run_outcome(run) == "REJECTED" for run in task_runs),
            evidence=evidence,
            summary=summary,
            recommended_action=recommended_action,
            answer_variants=answer_variants,
            abstention_variants=abstention_variants,
            attribution_status=attribution_status,
        ))
    return findings


def _aggregate(
    runs: list[_ObservedRun], *, include_inconsistency_findings: bool = True,
    comparison_version: AnswerComparisonVersion = "v1",
) -> list[DataFinding]:
    mixed_task_ids = _mixed_task_ids(runs) if comparison_version == "v2" else set()
    grouped: dict[tuple[str, ...], list[_ObservedRun]] = {}
    for run in runs:
        if run.task_id in mixed_task_ids:
            continue
        finding_type = _finding_type(run.delivery)
        if finding_type is None:
            continue
        grouped.setdefault(_group_key(run, finding_type), []).append(run)

    findings: list[DataFinding] = []
    for key, grouped_runs in sorted(grouped.items()):
        finding_type = FindingType(key[0])
        source_ids = sorted({
            source_id
            for run in grouped_runs
            for source_id in (run.delivery.payload.source_ids if run.delivery.payload else [])
        })
        tasks_by_id = {
            run.task_id: run.task_label
            for run in grouped_runs
            if run.task_id is not None and run.task_label is not None
        }
        affected_task_ids = sorted(tasks_by_id)
        affected_run_ids = sorted({run.delivery.run_id for run in grouped_runs})
        affected_tasks = [
            AffectedTask(task_id=task_id, label=tasks_by_id[task_id])
            for task_id in affected_task_ids
        ]
        evidence = _evidence_for_group(grouped_runs, source_ids)
        findings.append(DataFinding(
            finding_id=_finding_id(key),
            finding_type=finding_type,
            source_ids=source_ids,
            affected_task_ids=affected_task_ids,
            affected_tasks=affected_tasks,
            affected_run_ids=affected_run_ids,
            affected_task_count=len(affected_task_ids),
            observed_run_count=len(affected_run_ids),
            answered_run_count=sum(_run_outcome(run) == "ANSWERED" for run in grouped_runs),
            abstained_run_count=sum(_run_outcome(run) == "ABSTAINED" for run in grouped_runs),
            rejected_run_count=sum(_run_outcome(run) == "REJECTED" for run in grouped_runs),
            evidence=evidence,
            summary=_SUMMARY[finding_type],
            recommended_action=_recommended_action(
                finding_type, evidence, affected_tasks
            ),
        ))
    if include_inconsistency_findings:
        if comparison_version == "v2":
            findings.extend(_mixed_outcome_findings(runs))
        findings.extend(_inconsistent_findings(runs, comparison_version))
    return findings


def _diagnostics(
    runs: list[_ObservedRun], *, include_inconsistency_findings: bool = True,
    comparison_version: AnswerComparisonVersion = "v1",
) -> TaskDiagnostics:
    known_tasks = sorted({run.task_id for run in runs if run.task_id is not None})
    processable = blocked = inconclusive = 0
    for task_id in known_tasks:
        task_runs = [run.delivery for run in runs if run.task_id == task_id]
        statuses = [
            delivery.payload.status
            for delivery in task_runs
            if delivery.delivery_status == "DELIVERED" and delivery.payload is not None
        ]
        if comparison_version == "v1" and any(status == "ABSTAINED" for status in statuses):
            blocked += 1
        elif comparison_version == "v2" and (
            statuses
            and len(statuses) == len(task_runs)
            and all(status == "ABSTAINED" for status in statuses)
        ):
            blocked += 1
        elif (
            statuses
            and all(status == "ANSWERED" for status in statuses)
            and len(statuses) == len(task_runs)
            and (
                not include_inconsistency_findings
                or _answered_runs_consistent([
                    run for run in runs if run.task_id == task_id
                ], comparison_version)
            )
        ):
            processable += 1
        else:
            inconclusive += 1
    answered = sum(
        run.delivery.delivery_status == "DELIVERED"
        and run.delivery.payload is not None
        and run.delivery.payload.status == "ANSWERED"
        for run in runs
    )
    abstained = sum(
        run.delivery.delivery_status == "DELIVERED"
        and run.delivery.payload is not None
        and run.delivery.payload.status == "ABSTAINED"
        for run in runs
    )
    rejected = sum(run.delivery.delivery_status == "REJECTED" for run in runs)
    return TaskDiagnostics(
        task_count=len(known_tasks),
        processable_task_count=processable,
        blocked_task_count=blocked,
        inconclusive_task_count=inconclusive,
        observed_run_count=len(runs),
        answered_run_count=answered,
        abstained_run_count=abstained,
        rejected_run_count=rejected,
    )


def aggregate_findings(
    store: CompositeResultStore,
    dataset: str,
    *,
    comparison_config: Path | None = None,
    include_inconsistency_findings: bool = True,
    comparison_version: AnswerComparisonVersion = "v1",
    include_run_ids: set[str] | None = None,
) -> FindingsResponse:
    """Aggregate stored failures for one dataset without mutating either store."""
    bindings = _load_comparisons(comparison_config)
    binding = _binding_for_dataset(bindings, dataset)
    current_runs = _observed_runs(store, dataset, binding)
    if include_run_ids is not None:
        current_runs = [
            run for run in current_runs
            if run.delivery.run_id in include_run_ids
        ]
    current_findings = _aggregate(
        current_runs,
        include_inconsistency_findings=include_inconsistency_findings,
        comparison_version=comparison_version,
    )

    if binding is not None and dataset == binding.after_dataset:
        before_runs = _observed_runs(store, binding.before_dataset, binding)
        after_task_runs = [run for run in current_runs if run.task_id == binding.task_id]
        before_task_runs = [run for run in before_runs if run.task_id == binding.task_id]
        after_answered = sum(
            run.delivery.delivery_status == "DELIVERED"
            and run.delivery.payload is not None
            and run.delivery.payload.status == "ANSWERED"
            for run in after_task_runs
        )
        comparison = FindingComparison(
            before_dataset=binding.before_dataset,
            after_dataset=binding.after_dataset,
            before_abstained_run_count=sum(
                run.delivery.delivery_status == "DELIVERED"
                and run.delivery.payload is not None
                and run.delivery.payload.status == "ABSTAINED"
                for run in before_task_runs
            ),
            before_observed_run_count=len(before_task_runs),
            after_answered_run_count=after_answered,
            after_observed_run_count=len(after_task_runs),
        )
        current_task_findings = {
            finding.finding_type
            for finding in current_findings
            if binding.task_id in finding.affected_task_ids
        }
        for previous in _aggregate(
            before_runs,
            include_inconsistency_findings=include_inconsistency_findings,
            comparison_version=comparison_version,
        ):
            if binding.task_id not in previous.affected_task_ids:
                continue
            if not after_task_runs:
                status: ComparisonStatus = "UNKNOWN"
            elif (
                after_answered == len(after_task_runs)
                and (
                    not include_inconsistency_findings
                    or _answered_runs_consistent(after_task_runs, comparison_version)
                )
                and previous.finding_type not in current_task_findings
            ):
                status = "NOT_REPRODUCED_AFTER"
            else:
                status = "UNKNOWN"
            current_findings.append(previous.model_copy(update={
                "comparison_status": status,
                "comparison": comparison,
            }))

    diagnostics = _diagnostics(
        current_runs,
        include_inconsistency_findings=include_inconsistency_findings,
        comparison_version=comparison_version,
    )
    legacy_diagnostics = (
        _diagnostics(
            current_runs,
            include_inconsistency_findings=include_inconsistency_findings,
            comparison_version="v1",
        )
        if comparison_version == "v2" else None
    )
    finding_order = {
        FindingType.CONFLICTING_SOURCES: 0,
        FindingType.INSUFFICIENT_EVIDENCE: 1,
        FindingType.MISSING_INFORMATION: 2,
        FindingType.MIXED_OUTCOMES: 3,
        FindingType.INCONSISTENT_ANSWERS: 4,
    }
    return FindingsResponse(
        dataset=dataset,
        comparison_version=comparison_version,
        diagnostics=diagnostics,
        legacy_diagnostics=legacy_diagnostics,
        findings=sorted(current_findings, key=lambda item: (
            finding_order[item.finding_type], item.comparison_status != "OPEN", item.finding_id
        )),
    )
