#!/usr/bin/env python3
"""Generate the clean, deterministic AX Ceiling dataset and benchmark truth.

The company folder is the only runtime-facing fixture.  Benchmark artifacts are
written beside it, never inside it, so an eventual Kiro runtime can receive the
company evidence without receiving evaluation answers or planned blockers.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from ax_scanner.reports import write_report
from ax_scanner.scanner import scan_folder
from ax_scanner.telemetry import detect_live_llm_status

from .independent_ceiling_truth import independently_compute_truth
from .runtime_prompt import construct_runtime_prompt, project_runtime_prompt


ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "hanbit-distribution-ceiling-v1"
GENERATOR_VERSION = "1.1.0"
RANDOM_SEED = 20260921
AS_OF_DATE = date(2026, 9, 21)
FIXED_TIMESTAMP = datetime(2026, 9, 21, tzinfo=timezone.utc).timestamp()
FIXED_DOCUMENT_TIME = datetime(2026, 9, 21, tzinfo=timezone.utc)
ZIP_TIME = (2026, 9, 21, 0, 0, 0)
SOURCE_RELATIVE = Path("sample_data") / "ceiling_company"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _canonicalize_zip(path: Path) -> None:
    """Strip ZIP timestamp variability from DOCX and XLSX containers."""
    with zipfile.ZipFile(path, "r") as source:
        members: list[tuple[str, bytes]] = []
        for info in source.infolist():
            if not info.is_dir():
                data = source.read(info.filename)
                if info.filename == "docProps/core.xml":
                    data = re.sub(
                        rb"(<dcterms:modified\b[^>]*>)[^<]*(</dcterms:modified>)",
                        rb"\g<1>2026-09-21T00:00:00Z\g<2>",
                        data,
                    )
                members.append((info.filename, data))
    with tempfile.NamedTemporaryFile(delete=False, dir=path.parent, suffix=".zip") as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for name, data in sorted(members):
                info = zipfile.ZipInfo(name, ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                target.writestr(info, data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_xlsx(path: Path, sheets: list[tuple[str, list[str], list[dict[str, Any]]]]) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.created = FIXED_DOCUMENT_TIME.replace(tzinfo=None)
    workbook.properties.modified = FIXED_DOCUMENT_TIME.replace(tzinfo=None)
    for title, headers, rows in sheets:
        worksheet = workbook.create_sheet(title)
        worksheet.append(headers)
        for row in rows:
            worksheet.append([row.get(header) for header in headers])
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
    workbook.save(path)
    workbook.close()
    _canonicalize_zip(path)


def _write_docx(path: Path, title: str, paragraphs: list[str], table: tuple[list[str], list[list[str]]] | None = None) -> None:
    document = Document()
    document.core_properties.created = FIXED_DOCUMENT_TIME
    document.core_properties.modified = FIXED_DOCUMENT_TIME
    document.add_heading(title, level=1)
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    if table:
        headers, rows = table
        rendered = document.add_table(rows=1, cols=len(headers))
        for index, value in enumerate(headers):
            rendered.cell(0, index).text = value
        for values in rows:
            cells = rendered.add_row().cells
            for index, value in enumerate(values):
                cells[index].text = value
    document.save(path)
    _canonicalize_zip(path)


def _write_pdf(path: Path, lines: list[str]) -> None:
    pdf = canvas.Canvas(str(path), pagesize=letter, invariant=1, pageCompression=0)
    y = 730
    for line in lines:
        pdf.drawString(54, y, line)
        y -= 22
    pdf.save()


def _set_fixed_times(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, (FIXED_TIMESTAMP, FIXED_TIMESTAMP))


def _company_data() -> dict[str, Any]:
    """Create realistic but entirely synthetic, seeded distribution-company data."""
    rng = random.Random(RANDOM_SEED)
    customers = [
        {"customer_id": "C001", "customer_name": "한빛상사", "sales_tier": "A", "city": "서울", "payment_terms": "30일"},
        {"customer_id": "C002", "customer_name": "새봄마트", "sales_tier": "B", "city": "성남", "payment_terms": "30일"},
        {"customer_id": "C003", "customer_name": "동해상사", "sales_tier": "A", "city": "인천", "payment_terms": "45일"},
        {"customer_id": "C004", "customer_name": "미래식품", "sales_tier": "B", "city": "수원", "payment_terms": "30일"},
        {"customer_id": "C005", "customer_name": "그린테이블", "sales_tier": "B", "city": "고양", "payment_terms": "30일"},
        {"customer_id": "C006", "customer_name": "윤성마트", "sales_tier": "C", "city": "용인", "payment_terms": "15일"},
        {"customer_id": "C007", "customer_name": "아람리빙", "sales_tier": "A", "city": "서울", "payment_terms": "45일"},
        {"customer_id": "C008", "customer_name": "행복상점", "sales_tier": "C", "city": "의정부", "payment_terms": "15일"},
        {"customer_id": "C009", "customer_name": "다온유통", "sales_tier": "B", "city": "부천", "payment_terms": "30일"},
        {"customer_id": "C010", "customer_name": "새길상회", "sales_tier": "C", "city": "안양", "payment_terms": "15일"},
    ]
    products = [
        {"product_id": "P001", "product_name": "무가당 현미차 20입", "category": "음료", "unit_price": 9800, "standard_cost": 5100},
        {"product_id": "P002", "product_name": "저온착즙 사과주스", "category": "음료", "unit_price": 24000, "standard_cost": 13300},
        {"product_id": "P003", "product_name": "프리미엄 홍차 세트", "category": "선물", "unit_price": 46500, "standard_cost": 25900},
        {"product_id": "P004", "product_name": "국산 들기름 180ml", "category": "식품", "unit_price": 17800, "standard_cost": 9900},
        {"product_id": "P005", "product_name": "유기농 그래놀라", "category": "식품", "unit_price": 12900, "standard_cost": 6900},
        {"product_id": "P006", "product_name": "천연 수세미 3입", "category": "생활", "unit_price": 8600, "standard_cost": 4100},
        {"product_id": "P007", "product_name": "대나무 키친타월", "category": "생활", "unit_price": 15200, "standard_cost": 8100},
        {"product_id": "P008", "product_name": "냉동 블루베리 1kg", "category": "식품", "unit_price": 19800, "standard_cost": 11200},
        {"product_id": "P009", "product_name": "제주 감귤칩", "category": "간식", "unit_price": 11300, "standard_cost": 5900},
        {"product_id": "P010", "product_name": "수제 비누 선물세트", "category": "선물", "unit_price": 32500, "standard_cost": 17500},
        {"product_id": "P011", "product_name": "저자극 세탁세제", "category": "생활", "unit_price": 21900, "standard_cost": 12100},
        {"product_id": "P012", "product_name": "콜드브루 원액", "category": "음료", "unit_price": 14500, "standard_cost": 7700},
    ]
    prices = {item["product_id"]: item["unit_price"] for item in products}
    product_ids = [item["product_id"] for item in products]
    customer_ids = [item["customer_id"] for item in customers]
    customer_weights = [16, 11, 14, 8, 8, 6, 12, 5, 11, 5]
    product_weights = [12, 7, 4, 8, 10, 11, 10, 7, 8, 4, 5, 9]
    first_day = date(2026, 5, 1)
    order_day_count = (AS_OF_DATE - first_day).days + 1
    orders: list[dict[str, Any]] = []
    for index in range(180):
        ordered = first_day + timedelta(days=rng.randrange(order_day_count))
        customer_id = rng.choices(customer_ids, weights=customer_weights, k=1)[0]
        product_id = rng.choices(product_ids, weights=product_weights, k=1)[0]
        quantity = max(1, min(42, round(rng.gammavariate(2.1, 4.4))))
        unit_price = prices[product_id]
        orders.append({
            "order_id": f"O{index + 1001:04d}",
            "customer_id": customer_id,
            "product_id": product_id,
            "order_date": ordered.isoformat(),
            "quantity": quantity,
            "unit_price": unit_price,
            "amount": quantity * unit_price,
            "order_status": "출고완료" if ordered <= date(2026, 9, 12) else "주문확정",
        })
    orders.sort(key=lambda row: (row["order_date"], row["order_id"]))
    eligible_returns = [
        order for order in orders
        if date.fromisoformat(order["order_date"]) <= AS_OF_DATE - timedelta(days=7)
    ]
    selected_returns = sorted(rng.sample(eligible_returns, 36), key=lambda row: row["order_id"])
    returns: list[dict[str, Any]] = []
    for index, order in enumerate(selected_returns):
        returned = max(1, min(order["quantity"], round(order["quantity"] * rng.uniform(0.05, 0.25))))
        returns.append({
            "return_id": f"R{index + 501:04d}",
            "order_id": order["order_id"],
            "customer_id": order["customer_id"],
            "product_id": order["product_id"],
            "return_date": (date.fromisoformat(order["order_date"]) + timedelta(days=7)).isoformat(),
            "returned_qty": returned,
            "shipped_qty": order["quantity"],
            "return_reason": rng.choice(["단순변심", "파손", "오배송", "품질문의"]),
        })
    inventory = []
    for index, item in enumerate(products):
        available = 80 + int(rng.gammavariate(3.4, 44))
        reserved = rng.randrange(4, 40)
        inventory.append({
            "product_id": item["product_id"],
            "warehouse_code": "WH-SEOUL" if index < 7 else "WH-ICN",
            "available_qty": available,
            "reserved_qty": reserved,
            "reorder_point": 65 + (index % 4) * 15,
            "unit_cost": item["standard_cost"],
            "last_receipt_date": (date(2026, 8, 17) + timedelta(days=index)).isoformat(),
        })
    outbound = [
        {
            "request_id": f"S{index + 801:04d}",
            "order_id": order["order_id"],
            "warehouse_code": "WH-SEOUL" if order["product_id"] <= "P007" else "WH-ICN",
            "requested_ship_date": order["order_date"],
            "status": order["order_status"],
        }
        for index, order in enumerate(orders[-72:])
    ]
    monthly_targets = []
    for month in range(1, 13):
        monthly_targets.append({
            "month": f"2026-{month:02d}",
            "sales_target": 82_000_000 + month * 1_500_000,
            "gross_margin_target": 0.31,
        })
    return {
        "customers": customers,
        "products": products,
        "orders": orders,
        "returns": returns,
        "inventory": inventory,
        "outbound": outbound,
        "monthly_targets": monthly_targets,
    }


def _write_company_files(source_root: Path, data: dict[str, Any]) -> None:
    folders = [
        "01_경영관리", "02_정책", "03_영업", "04_주문", "05_물류", "06_고객지원", "07_정산",
    ]
    for folder in folders:
        (source_root / folder).mkdir(parents=True, exist_ok=True)

    _write_text(source_root / "01_경영관리" / "회사소개_한빛유통.txt", """한빛유통은 수도권 소매 거래처에 식품·생활용품을 공급하는 직원 45명 규모의 유통기업입니다.
