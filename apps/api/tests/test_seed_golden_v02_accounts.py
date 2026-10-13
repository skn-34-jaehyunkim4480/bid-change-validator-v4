import json
from pathlib import Path
from uuid import uuid4

import pytest

from apps.api.app.scripts.seed_golden_v02_accounts import (
    _preserved_baseline_id,
    golden_business_number,
    golden_username,
    load_golden_bundle,
    synthetic_industry_code,
)
from apps.api.app.models import BidNoticeVersion


def test_golden_account_identifiers_are_stable() -> None:
    assert golden_username("J01") == "golden-j01"
    assert golden_username("J32") == "golden-j32"
    assert golden_business_number("J01") == "9902000001"
    assert golden_business_number("J32") == "9902000032"
    assert synthetic_industry_code("J09", 1) == "GOLDEN-J09-01"


def test_golden_username_rejects_non_product_case() -> None:
    with pytest.raises(ValueError):
        golden_username("CH01-BEFORE")


def test_seed_preserves_only_an_earlier_baseline_from_the_same_notice() -> None:
    notice_id = uuid4()
    current = BidNoticeVersion(id=uuid4(), notice_id=notice_id, version_number=2)
    earlier = BidNoticeVersion(id=uuid4(), notice_id=notice_id, version_number=1)
    same = BidNoticeVersion(id=current.id, notice_id=notice_id, version_number=2)
    later = BidNoticeVersion(id=uuid4(), notice_id=notice_id, version_number=3)
    other_notice = BidNoticeVersion(id=uuid4(), notice_id=uuid4(), version_number=1)

    assert _preserved_baseline_id(earlier, current=current) == earlier.id
    assert _preserved_baseline_id(None, current=current) is None
    assert _preserved_baseline_id(same, current=current) is None
    assert _preserved_baseline_id(later, current=current) is None
    assert _preserved_baseline_id(other_notice, current=current) is None


