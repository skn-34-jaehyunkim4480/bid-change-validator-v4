"""Review candidates must use the same active-notice window as the API."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from apps.api.app.auth_models import AppUser
from apps.api.app.database import engine
from apps.api.app.ml_recommendations.real_dataset import ACTIVE_CANDIDATE_SQL, GOLDEN_COMPANY_SQL
from apps.api.app.models import BidNotice, BidNoticeVersion, Company


def test_review_candidates_exclude_expired_and_cancelled_notices():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    now = datetime.now(timezone.utc)
    cases = [
        ("explicit", now - timedelta(days=1), now + timedelta(days=1), None, True),
        ("assumed", now - timedelta(days=1), None, None, True),
        ("expired", now - timedelta(days=3), now - timedelta(days=1), None, False),
        ("cancelled", now - timedelta(days=1), now + timedelta(days=1), "취소공고", False),
        ("old_unknown", now - timedelta(days=41), None, None, False),
        ("no_posting", None, now + timedelta(days=1), None, True),
    ]
    expected = {}
    try:
        for name, posted_at, closed_at, notice_kind, included in cases:
            notice = BidNotice(
                bid_notice_no=f"ML-ACTIVE-{uuid4().hex}",
                title=f"ML review candidate {name}",
                business_type="SERVICE",
                notice_kind=notice_kind,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(notice)
            session.flush()
            version = BidNoticeVersion(
                notice_id=notice.id,
                version_number=1,
                bid_notice_order="000",
                is_current=True,
                notice_kind=notice_kind,
                posted_at=posted_at,
                bid_closed_at=closed_at,
                source_endpoint="test",
                payload_hash=uuid4().hex * 2,
                raw_json={},
                collected_at=now,
            )
            session.add(version)
            expected[str(notice.id)] = included
        session.flush()
        rows = connection.exec_driver_sql(ACTIVE_CANDIDATE_SQL, (2000,)).all()
        found = {row[0] for row in rows}
        for notice_id, included in expected.items():
            assert (notice_id in found) is included
        no_posting_id = next(
            notice_id for notice_id in expected
            if any(row[0] == notice_id and row[2] == "ML review candidate no_posting" for row in rows)
        )
        assert next(row[7] for row in rows if row[0] == no_posting_id) is None
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_review_company_candidates_only_use_seeded_golden_accounts():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        golden = Company(name="합성회사 J01", company_size="SMALL")
        ordinary = Company(name="합성회사처럼 보이는 일반 회사", company_size="SMALL")
        session.add_all((golden, ordinary))
        session.flush()
        session.add_all((
            AppUser(username="golden-j01", password_hash="unused", company_id=golden.id),
            AppUser(username=f"ordinary-{uuid4().hex}", password_hash="unused", company_id=ordinary.id),
        ))
        session.flush()
        rows = connection.exec_driver_sql(GOLDEN_COMPANY_SQL, (100,)).all()
        ids = {row[0] for row in rows}
        assert str(golden.id) in ids
        assert str(ordinary.id) not in ids
    finally:
        session.close()
        transaction.rollback()
        connection.close()