기준일은 2026-09-21이며, 모든 운영 자료는 해당 기준일의 승인본입니다.""")
    _write_docx(source_root / "01_경영관리" / "2026_사업운영방침.docx", "2026 사업운영방침", [
        "한빛유통은 거래처·상품·주문 식별자를 기준으로 영업과 물류 데이터를 연결합니다.",
        "운영 판단에는 승인된 마스터와 당일 재고 현황을 사용합니다.",
    ], (["지표", "2026 기준"], [["주문 기준", "주문원장_2026"], ["재고 기준", "재고현황_2026-09"]]))
    _write_pdf(source_root / "01_경영관리" / "거래처_관리기준.pdf", [
        "Customer management standard", "Use the approved customer ID for sales and operations reporting.",
        "Payment terms are maintained in the customer master workbook.",
    ])
    _write_text(source_root / "01_경영관리" / "월간_운영회의록_2026-08.txt", """2026년 8월 운영회의록
주문원장의 customer_id와 품목마스터의 product_id를 공통 운영 식별자로 사용한다.
9월 재고 점검은 2026-09-21 기준 수량으로 진행한다.""")
    _write_text(source_root / "01_경영관리" / "조직_연락망.txt", """운영조직 역할 안내
영업운영팀: 할인 승인과 거래처 기준 관리
물류운영팀: 출고 요청과 재고 조정
고객지원팀: 반품 접수와 고객 응대""")

    _write_docx(source_root / "02_정책" / "반품_교환_정책_2026.docx", "반품·교환 정책 2026", [
        "반품 가능 기간은 구매일로부터 30일입니다.",
        "반품 대상 상품은 미개봉, 미사용, 재판매 가능 상태여야 하며 원본 영수증을 함께 제출해야 합니다.",
        "훼손되었거나 변경된 상품은 반품 대상이 아닙니다.",
    ])
    _write_docx(source_root / "02_정책" / "배송_지연_보상_2026.docx", "배송 지연 보상 정책 2026", [
        "배송 지연 보상은 배송 지연이 3영업일을 초과하면 시작됩니다.",
        "승인된 보상은 적립금으로 제공합니다.",
    ])
    _write_docx(source_root / "02_정책" / "할인_승인_규정.docx", "할인 승인 규정", [
        "주문금액이 1,000,000원 이상인 개별 할인 요청은 영업운영팀장의 승인을 받아야 합니다.",
        "승인 후 할인코드를 주문 메모가 아닌 주문 시스템의 승인 필드에 기록합니다.",
    ])
    _write_text(source_root / "02_정책" / "재고_조정_절차.txt", """재고 조정 절차
