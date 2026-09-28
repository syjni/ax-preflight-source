from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOUNDARY_DOCS = (
    "README.md",
    "SUBMISSION.md",
    "docs/ARCHITECTURE.md",
    "docs/DATA_AND_PRIVACY.md",
    "docs/DEMO_SCRIPT.md",
)


def test_public_docs_name_the_configured_model_without_claiming_bedrock() -> None:
    for relative in BOUNDARY_DOCS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "claude-sonnet-5" in text, relative
        assert "Bedrock" in text, relative
        assert "Bedrock 직접 연동" in text or "Bedrock을 직접" in text, relative


def test_public_copy_does_not_claim_that_live_model_data_stays_local() -> None:
    combined = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in BOUNDARY_DOCS
    )
    forbidden = (
        "데이터가 외부로 나가지 않습니다",
        "원본 전체 파일은 절대 모델에 전달되지 않습니다",
        "모든 데이터는 로컬에서만 처리됩니다",
    )
    assert not any(claim in combined for claim in forbidden)
    assert "설정된 모델 처리 경계로 전달될 수 있습니다" in combined