def test_load_golden_bundle_keeps_current_company_cases(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    (tmp_path / "fixture_bundle.json").write_text(
        json.dumps(
            {
                "cases": [
                    {"case_id": "J02"},
                    {"case_id": "CH01-BEFORE"},
                    {"case_id": "J01"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "sources" / "evidence_all.json").write_text(
        json.dumps([{"evidence_id": "E001"}]),
        encoding="utf-8",
    )

    cases, evidence = load_golden_bundle(tmp_path)

    assert [item["case_id"] for item in cases] == ["J01", "J02"]
    assert evidence == {"E001": {"evidence_id": "E001"}}


def test_shared_db_seed_leaves_collected_notices_and_the_code_list_alone() -> None:
    """여럿이 쓰는 DB 에 넣을 때: 수집된 공고의 현재 차수와 업종 코드 목록을 바꾸지 않는다(2026-10-13)."""
    from datetime import datetime, timezone

    from apps.api.app.database import SessionLocal
    from apps.api.app.models import BidNotice, Company, IndustryCode
    from apps.api.app.scripts.seed_golden_v02_accounts import (
        SHARED_DB_POSTED_AT,
        _ensure_notice_version,
        _replace_company_profile,
    )

    db = SessionLocal()
    now = datetime.now(timezone.utc)
    suffix = uuid4().hex[:8].upper()
    collected = BidNotice(bid_notice_no=f"R26SH{suffix}", title="이미 수집된 공고", business_type="SERVICE", first_seen_at=now, last_seen_at=now)
    db.add(collected)
    db.flush()
    real = BidNoticeVersion(notice_id=collected.id, version_number=1, bid_notice_order="000", is_current=True,
                            payload_hash=uuid4().hex, raw_json={}, collected_at=now, source_endpoint="getBidPblancListInfoServc")
    db.add(real)
    db.commit()
    company_id, code = uuid4(), f"GOLDEN-T{suffix[:4]}-01"
    created_notice_no = f"R26SN{suffix}"
    try:
        # 이미 수집된 공고: 골든 차수는 현재가 아닌 차수로 덧붙고, 진짜 차수는 현재 그대로다.
        attached = _ensure_notice_version(db, {"notice_version_id": str(uuid4()), "notice_no": collected.bid_notice_no,
                                               "title": "골든", "source_order": "000"}, create_missing_notices=True, shared_db=True)
        db.flush()
        db.refresh(real)
        assert real.is_current is True and attached.is_current is False and attached.version_number == 2
        assert (real.bid_notice_order, attached.bid_notice_order) == ("000", "000-golden")   # 같은 차수는 따로 둔다
        # 없는 공고: 새로 만들되 게시일을 옛날로 두어 목록 맨 뒤에 오게 한다.
        made = _ensure_notice_version(db, {"notice_version_id": str(uuid4()), "notice_no": created_notice_no,
                                           "title": "골든 새 공고", "source_order": "000"}, create_missing_notices=True, shared_db=True)
        assert made.is_current is True and made.posted_at == SHARED_DB_POSTED_AT and made.bid_closed_at is None
        # 업종 코드 목록에 없는 코드는 비활성으로 들어간다.
        _replace_company_profile(db, {
            "case_id": "J99", "profile_name": f"공용 DB 확인 {suffix}",
            "profile": {"company_id": str(company_id), "company_size": "SMALL", "industries": [{"code": code, "name": "골든 전용 업종"}]},
        }, shared_db=True)
        db.flush()
        assert db.get(IndustryCode, code).active is False
    finally:
        db.rollback()
        for model, key in ((Company, company_id), (IndustryCode, code)):
            found = db.get(model, key)
            if found is not None:
                db.delete(found)
        for number in (collected.bid_notice_no, created_notice_no):
            for notice in db.query(BidNotice).filter(BidNotice.bid_notice_no == number):
                db.delete(notice)
        db.commit()
        db.close()


def test_shared_db_seed_refuses_the_default_or_a_short_password() -> None:
    from apps.api.app.scripts.seed_golden_v02_accounts import DEFAULT_PASSWORD, seed_golden_v02_accounts

    for password in (DEFAULT_PASSWORD, "short-pw-11"):
        with pytest.raises(ValueError, match="shared database"):
            seed_golden_v02_accounts(None, bundle_dir=Path("."), password=password, shared_db=True)


def test_golden_bundle_in_the_repo_has_the_evidence_the_seed_needs() -> None:
    bundle_dir = Path(__file__).resolve().parents[3] / "eval" / "golden" / "qualification-v0.2"
    cases, evidence = load_golden_bundle(bundle_dir)
    assert len(cases) == 32 and len(evidence) >= 64


def test_seed_attaches_evidence_excerpt_documents_so_judgments_are_grounded() -> None:
    """골든 근거 문장으로 「근거 발췌」 문서를 붙인다. 문서가 없으면 판정이 근거를 확인하지 못해 전부 확인 필요가 된다."""
    from datetime import datetime, timezone

    from apps.api.app.database import SessionLocal
    from apps.api.app.models import BidNotice, NoticeDocument
    from apps.api.app.scripts.seed_golden_v02_accounts import EXCERPT_EXTRACTOR, _ensure_evidence_documents

    db = SessionLocal()
    now = datetime.now(timezone.utc)
    notice = BidNotice(bid_notice_no=f"R26GD{uuid4().hex[:8].upper()}", title="골든 문서 확인", business_type="SERVICE", first_seen_at=now, last_seen_at=now)
    db.add(notice)
    db.flush()
    version = BidNoticeVersion(notice_id=notice.id, version_number=1, bid_notice_order="000", is_current=True,
                               payload_hash=uuid4().hex, raw_json={}, collected_at=now, source_endpoint="golden-v0.2")
    db.add(version)
    db.flush()
    excerpt_id, real_id = str(uuid4()), str(uuid4())
    real = NoticeDocument(id=real_id, notice_version_id=version.id, document_order=1, name="진짜 공고문.pdf", url="https://example.test/a",
                          source_field="stdNtceDocUrl", download_status="DOWNLOADED", storage_key="k", file_sha256="f" * 64,
                          extraction_status="EXTRACTED", extracted_text="진짜 본문", extracted_blocks=[{"block_index": 0, "text": "진짜 본문"}],
                          extracted_text_sha256="e" * 64, text_extractor="PYPDF")
    db.add(real)
    db.flush()
    try:
        items = [
            {"evidence_id": "E002", "document_id": excerpt_id, "quote": "본사가 서울특별시에 있는 업체", "location": "공고문 p.2"},
            {"evidence_id": "E001", "document_id": excerpt_id, "quote": "소프트웨어사업자(업종코드 1468)", "location": "공고문 p.1"},
            {"evidence_id": "E003", "document_id": real_id, "quote": "진짜 본문", "location": "p.1"},
        ]
        hashes = _ensure_evidence_documents(db, version=version, items=items,
                                            documents={excerpt_id: {"document_name": "입찰공고문.hwp", "source_url": "https://example.test/b"}})
        made = db.get(NoticeDocument, excerpt_id)
        assert made.name == "[골든셋 근거 발췌] 입찰공고문.hwp" and made.text_extractor == EXCERPT_EXTRACTOR
        assert [block["text"] for block in made.extracted_blocks] == ["소프트웨어사업자(업종코드 1468)", "본사가 서울특별시에 있는 업체"]
        assert made.extraction_status == "EXTRACTED" and made.download_status == "FAILED" and made.storage_key is None   # 원본 파일은 없다
        assert hashes[excerpt_id] == (made.file_sha256, made.extracted_text_sha256) and made.file_sha256
        # 이미 수집된 진짜 문서는 건드리지 않고 그 해시를 쓴다.
        db.refresh(real)
        assert (real.name, real.extracted_text, real.download_status) == ("진짜 공고문.pdf", "진짜 본문", "DOWNLOADED")
        assert hashes[real_id] == ("f" * 64, "e" * 64)
        # 다시 넣어도 발췌 문서는 하나다.
        _ensure_evidence_documents(db, version=version, items=items, documents={})
        assert db.query(NoticeDocument).filter(NoticeDocument.notice_version_id == version.id).count() == 2
    finally:
        db.rollback()
        db.close()