실사 차이가 확인되면 물류운영팀이 재고 조정 요청서를 작성한다.
안전재고 이하 품목은 발주 검토 목록에 올리고, 승인 전에는 가용수량을 임의로 변경하지 않는다.""")
    _write_docx(source_root / "02_정책" / "신규거래처_등록_절차.docx", "신규 거래처 등록 절차", [
        "신규 거래처는 거래처마스터에서 customer_id를 발급받은 뒤 주문을 등록합니다.",
        "동일 상호의 중복 등록 여부와 결제조건을 영업운영팀이 확인합니다.",
    ])

    _write_csv(source_root / "03_영업" / "품목_마스터.csv", ["product_id", "product_name", "category", "unit_price", "standard_cost"], data["products"])
    _write_xlsx(source_root / "03_영업" / "거래처_마스터.xlsx", [
        ("Customers", ["customer_id", "customer_name", "sales_tier", "city", "payment_terms"], data["customers"]),
    ])
    _write_xlsx(source_root / "03_영업" / "월별_매출목표_2026.xlsx", [
        ("Targets", ["month", "sales_target", "gross_margin_target"], data["monthly_targets"]),
    ])
    _write_text(source_root / "03_영업" / "영업_운영_안내.txt", """영업 운영 안내
거래처명으로 주문을 조회할 때에는 먼저 거래처마스터에서 customer_id를 확인한다.
상품명으로 재고를 확인할 때에는 먼저 품목마스터에서 product_id를 확인한다.""")
    _write_csv(source_root / "03_영업" / "할인코드_정의.csv", ["discount_code", "discount_name", "discount_rate", "approval_required"], [
        {"discount_code": "DISC05", "discount_name": "정기거래처", "discount_rate": 0.05, "approval_required": "N"},
        {"discount_code": "DISC10", "discount_name": "계절행사", "discount_rate": 0.10, "approval_required": "Y"},
        {"discount_code": "DISC15", "discount_name": "대량주문", "discount_rate": 0.15, "approval_required": "Y"},
    ])

    _write_xlsx(source_root / "04_주문" / "주문_원장_2026.xlsx", [
        ("Orders", ["order_id", "customer_id", "product_id", "order_date", "quantity", "unit_price", "amount", "order_status"], data["orders"]),
    ])
    _write_text(source_root / "04_주문" / "주문_상태_기준.txt", """주문 상태 기준
주문확정: 결제와 재고 예약이 완료된 주문
출고완료: 창고에서 출고 요청이 완료된 주문
취소: 출고 전 고객 요청 또는 승인 오류로 취소된 주문""")
    august_total = sum(row["amount"] for row in data["orders"] if row["order_date"].startswith("2026-08"))
    _write_pdf(source_root / "04_주문" / "8월_주문_검토.pdf", [
        "August 2026 order review", f"Recorded August order amount: KRW {august_total:,}.",
        "Detailed evidence remains in the approved order ledger.",
    ])
    _write_csv(source_root / "04_주문" / "반품_원장_2026.csv", ["return_id", "order_id", "customer_id", "product_id", "return_date", "returned_qty", "shipped_qty", "return_reason"], data["returns"])
    _write_xlsx(source_root / "04_주문" / "출고_요청_2026.xlsx", [
        ("OutboundRequests", ["request_id", "order_id", "warehouse_code", "requested_ship_date", "status"], data["outbound"]),
    ])

    _write_xlsx(source_root / "05_물류" / "재고_현황_2026-09.xlsx", [
        ("Inventory", ["product_id", "warehouse_code", "available_qty", "reserved_qty", "reorder_point", "unit_cost", "last_receipt_date"], data["inventory"]),
    ])
    _write_docx(source_root / "05_물류" / "창고_운영_매뉴얼.docx", "창고 운영 매뉴얼", [
        "재고 조회는 재고현황 파일의 available_qty를 기준으로 합니다.",
        "출고 우선순위는 주문확정일과 고객 납기 약속을 함께 확인합니다.",
        "입고 완료 후에는 last_receipt_date를 갱신합니다.",
    ])
    _write_csv(source_root / "05_물류" / "배송권역_리드타임.csv", ["zone_code", "zone_name", "standard_lead_days", "carrier"], [
        {"zone_code": "Z01", "zone_name": "서울", "standard_lead_days": 1, "carrier": "한빛택배"},
        {"zone_code": "Z02", "zone_name": "경기", "standard_lead_days": 2, "carrier": "한빛택배"},
        {"zone_code": "Z03", "zone_name": "인천", "standard_lead_days": 2, "carrier": "한빛택배"},
        {"zone_code": "Z04", "zone_name": "강원", "standard_lead_days": 3, "carrier": "한빛택배"},
    ])
    _write_text(source_root / "05_물류" / "입고_검수_기준.txt", """입고 검수 기준
