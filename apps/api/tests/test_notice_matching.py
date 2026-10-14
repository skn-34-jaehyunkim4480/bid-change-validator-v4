from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from apps.api.app.analysis_models import QualificationAnalysisRun
from apps.api.app.database import SessionLocal
from apps.api.app.models import BidNotice, BidNoticeVersion, NoticeDocument
from apps.api.app.qualification.analysis import qualification_analysis_version_fingerprint
from apps.api.app.qualification.matching import (
    _load_latest_valid_analysis_runs,
    match_cached_notices,
)


def _history_fixture(*, current=False):
    company_id = uuid4()
    other_company_id = uuid4()
    notice_id = uuid4()
    run_id = uuid4()
    case_id = uuid4()
    notice = SimpleNamespace(id=notice_id, bid_notice_no="R26BK00000001", title="기존 공고", announcing_institution_name="테스트 기관")
    version = SimpleNamespace(id=uuid4(), version_number=1, is_current=current)
    now = datetime.now(timezone.utc)
    analysis = SimpleNamespace(id=uuid4(), status="PARTIAL", created_at=now, requirements=[object()], evidence=[])
    judgment = SimpleNamespace(
        id=run_id, preflight_case_id=case_id, notice_version_id=version.id,
        analysis_run_id=analysis.id, analysis_run=analysis, overall_status="ineligible",
        created_at=now, judgments=[SimpleNamespace(status="UNSATISFIED")],
    )
    db = MagicMock()
    db.scalar.return_value = 1
    db.scalars.return_value.all.return_value = [run_id]
    db.execute.return_value.all.return_value = [(judgment, notice, version)]
    return db, company_id, other_company_id, notice, version, judgment


def test_history_is_scoped_to_company_and_preserves_previous_versions() -> None:
    db, company_id, other_company_id, notice, version, judgment = _history_fixture()
    with patch('apps.api.app.qualification.matching._load_company', return_value=object()):
        result = match_cached_notices(db, company_id=company_id, limit=12)

    assert result.analyzed_notice_count == 1
    assert result.returned_count == 1
    assert result.items[0].case_id == judgment.preflight_case_id
    assert result.items[0].notice_id == notice.id
    assert result.items[0].version_number == 1
    assert result.items[0].is_current_version is False
    assert result.items[0].overall_status == "core_unmet"
    assert result.items[0].unsatisfied_count == 1
    assert result.items[0].analysis_status == "PARTIAL"
    ranked_sql = str(db.scalar.call_args.args[0])
    assert "qualification_judgment_runs" in ranked_sql
    assert "preflight_cases" in ranked_sql
    assert "is_current" not in ranked_sql
    assert "input_fingerprint" not in ranked_sql
    assert list(db.scalar.call_args.args[0].compile().params.values()).count(company_id) == 2
    assert other_company_id not in db.scalar.call_args.args[0].compile().params.values()
    query_sql = str(db.execute.call_args.args[0])
    assert "preflight_cases.company_id" in query_sql
    assert "qualification_judgment_runs.company_id" in query_sql


def test_history_supports_legacy_needs_review_status() -> None:
    db, company_id, _, _, _, judgment = _history_fixture()
    judgment.overall_status = "needs_review"
    with patch('apps.api.app.qualification.matching._load_company', return_value=object()):
        result = match_cached_notices(db, company_id=company_id)
    assert result.items[0].overall_status == "needs_review"

def test_history_returns_zero_when_company_has_no_judgments() -> None:
    db = MagicMock()
    db.scalar.return_value = 0
    company_id = uuid4()
    with patch('apps.api.app.qualification.matching._load_company', return_value=object()):
        result = match_cached_notices(db, company_id=company_id)
    assert result.returned_count == 0
    assert result.analyzed_notice_count == 0
    assert result.items == []
    db.execute.assert_not_called()
    db.scalars.assert_not_called()


def test_history_pages_without_rejecting_historical_judgments() -> None:
    db, company_id, _, _, _, _ = _history_fixture(current=True)
    db.scalar.return_value = 31
    with patch('apps.api.app.qualification.matching._load_company', return_value=object()):
        result = match_cached_notices(db, company_id=company_id, limit=12, offset=12)
    assert result.offset == 12
    assert result.analyzed_notice_count == 31
    assert result.returned_count == 1
    params = db.scalars.call_args.args[0].compile().params
    assert 12 in params.values()


def test_latest_valid_run_query_handles_multiple_notices_and_histories() -> None:
    """The SQL query ranks matching lineage only and preserves latest-valid failure."""
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    notice_ids = [uuid4(), uuid4()]
    version_ids = [uuid4(), uuid4()]
    try:
        versions: list[BidNoticeVersion] = []
        for index, (notice_id, version_id) in enumerate(zip(notice_ids, version_ids)):
            notice = BidNotice(
                id=notice_id,
                bid_notice_no=f"TEST-LINEAGE-{notice_id}",
                title=f"lineage test {index}",
                business_type="SERVICE",
                first_seen_at=now,
                last_seen_at=now,
            )
            version = BidNoticeVersion(
                id=version_id,
                notice_id=notice_id,
                version_number=1,
                bid_notice_order="000",
                is_current=True,
                source_endpoint="pytest",
                payload_hash=f"{index + 1:064x}",
                raw_json={},
                collected_at=now,
            )
            document = NoticeDocument(
                id=uuid4(),
                notice_version_id=version_id,
                document_order=0,
                name="notice.pdf",
                url=f"https://example.invalid/{version_id}.pdf",
                source_field="stdNtceDocUrl",
                download_status="DOWNLOADED",
                extraction_status="EXTRACTED",
                extracted_text_sha256=f"{index + 10:064x}",
                extracted_blocks=[{"block_index": 0, "text": "참가자격"}],
            )
            version.documents = [document]
            db.add_all([notice, version])
            versions.append(version)
        db.flush()

        fingerprints = {
            version.id: qualification_analysis_version_fingerprint(version)
            for version in versions
        }
        stale_newer = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_ids[0], contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="SUCCEEDED",
            input_fingerprint="f" * 64, created_at=now + timedelta(minutes=2),
        )
        valid_older = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_ids[0], contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="SUCCEEDED",
            input_fingerprint=fingerprints[version_ids[0]], created_at=now,
        )
        valid_success = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_ids[1], contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="SUCCEEDED",
            input_fingerprint=fingerprints[version_ids[1]], created_at=now,
        )
        valid_failed_newer = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_ids[1], contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="FAILED",
            input_fingerprint=fingerprints[version_ids[1]], created_at=now + timedelta(minutes=1),
        )
        db.add_all([stale_newer, valid_older, valid_success, valid_failed_newer])
        db.commit()

        selected = _load_latest_valid_analysis_runs(db, fingerprints)

        assert selected[version_ids[0]].id == valid_older.id
        assert selected[version_ids[1]].id == valid_failed_newer.id
        assert len(selected) == 2
    finally:
        db.rollback()
        for notice_id in notice_ids:
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
        db.commit()
        db.close()
