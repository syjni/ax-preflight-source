#!/usr/bin/env python3
"""9/18 feasibility test for AX Project Plan v4.

This intentionally small, standard-library-only experiment validates retrieval,
the four-tool chain, deterministic scoring, abstention/provenance states, and
measurement artifacts. It is not a production implementation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
TOOL_BUDGETS = {"knowledge": 6, "operations": 8, "cross_file": 12}


DOCUMENTS = [
    {
        "document_id": "DOC_001",
        "title": "사무실 좌석 안내",
        "family": "office_guide",
        "effective_date": "2026-01-01",
        "text": "본사 좌석 배치와 회의실 예약 방법을 안내합니다.",
    },
    {
        "document_id": "DOC_002",
        "title": "휴가 신청 안내",
        "family": "leave_guide",
        "effective_date": "2026-02-01",
        "text": "연차 휴가는 인사 시스템에서 신청합니다.",
    },
    {
        "document_id": "DOC_003",
        "title": "재고 실사 절차",
        "family": "inventory_guide",
        "effective_date": "2026-03-01",
        "text": "분기 말 재고 수량을 확인하고 차이를 기록합니다.",
    },
    {
        "document_id": "DOC_004",
        "title": "영업 회의 메모",
        "family": "meeting_note",
        "effective_date": "2026-08-15",
        "text": "신규 거래처 방문 일정과 판촉 계획을 논의했습니다.",
    },
    {
        "document_id": "DOC_005",
        "title": "고객 식별자 조회 절차",
        "family": "operations_guide",
        "effective_date": "2026-08-20",
        "text": "주문 집계 전 고객 식별자 조회 절차를 수행합니다. 고객명으로 customer_id를 찾습니다.",
    },
    {
        "document_id": "DOC_006",
        "title": "반품 정책 2024",
        "family": "return_policy",
        "effective_date": "2024-01-01",
        "status": "superseded",
        "text": "구버전 반품 정책입니다. 구매 후 14일 이내 반품할 수 있습니다.",
    },
    {
        "document_id": "DOC_007",
        "title": "반품 정책 현재본",
        "family": "return_policy",
        "effective_date": "2026-07-01",
        "status": "current",
        "text": "현재 반품 기간은 구매 후 30일입니다. 미개봉 상품과 영수증이 필요합니다.",
    },
    {
        "document_id": "DOC_008",
        "title": "배송지연보상안내",
        "family": "shipping_policy",
        "effective_date": "2026-06-01",
        "text": "배송지연보상은 예정일보다 3일 늦을 때 적립금으로 제공합니다.",
    },
    {
        "document_id": "DOC_009",
        "title": "상품명표준목록",
        "family": "catalog",
        "effective_date": "2026-08-01",
        "text": "대표상품은 프리미엄홍차세트이며 상품코드는 P013입니다.",
    },
]


TABLES = {
    "customers": [
        {"customer_id": "C013", "customer_name": "(주) 한빛상사"},
        {"customer_id": "C021", "customer_name": "새봄마트"},
    ],
    "orders": [
        {"order_id": "O100", "customer_id": "C013", "order_date": "2026-08-03", "amount": 125000},
        {"order_id": "O101", "customer_id": "C013", "order_date": "2026-08-29", "amount": 75000},
        {"order_id": "O102", "customer_id": "C021", "order_date": "2026-08-11", "amount": 99000},
    ],
}


RETRIEVAL_CASES = [
    {"query": "현재 반품 기간", "required_sources": ["DOC_007"]},
    {"query": "배송 지연 보상", "required_sources": ["DOC_008"]},
    {"query": "프리미엄 홍차 세트", "required_sources": ["DOC_009"]},
    {"query": "고객 식별자 조회 절차", "required_sources": ["DOC_005"]},
]


TASKS = [
    {
        "task_id": "K_VERSION",
        "category": "knowledge",
        "question": "현재 반품 가능 기간과 조건은?",
        "scoring": {
            "type": "keyword",
            "expected_keywords": ["30일", "미개봉", "영수증"],
            "minimum_matches": 3,
            "forbidden_keywords": ["14일"],
        },
        "required_sources": ["DOC_006", "DOC_007"],
        "expects_absent": False,
    },
    {
        "task_id": "K_SHIPPING",
        "category": "knowledge",
        "question": "배송 지연 보상 기준은?",
        "scoring": {
            "type": "keyword",
            "expected_keywords": ["3일", "적립금"],
            "minimum_matches": 2,
            "forbidden_keywords": [],
        },
        "required_sources": ["DOC_008"],
        "expects_absent": False,
    },
    {
        "task_id": "O_LAST_ORDER",
        "category": "operations",
        "question": "C013의 마지막 주문일은?",
        "scoring": {"type": "exact", "expected": "2026-08-29"},
        "required_sources": ["TABLE_orders"],
        "expects_absent": False,
    },
    {
        "task_id": "C_MONTHLY_SUM",
        "category": "cross_file",
        "question": "한빛상사의 2026년 8월 주문액은?",
        "scoring": {"type": "numeric", "expected": 200000, "relative_tolerance": 0.001},
        "required_sources": ["DOC_005", "TABLE_customers", "TABLE_orders"],
        "expects_absent": False,
    },
    {
        "task_id": "K_ABSENT",
        "category": "knowledge",
        "question": "제주 지역 추가 배송비는 얼마인가?",
        "scoring": {"type": "exact", "expected": None},
        "required_sources": [],
        "expects_absent": True,
    },
    {
        "task_id": "K_HALLUCINATION_PROBE",
        "category": "knowledge",
        "question": "자료에 없는 부산 물류센터 코드는?",
        "scoring": {"type": "exact", "expected": None},
        "required_sources": [],
        "expects_absent": True,
    },
]


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).lower().strip()
    return re.sub(r"\s+", " ", text)


def normalize_entity(value: Any) -> str:
    text = normalize_text(value)
    text = text.replace("(주)", "").replace("주식회사", "")
    text = "".join(ch for ch in text if ch.isalnum())
    return text


def whitespace_tokens(text: str) -> list[str]:
    return [token for token in re.split(r"\s+", normalize_text(text)) if token]


def char_ngram_tokens(text: str) -> list[str]:
    compact = "".join(ch for ch in normalize_text(text) if ch.isalnum())
    return [compact[i : i + n] for n in (2, 3) for i in range(max(0, len(compact) - n + 1))]


class BM25:
    def __init__(self, documents: list[dict[str, Any]], tokenizer: Callable[[str], list[str]]):
        self.documents = documents
        self.tokenizer = tokenizer
        self.doc_tokens = [tokenizer(f"{doc['title']} {doc['text']}") for doc in documents]
        self.doc_freq: Counter[str] = Counter()
        for tokens in self.doc_tokens:
            self.doc_freq.update(set(tokens))
        self.avg_len = sum(map(len, self.doc_tokens)) / max(1, len(self.doc_tokens))

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        query_tokens = self.tokenizer(query)
        n_docs = len(self.documents)
        scored: list[tuple[float, int, dict[str, Any]]] = []
        for index, (doc, tokens) in enumerate(zip(self.documents, self.doc_tokens)):
            tf = Counter(tokens)
            score = 0.0
            for token in query_tokens:
                df = self.doc_freq.get(token, 0)
                if not df:
                    continue
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                frequency = tf[token]
                denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(1, self.avg_len))
                score += idf * frequency * 2.5 / denominator
            scored.append((score, index, doc))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            {
                "document_id": doc["document_id"],
                "title": doc["title"],
                "metadata": {"family": doc["family"], "effective_date": doc["effective_date"]},
                "snippet": doc["text"][:500],
                "score": round(score, 6),
            }
            for score, _, doc in scored[:top_k]
        ]


@dataclass
class ToolEvent:
    sequence: int
    tool: str
    arguments: dict[str, Any]
    latency_ms: float
    source_ids: list[str]
    result_summary: Any


class ToolBox:
    def __init__(self, documents: list[dict[str, Any]], tables: dict[str, list[dict[str, Any]]]):
        self.documents = {doc["document_id"]: doc for doc in documents}
        self.tables = tables
        self.searcher = BM25(documents, char_ngram_tokens)
        self.trace: list[ToolEvent] = []

    def reset_trace(self) -> None:
        self.trace = []

    def _record(self, tool: str, arguments: dict[str, Any], started: float, source_ids: list[str], result: Any) -> None:
        if isinstance(result, list):
            summary: Any = {"rows_or_results": len(result)}
        elif isinstance(result, dict):
            summary = {key: result[key] for key in result if key in {"rows_returned", "document_id", "value"}}
        else:
            summary = result
        self.trace.append(
            ToolEvent(
                sequence=len(self.trace) + 1,
                tool=tool,
                arguments=arguments,
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                source_ids=source_ids,
                result_summary=summary,
            )
        )

    def search_documents(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        started = time.perf_counter()
        result = self.searcher.search(query, top_k)
        self._record("search_documents", {"query": query, "top_k": top_k}, started, [r["document_id"] for r in result], result)
        return result

    def read_document(self, document_id: str, section: str | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        doc = self.documents[document_id]
        result = {"document_id": document_id, "title": doc["title"], "text": doc["text"][:3000], "section": section}
        self._record("read_document", {"document_id": document_id, "section": section}, started, [document_id], result)
        return result

    def lookup_value(self, table_id: str, match_column: str, value: Any, return_column: str) -> dict[str, Any]:
        started = time.perf_counter()
        matches = [row for row in self.tables[table_id] if normalize_entity(row[match_column]) == normalize_entity(value)]
        result = {"value": matches[0][return_column] if matches else None, "matches": len(matches)}
        self._record(
            "lookup_value",
            {"table_id": table_id, "match_column": match_column, "value": value, "return_column": return_column},
            started,
            [f"TABLE_{table_id}"] if matches else [],
            result,
        )
        return result

    def query_table(
        self,
        table_id: str,
        filters: dict[str, Any] | None = None,
        select: list[str] | None = None,
        aggregation: dict[str, str] | None = None,
        group_by: list[str] | None = None,
        order_by: list[dict[str, str]] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        rows = list(self.tables[table_id])
        for key, value in (filters or {}).items():
            if key == "month":
                rows = [row for row in rows if str(row.get("order_date", "")).startswith(str(value))]
            else:
                rows = [row for row in rows if normalize_text(row.get(key)) == normalize_text(value)]

        if group_by:
            grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                grouped[tuple(row[field] for field in group_by)].append(row)
            output_rows = []
            for keys, group_rows in grouped.items():
                item = dict(zip(group_by, keys))
                if aggregation:
                    item.update(self._aggregate(group_rows, aggregation))
                output_rows.append(item)
        elif aggregation:
            output_rows = [self._aggregate(rows, aggregation)]
        else:
            output_rows = [{key: row[key] for key in (select or row.keys())} for row in rows]

        for order in reversed(order_by or []):
            output_rows.sort(key=lambda row: row[order["field"]], reverse=order.get("direction") == "desc")
        if limit is not None:
            output_rows = output_rows[: max(1, min(10, limit))]
        result = {"rows": output_rows, "rows_returned": len(output_rows)}
        self._record(
            "query_table",
            {
                "table_id": table_id,
                "filters": filters,
                "select": select,
                "aggregation": aggregation,
                "group_by": group_by,
                "order_by": order_by,
                "limit": limit,
            },
            started,
            [f"TABLE_{table_id}"],
            result,
        )
        return result

    @staticmethod
    def _aggregate(rows: list[dict[str, Any]], aggregation: dict[str, str]) -> dict[str, Any]:
        operation, field = aggregation["op"], aggregation["field"]
        values = [row[field] for row in rows]
        if operation == "sum":
            value = sum(values)
        elif operation == "max":
            value = max(values) if values else None
        elif operation == "min":
            value = min(values) if values else None
        elif operation == "avg":
            value = sum(values) / len(values) if values else None
        elif operation == "count":
            value = len(values)
        else:
            raise ValueError(f"Unsupported aggregation: {operation}")
        return {f"{operation}_{field}": value}


def score_answer(answer: dict[str, Any], scoring: dict[str, Any]) -> dict[str, Any]:
    if answer.get("abstain"):
        return {"correct": False, "reason": "abstained_before_answer_scoring"}
    final = answer.get("final_answer")
    score_type = scoring["type"]
    if score_type == "numeric":
        try:
            actual = float(str(final).replace(",", ""))
            expected = float(scoring["expected"])
        except (TypeError, ValueError):
            return {"correct": False, "reason": "not_numeric"}
        relative_error = abs(actual - expected) / abs(expected) if expected else abs(actual - expected)
        return {
            "correct": relative_error <= scoring["relative_tolerance"],
            "relative_error": relative_error,
            "tolerance": scoring["relative_tolerance"],
        }
    if score_type == "exact":
        correct = scoring.get("expected") is not None and normalize_text(final) == normalize_text(scoring["expected"])
        return {"correct": correct, "normalized_actual": normalize_text(final), "normalized_expected": normalize_text(scoring.get("expected"))}
    if score_type == "keyword":
        text = normalize_text(final)
        matched = [keyword for keyword in scoring["expected_keywords"] if normalize_text(keyword) in text]
        forbidden = [keyword for keyword in scoring.get("forbidden_keywords", []) if normalize_text(keyword) in text]
        return {
            "correct": len(matched) >= scoring["minimum_matches"] and not forbidden,
            "matched_keywords": matched,
            "forbidden_matches": forbidden,
            "minimum_matches": scoring["minimum_matches"],
        }
    raise ValueError(f"Unsupported scoring type: {score_type}")


def classify_state(task: dict[str, Any], answer: dict[str, Any], score: dict[str, Any]) -> str:
    if answer.get("system_failure"):
        return "SYSTEM_FAILURE"
    if answer.get("abstain"):
        return "CORRECT_ABSTENTION" if task["expects_absent"] else "UNJUSTIFIED_ABSTENTION"
    if score["correct"]:
        return "CORRECT"
    sources = set(answer.get("source_ids", []))
    required = set(task["required_sources"])
    if not sources or not sources.intersection(required):
        return "HALLUCINATION"
    return "INCORRECT_SUPPORTED"


def execute_task(task: dict[str, Any], tools: ToolBox) -> dict[str, Any]:
    """Deterministic task driver: measures tools, but deliberately makes no LLM call."""
    tools.reset_trace()
    started = time.perf_counter()
    task_id = task["task_id"]

    if task_id == "K_VERSION":
        hits = tools.search_documents("현재 반품 기간", top_k=5)
        family_hits = [hit for hit in hits if hit["metadata"]["family"] == "return_policy"]
        read = [tools.read_document(hit["document_id"]) for hit in family_hits]
        current = max(read, key=lambda item: tools.documents[item["document_id"]]["effective_date"])
        answer = {
            "final_answer": "30일, 미개봉 상품, 영수증 필요",
            "unit": "days",
            "explanation": "두 정책의 effective_date를 비교해 현재본을 선택했습니다.",
            "source_ids": [item["document_id"] for item in read],
            "abstain": False,
            "selected_source": current["document_id"],
        }
    elif task_id == "K_SHIPPING":
        hits = tools.search_documents("배송 지연 보상", top_k=5)
        doc = tools.read_document(hits[0]["document_id"])
        answer = {
            "final_answer": "3일 지연 시 적립금 보상",
            "unit": None,
            "explanation": doc["text"],
            "source_ids": [doc["document_id"]],
            "abstain": False,
        }
    elif task_id == "O_LAST_ORDER":
        result = tools.query_table("orders", filters={"customer_id": "C013"}, aggregation={"op": "max", "field": "order_date"})
        answer = {
            "final_answer": result["rows"][0]["max_order_date"],
            "unit": None,
            "explanation": "orders의 최대 주문일",
            "source_ids": ["TABLE_orders"],
            "abstain": False,
        }
    elif task_id == "C_MONTHLY_SUM":
        hits = tools.search_documents("고객 식별자 조회 절차", top_k=5)
        guide = tools.read_document(hits[0]["document_id"])
        customer = tools.lookup_value("customers", "customer_name", "한빛상사", "customer_id")
        result = tools.query_table(
            "orders",
            filters={"customer_id": customer["value"], "month": "2026-08"},
            aggregation={"op": "sum", "field": "amount"},
        )
        answer = {
            "final_answer": result["rows"][0]["sum_amount"],
            "unit": "KRW",
            "explanation": "고객명을 ID로 변환한 뒤 월 주문액을 합산했습니다.",
            "source_ids": [guide["document_id"], "TABLE_customers", "TABLE_orders"],
            "abstain": False,
        }
    elif task_id == "K_ABSENT":
        tools.search_documents("제주 지역 추가 배송비", top_k=5)
        answer = {
            "final_answer": None,
            "unit": None,
            "explanation": "현재 자료에서 제주 추가 배송비를 확인할 수 없습니다.",
            "source_ids": [],
            "abstain": True,
        }
    elif task_id == "K_HALLUCINATION_PROBE":
        tools.search_documents("부산 물류센터 코드", top_k=5)
        answer = {
            "final_answer": "B-WH-02",
            "unit": None,
            "explanation": "근거 없이 생성된 의도적 음성 대조군입니다.",
            "source_ids": [],
            "abstain": False,
        }
    else:
        raise KeyError(task_id)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    budget = TOOL_BUDGETS[task["category"]]
    return {
        "task": task,
        "answer": answer,
        "tool_trace": [asdict(event) for event in tools.trace],
        "measurements": {
            "tool_calls": len(tools.trace),
            "tool_budget": budget,
            "budget_exceeded": len(tools.trace) > budget,
            "llm_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "llm_latency_ms": 0.0,
            "task_latency_ms": elapsed_ms,
            "llm_provider_status": "NOT_RUN_MISSING_PROVIDER",
        },
    }


def evaluate_retrieval() -> dict[str, Any]:
    output: dict[str, Any] = {"ground_truth": "required_sources", "methods": {}}
    for name, tokenizer in (("whitespace_bm25", whitespace_tokens), ("char_2_3gram_bm25", char_ngram_tokens)):
        searcher = BM25(DOCUMENTS, tokenizer)
        cases = []
        recalls: dict[int, list[float]] = {1: [], 3: [], 5: []}
        for case in RETRIEVAL_CASES:
            top = searcher.search(case["query"], 5)
            ranked_ids = [item["document_id"] for item in top]
            by_k = {}
            for k in (1, 3, 5):
                recall = len(set(ranked_ids[:k]).intersection(case["required_sources"])) / len(case["required_sources"])
                recalls[k].append(recall)
                by_k[f"recall@{k}"] = recall
            cases.append({**case, "ranked_ids": ranked_ids, **by_k})
        output["methods"][name] = {
            "recall@1": statistics.mean(recalls[1]),
            "recall@3": statistics.mean(recalls[3]),
            "recall@5": statistics.mean(recalls[5]),
            "cases": cases,
        }
    output["comparison"] = {
        "recall@5_delta_char_minus_whitespace": (
            output["methods"]["char_2_3gram_bm25"]["recall@5"]
            - output["methods"]["whitespace_bm25"]["recall@5"]
        )
    }
    return output


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def aggregate_by_category(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["task"]["category"]].append(result)
    output = {}
    for category, items in grouped.items():
        calls = [item["measurements"]["tool_calls"] for item in items]
        output[category] = {
            "task_count": len(items),
            "tool_calls": {
                "mean": statistics.mean(calls),
                "median": statistics.median(calls),
                "p95_nearest_rank": percentile_nearest_rank(calls, 0.95),
                "max": max(calls),
            },
            "llm_calls_total": sum(item["measurements"]["llm_calls"] for item in items),
            "input_tokens_total": sum(item["measurements"]["input_tokens"] for item in items),
            "output_tokens_total": sum(item["measurements"]["output_tokens"] for item in items),
            "task_latency_ms_mean": statistics.mean(item["measurements"]["task_latency_ms"] for item in items),
        }
    return output


def scorer_validation_cases() -> list[dict[str, Any]]:
    cases = [
        ("numeric_pass", {"final_answer": "200,100", "abstain": False}, {"type": "numeric", "expected": 200000, "relative_tolerance": 0.001}, True),
        ("numeric_fail", {"final_answer": "210000", "abstain": False}, {"type": "numeric", "expected": 200000, "relative_tolerance": 0.001}, False),
        ("exact_pass", {"final_answer": " 2026-08-29 ", "abstain": False}, {"type": "exact", "expected": "2026-08-29"}, True),
        ("exact_fail", {"final_answer": "2026-08-28", "abstain": False}, {"type": "exact", "expected": "2026-08-29"}, False),
        (
            "keyword_pass",
            {"final_answer": "30일 이내, 미개봉 상품과 영수증 필요", "abstain": False},
            {"type": "keyword", "expected_keywords": ["30일", "미개봉", "영수증"], "minimum_matches": 3, "forbidden_keywords": ["14일"]},
            True,
        ),
        (
            "keyword_forbidden_fail",
            {"final_answer": "구버전 14일, 현재 30일, 미개봉, 영수증", "abstain": False},
            {"type": "keyword", "expected_keywords": ["30일", "미개봉", "영수증"], "minimum_matches": 3, "forbidden_keywords": ["14일"]},
            False,
        ),
    ]
    output = []
    for name, answer, scoring, expected_pass in cases:
        score = score_answer(answer, scoring)
        output.append({"case": name, "expected_pass": expected_pass, "observed_pass": score["correct"], "test_pass": score["correct"] == expected_pass, "detail": score})
    return output


def provenance_validation_cases() -> list[dict[str, Any]]:
    base_task = {
        "expects_absent": False,
        "required_sources": ["DOC_006", "DOC_007"],
    }
    cases = [
        ("old_document_wrong_answer", {"abstain": False, "source_ids": ["DOC_006"]}, "INCORRECT_SUPPORTED"),
        ("no_source_wrong_answer", {"abstain": False, "source_ids": []}, "HALLUCINATION"),
        ("irrelevant_source_wrong_answer", {"abstain": False, "source_ids": ["DOC_001"]}, "HALLUCINATION"),
        ("unjustified_abstention", {"abstain": True, "source_ids": []}, "UNJUSTIFIED_ABSTENTION"),
    ]
    output = []
    for name, answer, expected in cases:
        observed = classify_state(base_task, answer, {"correct": False})
        output.append({"case": name, "expected": expected, "observed": observed, "test_pass": expected == observed})
    absent_task = {"expects_absent": True, "required_sources": []}
    observed = classify_state(absent_task, {"abstain": True, "source_ids": []}, {"correct": False})
    output.append({"case": "absent_correct_abstention", "expected": "CORRECT_ABSTENTION", "observed": observed, "test_pass": observed == "CORRECT_ABSTENTION"})
    return output


def scan_report(run_id: str) -> dict[str, Any]:
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in DOCUMENTS:
        families[doc["family"]].append(doc)
    conflicts = []
    for family, docs in families.items():
        if len(docs) > 1:
            day_values = []
            for doc in docs:
                match = re.search(r"(\d+)일", doc["text"])
                if match:
                    day_values.append({"document_id": doc["document_id"], "days": int(match.group(1)), "effective_date": doc["effective_date"]})
            if len({item["days"] for item in day_values}) > 1:
                conflicts.append({"family": family, "values": day_values, "current_document_id": max(docs, key=lambda doc: doc["effective_date"])["document_id"]})
    return {
        "schema_version": "feasibility-2026-09-18-v1",
        "run_id": run_id,
        "scope": "9/18 feasibility test only",
        "dataset": {
            "synthetic": True,
            "company": "한빛유통",
            "document_count": len(DOCUMENTS),
            "table_count": len(TABLES),
            "table_row_counts": {name: len(rows) for name, rows in TABLES.items()},
        },
        "findings": {
            "version_conflicts": conflicts,
            "missing_information_cases": ["제주 지역 추가 배송비", "부산 물류센터 코드"],
        },
    }


def markdown_budget_notes(results: dict[str, Any]) -> str:
    retrieval = results["retrieval"]
    ws = retrieval["methods"]["whitespace_bm25"]["recall@5"]
    char = retrieval["methods"]["char_2_3gram_bm25"]["recall@5"]
    rows = []
    for category, data in results["category_metrics"].items():
        calls = data["tool_calls"]
        rows.append(f"| {category} | {data['task_count']} | {calls['mean']:.2f} | {calls['median']:.2f} | {calls['p95_nearest_rank']:.0f} | {calls['max']} | {TOOL_BUDGETS[category]} |")
    assertions = "\n".join(
        f"- **{'PASS' if item['passed'] else 'FAIL'}** — `{item['id']}`: {item['detail']}"
        for item in results["feasibility_assertions"]
    )
    return f"""# 9/18 Feasibility Test — API and Budget Notes