수량, 외관, 유통기한을 확인한다.
검수 완료 수량은 재고현황에 반영하며, 훼손 수량은 가용수량에 포함하지 않는다.""")
    _write_pdf(source_root / "05_물류" / "월간_재고_점검.pdf", [
        "Monthly inventory inspection", "Count available stock by product and warehouse.",
        "Escalate any count below the reorder point to logistics operations.",
    ])

    _write_docx(source_root / "06_고객지원" / "고객응대_매뉴얼.docx", "고객응대 매뉴얼", [
        "일반 문의의 최초 응답 목표는 영업일 기준 4시간 이내입니다.",
        "반품 문의는 승인된 반품·교환 정책을 기준으로 안내합니다.",
    ])
    _write_text(source_root / "06_고객지원" / "FAQ_2026.txt", """고객지원 FAQ
배송 지연 보상은 승인된 배송 지연 보상 정책을 확인한다.
반품 가능 여부는 구매일, 상품 상태, 영수증 보유 여부를 함께 확인한다.""")
    _write_csv(source_root / "06_고객지원" / "CS_유형_코드.csv", ["cs_code", "cs_category", "owner_team"], [
        {"cs_code": "CS01", "cs_category": "배송문의", "owner_team": "고객지원팀"},
        {"cs_code": "CS02", "cs_category": "반품문의", "owner_team": "고객지원팀"},
        {"cs_code": "CS03", "cs_category": "상품문의", "owner_team": "영업운영팀"},
    ])

    _write_pdf(source_root / "07_정산" / "세금계산서_처리_안내.pdf", [
        "Tax invoice processing guide", "Confirm the customer ID before issuing a tax invoice.",
        "Close monthly invoices on the fifth business day of the following month.",
    ])
    _write_xlsx(source_root / "07_정산" / "정산_캘린더_2026.xlsx", [
        ("SettlementCalendar", ["month", "invoice_close_day", "payment_review_day"], [
            {"month": f"2026-{month:02d}", "invoice_close_day": 5, "payment_review_day": 10}
            for month in range(1, 13)
        ]),
    ])


def _numeric(relative_tolerance: float = 0.0) -> dict[str, Any]:
    return {"type": "numeric", "relative_tolerance": relative_tolerance}


def _exact() -> dict[str, str]:
    return {"type": "exact"}


def _knowledge_plan(query: str, source: str) -> dict[str, Any]:
    return {
        "table_id_policy": "No table ID is needed; discover the document through search_documents.",
        "steps": [
            {"tool": "search_documents", "query": query, "required_source": source},
            {"tool": "read_document", "source": source},
        ],
    }


def _table_plan(query: str, source: str, required_columns: list[str], query_arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_id_policy": "Use the exact table ID returned by search_documents metadata; never guess or hard-code it.",
        "steps": [
            {"tool": "search_documents", "query": query, "required_source": source},
            {"tool": "query_table", "source": source, "required_columns": required_columns, "arguments": query_arguments},
        ],
    }


def _cross_plan(query: str, customer_value: str, query_arguments: dict[str, Any]) -> dict[str, Any]:
    customers_source = "03_영업/거래처_마스터.xlsx"
    orders_source = "04_주문/주문_원장_2026.xlsx"
    return {
        "table_id_policy": "Discover exact table IDs from search_documents metadata; benchmark plans contain no internal table IDs.",
        "steps": [
            {"tool": "search_documents", "query": query, "required_source": customers_source},
            {
                "tool": "lookup_value", "source": customers_source,
                "required_columns": ["customer_id", "customer_name"], "match_column": "customer_name",
                "value": customer_value, "return_column": "customer_id", "save_as": "customer_id",
            },
            {"tool": "search_documents", "query": "주문 원장 order_id customer_id product_id order_date amount", "required_source": orders_source},
            {
                "tool": "query_table", "source": orders_source,
                "required_columns": ["order_id", "customer_id", "product_id", "order_date", "amount"],
                "arguments": query_arguments,
            },
        ],
    }


def _cross_product_inventory_plan(product_value: str, query_arguments: dict[str, Any]) -> dict[str, Any]:
    products_source = "03_영업/품목_마스터.csv"
    inventory_source = "05_물류/재고_현황_2026-09.xlsx"
    return {
        "table_id_policy": "Discover exact table IDs from search_documents metadata; benchmark plans contain no internal table IDs.",
        "steps": [
            {"tool": "search_documents", "query": "품목 마스터 product_id product_name", "required_source": products_source},
            {
                "tool": "lookup_value", "source": products_source,
                "required_columns": ["product_id", "product_name"], "match_column": "product_name",
                "value": product_value, "return_column": "product_id", "save_as": "product_id",
            },
            {"tool": "search_documents", "query": "재고 현황 product_id available_qty warehouse", "required_source": inventory_source},
            {
                "tool": "query_table", "source": inventory_source,
                "required_columns": ["product_id", "available_qty"], "arguments": query_arguments,
            },
        ],
    }


def _benchmark_tasks(data: dict[str, Any]) -> list[dict[str, Any]]:
    customers = {row["customer_name"]: row["customer_id"] for row in data["customers"]}
    products = {row["product_name"]: row["product_id"] for row in data["products"]}
    orders = data["orders"]
    inventory = data["inventory"]
    returns = data["returns"]
    active_customer_count = len(data["customers"])
    september_total = sum(row["amount"] for row in orders if row["order_date"].startswith("2026-09"))
    last_c005 = max(row["order_date"] for row in orders if row["customer_id"] == customers["그린테이블"])
    largest_stock = max(inventory, key=lambda row: (row["available_qty"], row["product_id"]))["product_id"]
    return_rate = sum(row["returned_qty"] for row in returns) / sum(row["shipped_qty"] for row in returns)
    c001_august = sum(row["amount"] for row in orders if row["customer_id"] == customers["한빛상사"] and row["order_date"].startswith("2026-08"))
    c003_september = sum(row["amount"] for row in orders if row["customer_id"] == customers["동해상사"] and row["order_date"].startswith("2026-09"))
    p003_stock = sum(row["available_qty"] for row in inventory if row["product_id"] == products["프리미엄 홍차 세트"])
    c006_last = max(row["order_date"] for row in orders if row["customer_id"] == customers["윤성마트"])
    c002_july = sum(row["amount"] for row in orders if row["customer_id"] == customers["새봄마트"] and row["order_date"].startswith("2026-07"))
    c007_aug_returns = sum(row["returned_qty"] for row in returns if row["customer_id"] == customers["아람리빙"] and row["return_date"].startswith("2026-08"))
    c009_top_order = max(
        (row for row in orders if row["customer_id"] == customers["다온유통"]),
        key=lambda row: (row["amount"], row["order_id"]),
    )["product_id"]

    tasks: list[dict[str, Any]] = [
        {
            "task_id": "K01_RETURN_WINDOW", "category": "knowledge",
            "question": "현재 반품 가능 기간은 며칠인가요?", "expected_answer": 30,
            "scoring_method": _numeric(), "required_sources": ["02_정책/반품_교환_정책_2026.docx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _knowledge_plan("반품 교환 정책 반품 가능 기간", "02_정책/반품_교환_정책_2026.docx"),
        },
        {
            "task_id": "K02_RETURN_REQUIREMENTS", "category": "knowledge",
            "question": "반품 접수 시 함께 확인해야 할 상품 상태 요건을 모두 답하세요.",
            "expected_answer": ["미개봉", "미사용", "재판매 가능 상태", "원본 영수증"],
            "scoring_method": {"type": "set", "required_items": ["미개봉", "미사용", "재판매 가능 상태", "원본 영수증"], "reject_negated_items": True},
            "required_sources": ["02_정책/반품_교환_정책_2026.docx"], "primary_blocker": "none", "control": False,
            "tool_plan": _knowledge_plan("반품 접수 미개봉 미사용 재판매 가능 상태 원본 영수증", "02_정책/반품_교환_정책_2026.docx"),
        },
        {
            "task_id": "K03_DELAY_COMPENSATION_THRESHOLD", "category": "knowledge",
            "question": "배송 지연 보상은 지연 후 몇 영업일부터 시작되나요?", "expected_answer": 3,
            "scoring_method": _numeric(), "required_sources": ["02_정책/배송_지연_보상_2026.docx"],
            "primary_blocker": "none", "control": True,
            "tool_plan": _knowledge_plan("배송 지연 보상 영업일", "02_정책/배송_지연_보상_2026.docx"),
        },
        {
            "task_id": "K04_DISCOUNT_APPROVER", "category": "knowledge",
            "question": "주문금액 100만원 이상 개별 할인 요청의 승인 담당자는 누구인가요?", "expected_answer": "영업운영팀장",
            "scoring_method": _exact(), "required_sources": ["02_정책/할인_승인_규정.docx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _knowledge_plan("할인 승인 주문금액 영업운영팀장", "02_정책/할인_승인_규정.docx"),
        },
        {
            "task_id": "K05_STOCK_REFERENCE_FIELD", "category": "knowledge",
            "question": "재고 조회의 기준 수량 필드는 무엇인가요?", "expected_answer": "available_qty",
            "scoring_method": _exact(), "required_sources": ["05_물류/창고_운영_매뉴얼.docx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _knowledge_plan("창고 운영 매뉴얼 available_qty", "05_물류/창고_운영_매뉴얼.docx"),
        },
        {
            "task_id": "K06_FIRST_RESPONSE_TARGET", "category": "knowledge",
            "question": "일반 문의의 최초 응답 목표는 영업일 기준 몇 시간 이내인가요?", "expected_answer": 4,
            "scoring_method": _numeric(), "required_sources": ["06_고객지원/고객응대_매뉴얼.docx"],
            "primary_blocker": "none", "control": True,
            "tool_plan": _knowledge_plan("고객응대 매뉴얼 최초 응답 시간", "06_고객지원/고객응대_매뉴얼.docx"),
        },
        {
            "task_id": "O01_CUSTOMER_COUNT", "category": "operations",
            "question": "등록된 거래처는 총 몇 곳인가요?", "expected_answer": active_customer_count,
            "scoring_method": _numeric(), "required_sources": ["03_영업/거래처_마스터.xlsx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _table_plan("거래처 마스터 customer_id customer_name", "03_영업/거래처_마스터.xlsx", ["customer_id"], {"aggregation": {"op": "count", "field": "customer_id", "alias": "customer_count"}, "select": ["customer_count"]}),
        },
        {
            "task_id": "O02_SEPTEMBER_ORDER_TOTAL", "category": "operations",
            "question": "2026년 9월 전체 주문금액은 얼마인가요?", "expected_answer": september_total,
            "scoring_method": _numeric(), "required_sources": ["04_주문/주문_원장_2026.xlsx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _table_plan("주문 원장 order_date amount", "04_주문/주문_원장_2026.xlsx", ["order_date", "amount"], {"filters": [{"field": "order_date", "op": "prefix", "value": "2026-09"}], "aggregation": {"op": "sum", "field": "amount", "alias": "total_amount"}, "select": ["total_amount"]}),
        },
        {
            "task_id": "O03_GREEN_TABLE_LAST_ORDER", "category": "cross_file",
            "question": "그린테이블의 마지막 주문일은 언제인가요?", "expected_answer": last_c005,
            "scoring_method": _exact(), "required_sources": ["03_영업/거래처_마스터.xlsx", "04_주문/주문_원장_2026.xlsx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _cross_plan("거래처 마스터 주문 원장 customer_id 그린테이블", "그린테이블", {"filters": [{"field": "customer_id", "op": "eq", "value_from": "customer_id"}], "aggregation": {"op": "max", "field": "order_date", "alias": "last_order_date"}, "select": ["last_order_date"]}),
        },
        {
            "task_id": "O04_PRODUCT_MASTER_COUNT", "category": "operations",
            "question": "품목마스터에 등록된 상품은 총 몇 개인가요?", "expected_answer": len(data["products"]),
            "scoring_method": _numeric(), "required_sources": ["03_영업/품목_마스터.csv"],
            "primary_blocker": "none", "control": True,
            "tool_plan": _table_plan("품목 마스터 product_id product_name", "03_영업/품목_마스터.csv", ["product_id"], {"aggregation": {"op": "count", "field": "product_id", "alias": "product_count"}, "select": ["product_count"]}),
        },
        {
            "task_id": "O05_HIGHEST_AVAILABLE_STOCK", "category": "operations",
            "question": "현재 가용재고가 가장 많은 품목 ID는 무엇인가요?", "expected_answer": largest_stock,
            "scoring_method": _exact(), "required_sources": ["05_물류/재고_현황_2026-09.xlsx"],
            "primary_blocker": "none", "control": True,
            "tool_plan": _table_plan("재고 현황 product_id available_qty", "05_물류/재고_현황_2026-09.xlsx", ["product_id", "available_qty"], {"select": ["product_id", "available_qty"], "order_by": [{"field": "available_qty", "direction": "desc"}], "limit": 1}),
        },
        {
            "task_id": "O06_RETURN_RATE", "category": "operations",
            "question": "반품원장에서 반품수량 합계를 분자로, 출고수량 합계를 분모로 계산한 반품률은 얼마인가요?", "expected_answer": return_rate,
            "scoring_method": _numeric(0.000001), "required_sources": ["04_주문/반품_원장_2026.csv"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _table_plan("반품 원장 returned_qty shipped_qty", "04_주문/반품_원장_2026.csv", ["returned_qty", "shipped_qty"], {"aggregation": {"op": "rate", "numerator_field": "returned_qty", "denominator_field": "shipped_qty", "alias": "return_rate"}, "select": ["return_rate"]}),
        },
        {
            "task_id": "O07_SEOUL_LEAD_TIME", "category": "operations",
            "question": "서울 권역의 표준 배송 리드타임은 며칠인가요?", "expected_answer": 1,
            "scoring_method": _numeric(), "required_sources": ["05_물류/배송권역_리드타임.csv"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _table_plan("배송 권역 리드타임 서울 standard_lead_days", "05_물류/배송권역_리드타임.csv", ["zone_name", "standard_lead_days"], {"filters": [{"field": "zone_name", "op": "eq", "value": "서울"}], "select": ["standard_lead_days"]}),
        },
        {
            "task_id": "C01_HANBIT_AUGUST_TOTAL", "category": "cross_file",
            "question": "한빛상사의 2026년 8월 주문금액은 얼마인가요?", "expected_answer": c001_august,
            "scoring_method": _numeric(), "required_sources": ["03_영업/거래처_마스터.xlsx", "04_주문/주문_원장_2026.xlsx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _cross_plan("거래처 마스터 주문 원장 customer_id 한빛상사", "한빛상사", {"filters": [{"field": "customer_id", "op": "eq", "value_from": "customer_id"}, {"field": "order_date", "op": "prefix", "value": "2026-08"}], "aggregation": {"op": "sum", "field": "amount", "alias": "total_amount"}, "select": ["total_amount"]}),
        },
        {
            "task_id": "C02_DONGHAE_SEPTEMBER_TOTAL", "category": "cross_file",
            "question": "주식회사 동해상사의 2026년 9월 주문금액은 얼마인가요?", "expected_answer": c003_september,
            "scoring_method": _numeric(), "required_sources": ["03_영업/거래처_마스터.xlsx", "04_주문/주문_원장_2026.xlsx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _cross_plan("거래처 마스터 주문 원장 customer_id 동해상사", "주식회사 동해상사", {"filters": [{"field": "customer_id", "op": "eq", "value_from": "customer_id"}, {"field": "order_date", "op": "prefix", "value": "2026-09"}], "aggregation": {"op": "sum", "field": "amount", "alias": "total_amount"}, "select": ["total_amount"]}),
        },
        {
            "task_id": "C03_TEA_STOCK", "category": "cross_file",
            "question": "프리미엄 홍차 세트의 현재 가용재고는 몇 개인가요?", "expected_answer": p003_stock,
            "scoring_method": _numeric(), "required_sources": ["03_영업/품목_마스터.csv", "05_물류/재고_현황_2026-09.xlsx"],
            "primary_blocker": "none", "control": True,
            "tool_plan": _cross_product_inventory_plan("프리미엄 홍차 세트", {"filters": [{"field": "product_id", "op": "eq", "value_from": "product_id"}], "aggregation": {"op": "sum", "field": "available_qty", "alias": "available_qty"}, "select": ["available_qty"]}),
        },
        {
            "task_id": "C04_YUNSEONG_LAST_ORDER", "category": "cross_file",
            "question": "윤성마트의 마지막 주문일은 언제인가요?", "expected_answer": c006_last,
            "scoring_method": _exact(), "required_sources": ["03_영업/거래처_마스터.xlsx", "04_주문/주문_원장_2026.xlsx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _cross_plan("거래처 마스터 주문 원장 customer_id 윤성마트", "윤성마트", {"filters": [{"field": "customer_id", "op": "eq", "value_from": "customer_id"}], "aggregation": {"op": "max", "field": "order_date", "alias": "last_order_date"}, "select": ["last_order_date"]}),
        },
        {
            "task_id": "C05_SAEBOM_JULY_TOTAL", "category": "cross_file",
            "question": "새봄마트의 2026년 7월 주문금액은 얼마인가요?", "expected_answer": c002_july,
            "scoring_method": _numeric(), "required_sources": ["03_영업/거래처_마스터.xlsx", "04_주문/주문_원장_2026.xlsx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _cross_plan("거래처 마스터 주문 원장 customer_id 새봄마트", "새봄마트", {"filters": [{"field": "customer_id", "op": "eq", "value_from": "customer_id"}, {"field": "order_date", "op": "prefix", "value": "2026-07"}], "aggregation": {"op": "sum", "field": "amount", "alias": "total_amount"}, "select": ["total_amount"]}),
        },
        {
            "task_id": "C06_ARAM_AUGUST_RETURNS", "category": "cross_file",
            "question": "아람리빙의 2026년 8월 반품 수량은 몇 개인가요?", "expected_answer": c007_aug_returns,
            "scoring_method": _numeric(), "required_sources": ["03_영업/거래처_마스터.xlsx", "04_주문/반품_원장_2026.csv"],
            "primary_blocker": "none", "control": False,
            "tool_plan": {
                "table_id_policy": "Discover exact table IDs from search_documents metadata; benchmark plans contain no internal table IDs.",
                "steps": [
                    {"tool": "search_documents", "query": "거래처 마스터 customer_id 아람리빙", "required_source": "03_영업/거래처_마스터.xlsx"},
                    {"tool": "lookup_value", "source": "03_영업/거래처_마스터.xlsx", "required_columns": ["customer_id", "customer_name"], "match_column": "customer_name", "value": "아람리빙", "return_column": "customer_id", "save_as": "customer_id"},
                    {"tool": "search_documents", "query": "반품 원장 customer_id return_date returned_qty", "required_source": "04_주문/반품_원장_2026.csv"},
                    {"tool": "query_table", "source": "04_주문/반품_원장_2026.csv", "required_columns": ["customer_id", "return_date", "returned_qty"], "arguments": {"filters": [{"field": "customer_id", "op": "eq", "value_from": "customer_id"}, {"field": "return_date", "op": "prefix", "value": "2026-08"}], "aggregation": {"op": "sum", "field": "returned_qty", "alias": "returned_qty"}, "select": ["returned_qty"]}},
                ],
            },
        },
        {
            "task_id": "C07_DAON_TOP_ORDER_PRODUCT", "category": "cross_file",
            "question": "다온유통의 주문 중 금액이 가장 큰 주문의 품목 ID는 무엇인가요?", "expected_answer": c009_top_order,
            "scoring_method": _exact(), "required_sources": ["03_영업/거래처_마스터.xlsx", "04_주문/주문_원장_2026.xlsx"],
            "primary_blocker": "none", "control": False,
            "tool_plan": _cross_plan("거래처 마스터 주문 원장 customer_id 다온유통", "다온유통", {"filters": [{"field": "customer_id", "op": "eq", "value_from": "customer_id"}], "select": ["product_id", "amount"], "order_by": [{"field": "amount", "direction": "desc"}], "limit": 1}),
        },
        {
            "task_id": "K07_VENDOR_FORECAST_ABSTAIN", "category": "knowledge",
            "question": "한빛상사의 2027년 1분기 주문금액 전망은 얼마인가요?", "expected_answer": None,
            "scoring_method": _exact(), "required_sources": ["03_영업/거래처_마스터.xlsx", "04_주문/주문_원장_2026.xlsx"],
            "primary_blocker": "missing_data", "control": False, "expects_abstention": True,
            "tool_plan": {"table_id_policy": "No forecast field exists in the discoverable company evidence; abstain after searching the available sources.", "steps": [{"tool": "search_documents", "query": "한빛상사 2027년 1분기 주문금액 전망", "required_source": "03_영업/거래처_마스터.xlsx"}]},
        },
    ]
    return tasks


def _ground_truth(source_truth: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ax-ground-truth-v2",
        "dataset_id": DATASET_ID,
        "generator_version": GENERATOR_VERSION,
        "derivation": "Answers are independently recomputed from generated runtime-facing Ceiling source files, never copied from benchmark declarations.",
        "independent_method": source_truth["method"],
        "structured_row_counts": source_truth["structured_row_counts"],
        "tasks": [
            {
                "task_id": task_id,
                "expected_answer": expected_answer,
                "calculation_source": "independent_runtime_source_readers",
            }
            for task_id, expected_answer in source_truth["answers"].items()
        ],
    }


def _manifest(source_root: Path) -> dict[str, Any]:
    files = sorted(path for path in source_root.rglob("*") if path.is_file())
    entries = [
        {
            "relative_path": path.relative_to(source_root).as_posix(),
            "format": path.suffix.lower().lstrip("."),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "runtime_facing": True,
        }
        for path in files
    ]
    format_counts: dict[str, int] = {}
    for entry in entries:
        format_counts[entry["format"]] = format_counts.get(entry["format"], 0) + 1
    return {
        "schema_version": "ax-ceiling-dataset-manifest-v1",
        "dataset_id": DATASET_ID,
        "condition": "ceiling",
        "company": {"name": "한빛유통", "industry": "식품·생활용품 유통", "employee_count": 45, "synthetic": True},
        "generator": {"version": GENERATOR_VERSION, "random_seed": RANDOM_SEED, "as_of_date": AS_OF_DATE.isoformat()},
        "source_root": SOURCE_RELATIVE.as_posix(),
        "file_count": len(entries),
        "format_counts": dict(sorted(format_counts.items())),
        "files": entries,
        "runtime_scan_report": "ceiling_scan_report.json",
        "benchmark_artifacts_are_runtime_resources": False,
    }


def _control_sources(source_root: Path, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    protected_sources = sorted({source for task in tasks if task["control"] for source in task["required_sources"]})
    control_task_ids = [task["task_id"] for task in tasks if task["control"]]
    families = []
    for relative_path in protected_sources:
        path = Path(relative_path)
        normalized_stem = re.sub(r"(?:copy|duplicate|final|v\d+|수정)$", "", re.sub(r"[^0-9a-z가-힣]+", "", path.stem.casefold()))
        families.append({
            "family_id": f"{path.parent.as_posix()}/{normalized_stem}",
            "canonical_source": relative_path,
            "allowed_members": [relative_path],
        })
    return {
        "schema_version": "ax-control-sources-v2",
        "dataset_id": DATASET_ID,
        "control_task_ids": control_task_ids,
        "protected_sources": protected_sources,
        "protected_source_sha256": {
            relative_path: _sha256(source_root / relative_path) for relative_path in protected_sources
        },
        "protected_logical_families": families,
        "protection_rule": "Later defect injection must preserve every protected source byte-for-byte and may not add a duplicate or conflicting sibling in a protected logical family.",
        "later_retrieval_result_stability_metric": {
            "name": "protected_control_retrieval_result_stability",
            "definition": "After a future injection, each control task must retain its Ceiling source hash, required-source retrieval rank@k, and deterministic score classification under the same frozen retrieval contract.",
            "execution_status": "NOT_RUN",
        },
    }


def _task_to_defect_manifest(tasks: list[dict[str, Any]], controls: dict[str, Any]) -> dict[str, Any]:
    protected = set(controls["protected_sources"])
    control_ids = controls["control_task_ids"]
    entries = []
    for task in tasks:
        if task["control"]:
            continue
        affected_sources = list(task["required_sources"])
        entries.append({
            "task_id": task["task_id"],
            "primary_defect_id": f"DEF_{task['task_id']}_SOURCE_READINESS",
            "primary_defect_type": "source_readiness",
            "affected_sources": affected_sources,
            "protected_dependencies": sorted(protected),
            "control_task_ids_excluded": control_ids,
        })
    return {
        "schema_version": "ax-task-to-defect-v1",
        "dataset_id": DATASET_ID,
        "status": "PLANNING_ONLY_NO_DEFECTS_INJECTED",
        "task_defects": entries,
    }


def _runtime_blind_samples(tasks: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    samples = []
    for task in tasks:
        projected = project_runtime_prompt(task)
        samples.append({**projected, "runtime_prompt": construct_runtime_prompt(projected)})
    artifact = {
        "schema_version": "ax-runtime-blind-samples-v1",
        "execution_status": "NOT_RUN",
        "included_fields": ["category", "question"],
        "samples": samples,
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AX blind runtime sample",
        "type": "object",
        "required": ["category", "question", "runtime_prompt"],
        "additionalProperties": False,
        "properties": {
            "category": {"enum": ["knowledge", "operations", "cross_file"]},
            "question": {"type": "string", "minLength": 1},
            "runtime_prompt": {"type": "string", "minLength": 1},
        },
    }
    return artifact, schema


def _provenance() -> str:
    return """# Ceiling dataset provenance

