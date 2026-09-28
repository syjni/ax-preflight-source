from __future__ import annotations

from ax_product.evidence import check_evidence
from ax_product.evidence_v2 import check_evidence_v2
from ax_product.evidence_v3 import check_evidence_v3
from tests.test_evidence_checker import delivered, record


def retired_policy_records():
    return [record({
        "document_id": "FILE_1",
        "content": "14일 기준은 폐기되었고 현재는 30일입니다.",
    }, tool="read_document")]


def test_v3_accepts_equivalent_current_day_quantities() -> None:
    records = [record({
        "document_id": "FILE_1",
        "content": "현재 반품 가능 기간은 30일입니다.",
    }, tool="read_document")]

    for answer in ("30일", "30", 30):
        delivery = delivered(answer=answer, unit="일", source_ids=["FILE_1"])
        assert check_evidence_v3(delivery, records).verdict == "DIRECT_MATCH"


def test_v3_downgrades_retired_quantity_without_mutating_frozen_checkers() -> None:
    records = retired_policy_records()
    retired = delivered(answer="14", unit="일", source_ids=["FILE_1"])

    assert check_evidence(retired, records).verdict == "DIRECT_MATCH"
    assert check_evidence_v2(retired, records).verdict == "DIRECT_MATCH"
    assert check_evidence_v3(retired, records).verdict == "PARTIAL_SUPPORT"


def test_v3_preserves_current_quantity_in_same_sentence() -> None:
    delivery = delivered(answer="30", unit="일", source_ids=["FILE_1"])

    assert check_evidence_v3(delivery, retired_policy_records()).verdict == "DIRECT_MATCH"


def test_v3_preserves_explicitly_non_retired_quantity() -> None:
    records = [record({
        "document_id": "FILE_1",
        "content": "30일 기준은 폐기되지 않았고 현재도 유효합니다.",
    }, tool="read_document")]
    delivery = delivered(answer="30", unit="일", source_ids=["FILE_1"])

    assert check_evidence_v3(delivery, records).verdict == "DIRECT_MATCH"