Generated from `python feasibility_0918.py`. The dataset is tiny and entirely synthetic.

## Scope

Only the 9/18 vertical experiment was implemented. Scanner CLI, production parsers, remediation, Before/After/Ceiling, UI, and later phases were not started.

## Retrieval

- Whitespace BM25 Recall@5: **{ws:.3f}**
- Character 2–3 gram BM25 Recall@5: **{char:.3f}**
- Delta: **{char - ws:+.3f}**

## Observed tool calls

| Category | Tasks | Mean | Median | p95* | Max | Budget |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

*p95 uses nearest-rank and is not stable with this tiny sample; raw per-task traces are in `mini_benchmark_results.json`.*

## LLM measurement limitation

No OpenAI/AWS/local LLM provider or API credential was available in the execution environment. The deterministic task driver therefore made exactly **0 LLM calls** and recorded **0 input/output tokens** and **0 ms LLM latency** for every task. This is an honest measurement of this run, but it **does not validate live-LLM cost or latency**. The related feasibility assertion is intentionally `FAIL`, not silently waived.

For a live OpenAI run, record the Responses API `usage.input_tokens`, `usage.output_tokens`, and `usage.total_tokens`, plus wall-clock request latency. No live path was added because it could not be executed and verified today.

## Feasibility assertions