## Scope

`sample_data/ceiling_company` is a clean, internally consistent synthetic dataset for the AX Benchmark Mode Ceiling condition. It represents **한빛유통**, a 45-person Korean SME distributor of food and household goods. All company names, documents, product names, customers, identifiers, policies, and figures are fictional.

## Numeric distributions

No public dataset was incorporated. The deterministic generator uses Python's standard-library pseudo-random generator with seed `20260921` to create an intentionally realistic distribution:

- 180 orders across 2026-05-01 through the fixed as-of date 2026-09-21;
- weighted customer and product frequencies, rather than uniform selection;
- gamma-distributed integer quantities, bounded from 1 to 42;
- product-specific unit prices and exact `amount = quantity × unit_price` values;
- inventory quantities using a separate bounded gamma distribution;
- returns sampled from shipped orders with quantities no greater than the shipped quantity.

Because these numbers are generated from code rather than copied from a public source, there is no external data license to attribute. The generated fixture and its code are maintained as project test data.

## Leakage boundary

The company folder and `ceiling_scan_report.json` are runtime-facing evidence only. `benchmark_tasks.json`, `ground_truth.json`, `control_sources.json`, and `ceiling_validation.json` are evaluation-only artifacts and are not placed in the runtime company folder or the Kiro agent resources.
"""


def generate_ceiling_dataset(output_root: Path = ROOT) -> dict[str, Path]:
    """Write all requested Ceiling artifacts beneath *output_root* deterministically."""
    output_root = output_root.resolve()
    source_root = output_root / SOURCE_RELATIVE
    if source_root.exists():
        shutil.rmtree(source_root)
    source_root.mkdir(parents=True, exist_ok=True)
    data = _company_data()
    _write_company_files(source_root, data)
    _set_fixed_times(source_root)

    tasks = _benchmark_tasks(data)
    manifest = _manifest(source_root)
    controls = sorted({source for task in tasks if task["control"] for source in task["required_sources"]})
    benchmark = {
        "schema_version": "ax-benchmark-tasks-v1",
        "dataset_id": DATASET_ID,
        "condition": "ceiling",
        "task_count": len(tasks),
        "tasks": tasks,
    }
    paths = {
        "source_root": source_root,
        "dataset_manifest": output_root / "dataset_manifest.json",
        "benchmark_tasks": output_root / "benchmark_tasks.json",
        "ground_truth": output_root / "ground_truth.json",
        "control_sources": output_root / "control_sources.json",
        "task_to_defect_manifest": output_root / "task_to_defect_manifest.json",
        "runtime_blind_samples": output_root / "runtime_blind_samples.json",
        "runtime_blind_sample_schema": output_root / "runtime_blind_sample.schema.json",
        "dataset_provenance": output_root / "dataset_provenance.md",
        "scan_report": output_root / "ceiling_scan_report.json",
    }
    report = scan_folder(source_root, live_llm=detect_live_llm_status({}, local_runtime_available=False))
    write_report(report, paths["scan_report"])
    control_sources = _control_sources(source_root, tasks)
    blind_samples, blind_schema = _runtime_blind_samples(tasks)
    _write_json(paths["dataset_manifest"], manifest)
    _write_json(paths["benchmark_tasks"], benchmark)
    _write_json(paths["ground_truth"], _ground_truth(independently_compute_truth(source_root)))
    _write_json(paths["control_sources"], control_sources)
    _write_json(paths["task_to_defect_manifest"], _task_to_defect_manifest(tasks, control_sources))
    _write_json(paths["runtime_blind_samples"], blind_samples)
    _write_json(paths["runtime_blind_sample_schema"], blind_schema)
    paths["dataset_provenance"].write_text(_provenance(), encoding="utf-8")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the clean AX Ceiling company dataset and benchmark artifacts")
    parser.add_argument("--output-root", type=Path, default=ROOT, help="Project root or isolated test output root")
    args = parser.parse_args()
    paths = generate_ceiling_dataset(args.output_root)
    print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
