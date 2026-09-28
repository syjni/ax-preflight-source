from __future__ import annotations

from ax_product.evidence import check_evidence
from ax_product.evidence_v2 import check_evidence_v2, evidence_v2_reason
from tests.test_evidence_checker import delivered, record


def query_output(row: dict, *, matched: int = 10) -> dict:
    return {
        "table_id": "TABLE_1",
        "rows": [row],
        "rows_returned": 1,
        "result_rows_before_limit": 1,
        "source_rows_matched": matched,
        "truncated": False,
        "source_ids": ["TABLE_1"],
    }


def test_v2_promotes_query_aggregate_values_with_separate_units() -> None:
    cases = (
        ("10곳", "거래처", {"count": 10}, False),
        ("4,980,700원", "KRW", {"sum_amount": 4980700}, False),
        ("2026-09-21", "date", {"max_order_date": "2026-09-21"}, False),
        (3, None, {"min_priority": 3}, True),
    )
    for answer, unit, row, v1_is_direct in cases:
        delivery = delivered(answer=answer, unit=unit)
        records = [record(query_output(row))]

        assert (check_evidence(delivery, records).verdict == "DIRECT_MATCH") is v1_is_direct
        assert check_evidence_v2(delivery, records).verdict == "DIRECT_MATCH"
        assert evidence_v2_reason(delivery, records) == "QUERY_AGGREGATE_VALUE"


def test_v2_normalizes_dates_in_structured_cells() -> None:
    delivery = delivered(answer="2026.9.21", unit="date")
    records = [record(query_output({"order_date": "2026-09-21"}, matched=1))]

    assert check_evidence_v2(delivery, records).verdict == "DIRECT_MATCH"
    assert evidence_v2_reason(delivery, records) == "DATE_NORMALIZATION"


def test_v2_accepts_exact_structured_identifier_with_nonquantity_unit() -> None:
    delivery = delivered(answer="P005", unit="product_id")
    records = [record({
        **query_output({"product_id": "P005"}),
        "result_rows_before_limit": 12,
        "source_rows_matched": 12,
        "truncated": True,
    })]

    assert check_evidence_v2(delivery, records).verdict == "DIRECT_MATCH"
    assert evidence_v2_reason(delivery, records) == "STRUCTURED_SCALAR_VALUE"


def test_v2_accepts_complete_multirow_mapping() -> None:
    delivery = delivered(answer=(
        "배송문의(CS01)와 반품문의(CS02)는 고객지원팀이 담당하고, "
        "상품문의(CS03)는 영업운영팀이 담당합니다."
    ))
    records = [record({
        "table_id": "TABLE_1",
        "rows": [
            {"category": "배송문의", "code": "CS01", "team": "고객지원팀"},
            {"category": "반품문의", "code": "CS02", "team": "고객지원팀"},
            {"category": "상품문의", "code": "CS03", "team": "영업운영팀"},
        ],
        "rows_returned": 3,
        "result_rows_before_limit": 3,
        "source_rows_matched": 3,
        "truncated": False,
        "source_ids": ["TABLE_1"],
    })]

    assert check_evidence_v2(delivery, records).verdict == "DIRECT_MATCH"
    assert evidence_v2_reason(delivery, records) == "COMPLETE_TABLE_MAPPING"


def test_v2_accepts_composite_values_from_one_structured_row() -> None:
    delivery = delivered(
        answer="P005 (WH-SEOUL 창고, 가용재고 281)", unit="available_qty"
    )
    records = [record(query_output({
        "product_id": "P005",
        "warehouse_code": "WH-SEOUL",
        "available_qty": 281,
        "reserved_qty": 13,
    }))]

    assert check_evidence_v2(delivery, records).verdict == "DIRECT_MATCH"
    assert evidence_v2_reason(delivery, records) == "STRUCTURED_COMPOSITE_VALUE"


def test_v2_accepts_typed_numeric_value_returned_by_lookup() -> None:
    delivery = delivered(
        answer="월별 세금계산서는 익월 5번째 영업일에 마감합니다.",
        unit="business_day_of_next_month",
    )
    records = [record({
        "table_id": "TABLE_1",
        "value": 5,
        "matched_rows": 1,
        "ambiguous": False,
        "source_ids": ["TABLE_1"],
    }, tool="lookup_value")]

    assert check_evidence_v2(delivery, records).verdict == "DIRECT_MATCH"
    assert evidence_v2_reason(delivery, records) == "STRUCTURED_LOOKUP_NUMERIC_VALUE"


def test_v2_accepts_exact_text_composite_across_structured_sources() -> None:
    delivery = delivered(
        answer="유기농 그래놀라 (product_id: P005)", unit="product_id",
        source_ids=["TABLE_1", "TABLE_2"],
    )
    records = [
        record(query_output({"product_id": "P005"}), sequence=1),
        record({
            "table_id": "TABLE_2",
            "value": "유기농 그래놀라",
            "matched_rows": 1,
            "ambiguous": False,
            "source_ids": ["TABLE_2"],
        }, tool="lookup_value", sequence=2),
    ]

    assert check_evidence_v2(delivery, records).verdict == "DIRECT_MATCH"
    assert evidence_v2_reason(delivery, records) == "STRUCTURED_MULTI_SOURCE_COMPOSITE"


def test_v2_accepts_no_low_stock_only_when_paged_rows_cover_complete_table() -> None:
    delivery = delivered(answer="없음 (해당 품목 없음)")
    first = {
        "table_id": "TABLE_1",
        "rows": [
            {"product_id": "P001", "available_qty": 10, "reorder_point": 5},
        ],
        "rows_returned": 1,
        "result_rows_before_limit": 2,
        "source_rows_matched": 2,
        "truncated": True,
        "source_ids": ["TABLE_1"],
    }
    second = {
        "table_id": "TABLE_1",
        "rows": [
            {"product_id": "P002", "available_qty": 7, "reorder_point": 7},
        ],
        "rows_returned": 1,
        "result_rows_before_limit": 1,
        "source_rows_matched": 1,
        "truncated": False,
        "source_ids": ["TABLE_1"],
    }

    assert check_evidence_v2(delivery, [record(first), record(second, sequence=2)]).verdict == "DIRECT_MATCH"
    assert evidence_v2_reason(delivery, [record(first), record(second, sequence=2)]) == "COMPLETE_TABLE_PREDICATE"
    assert check_evidence_v2(delivery, [record(first)]).verdict != "DIRECT_MATCH"


def test_v2_does_not_promote_uncited_or_partial_source_sets() -> None:
    delivery = delivered(answer="10곳", unit="거래처", source_ids=["TABLE_1", "TABLE_2"])
    records = [record(query_output({"count": 10}))]

    assert check_evidence_v2(delivery, records).verdict != "DIRECT_MATCH"
    assert evidence_v2_reason(delivery, records) is None