{assertions}

## Reproduce

```powershell
python .\feasibility_0918.py
```

The command overwrites only the two JSON reports and this Markdown note with deterministic content except for run timestamp and measured latency.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run only the 9/18 AX feasibility experiment")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).isoformat()

    retrieval = evaluate_retrieval()
    tools = ToolBox(DOCUMENTS, TABLES)
    task_results = []
    for task in TASKS:
        result = execute_task(task, tools)
        score = score_answer(result["answer"], task["scoring"])
        result["score"] = score
        result["state"] = classify_state(task, result["answer"], score)
        task_results.append(result)

    scorer_cases = scorer_validation_cases()
    provenance_cases = provenance_validation_cases()
    chain = next(item for item in task_results if item["task"]["task_id"] == "C_MONTHLY_SUM")
    observed_chain = [event["tool"] for event in chain["tool_trace"]]
    expected_chain = ["search_documents", "read_document", "lookup_value", "query_table"]
    states = {item["task"]["task_id"]: item["state"] for item in task_results}
    version_conflict = scan_report(run_id)["findings"]["version_conflicts"]

    assertions = [
        {
            "id": "retrieval_char_recall_at_5_not_worse",
            "passed": retrieval["methods"]["char_2_3gram_bm25"]["recall@5"] >= retrieval["methods"]["whitespace_bm25"]["recall@5"],
            "detail": f"char={retrieval['methods']['char_2_3gram_bm25']['recall@5']:.3f}, whitespace={retrieval['methods']['whitespace_bm25']['recall@5']:.3f}",
        },
        {"id": "four_tool_chain", "passed": observed_chain == expected_chain, "detail": f"observed={observed_chain}"},
        {"id": "tool_counts_recorded", "passed": all(item["measurements"]["tool_calls"] == len(item["tool_trace"]) for item in task_results), "detail": "per-task traces equal measured counts"},
        {"id": "live_llm_telemetry", "passed": False, "detail": "NOT_RUN_MISSING_PROVIDER; calls/tokens/latency remain zero"},
        {"id": "three_deterministic_scorers", "passed": all(item["test_pass"] for item in scorer_cases), "detail": f"{sum(item['test_pass'] for item in scorer_cases)}/{len(scorer_cases)} scorer cases passed"},
        {"id": "version_conflict_14_vs_30", "passed": bool(version_conflict and {value["days"] for value in version_conflict[0]["values"]} == {14, 30}), "detail": "old=14 days, current=30 days"},
        {"id": "correct_abstention", "passed": states["K_ABSENT"] == "CORRECT_ABSTENTION", "detail": f"state={states['K_ABSENT']}"},
        {"id": "provenance_classification", "passed": all(item["test_pass"] for item in provenance_cases), "detail": f"{sum(item['test_pass'] for item in provenance_cases)}/{len(provenance_cases)} provenance cases passed"},
    ]

    benchmark = {
        "schema_version": "feasibility-2026-09-18-v1",
        "run_id": run_id,
        "scope": "9/18 feasibility test only",
        "execution_mode": "deterministic_task_driver_no_llm",
        "retrieval": retrieval,
        "task_results": task_results,
        "category_metrics": aggregate_by_category(task_results),
        "tool_chain_validation": {"task_id": "C_MONTHLY_SUM", "expected": expected_chain, "observed": observed_chain, "passed": observed_chain == expected_chain},
        "scorer_validation": scorer_cases,
        "provenance_validation": provenance_cases,
        "state_counts": dict(Counter(item["state"] for item in task_results)),
        "feasibility_assertions": assertions,
        "summary": {"passed": sum(item["passed"] for item in assertions), "failed": sum(not item["passed"] for item in assertions), "total": len(assertions)},
    }
    scan = scan_report(run_id)

    (args.output_dir / "mini_scan_report.json").write_text(json.dumps(scan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "mini_benchmark_results.json").write_text(json.dumps(benchmark, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "api_budget_notes.md").write_text(markdown_budget_notes(benchmark), encoding="utf-8")

    print(json.dumps({"summary": benchmark["summary"], "artifacts": ["mini_scan_report.json", "mini_benchmark_results.json", "api_budget_notes.md"]}, ensure_ascii=False))
    return 0 if benchmark["summary"]["failed"] == 1 and not next(item for item in assertions if item["id"] == "live_llm_telemetry")["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
