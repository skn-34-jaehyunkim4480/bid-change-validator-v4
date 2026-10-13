"""마감이 지난 공고의 검토 건은 '만료됨' 으로 표시되고 지울 수 있다(2026-10-13)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from types import SimpleNamespace

from apps.api.app import membership
from apps.api.app.auth_models import AppUser
from apps.api.app.database import SessionLocal
from apps.api.app.errors import ApiError
from apps.api.app.main import app
from apps.api.app.models import BidNotice, BidNoticeVersion, PreflightCase
from apps.api.app.schemas import BusinessType
from apps.api.app.services.notices import save_notice_snapshot


client = TestClient(app)


def _notice_item(notice_no: str) -> dict:
    return {
        "bidNtceNo": notice_no, "bidNtceOrd": "000", "bidNtceNm": f"{notice_no} 만료 확인용 공고",
        "ntceInsttNm": "테스트 기관", "dminsttNm": "테스트 기관", "bidNtceDt": "2026-09-01 10:00:00",
        "bidClseDt": "2026-09-10 10:00:00", "rgstTyNm": "조달청 또는 나라장터 자체 공고건", "ntceKindNm": "등록공고",
    }


def test_expired_case_is_flagged_and_only_expired_cases_can_be_deleted() -> None:
    db = SessionLocal()
    notice_no = f"R26EXP{uuid4().hex[:8].upper()}"
    notice_id = None
    try:
        _, notice, version = save_notice_snapshot(
            db, item=_notice_item(notice_no), business_type=BusinessType.SERVICE, source_endpoint="getBidPblancListInfoServc",
        )
        db.commit()
        notice_id, version_id = notice.id, version.id

        def set_deadline(value: datetime | None) -> None:
            db.get(BidNoticeVersion, version_id).bid_closed_at = value
            db.commit()

        set_deadline(datetime.now(timezone.utc) + timedelta(days=3))
        created = client.post("/api/v1/preflight-cases", json={
            "notice_id": str(notice_id), "current_version_number": version.version_number, "title": "만료 확인",
        })
        assert created.status_code == 201, created.text
        case_id = created.json()["id"]
        assert created.json()["expired"] is False and created.json()["bid_closed_at"] is not None

        # 마감 전에는 지울 수 없다.
        early = client.delete(f"/api/v1/preflight-cases/{case_id}")
        assert early.status_code == 409 and early.json()["error"]["code"] == "PREFLIGHT_CASE_NOT_EXPIRED"

        # 마감을 모르는 공고는 만료로 보지 않는다.
        set_deadline(None)
        assert client.get(f"/api/v1/preflight-cases/{case_id}").json()["expired"] is False

        set_deadline(datetime.now(timezone.utc) - timedelta(minutes=1))
        assert client.get(f"/api/v1/preflight-cases/{case_id}").json()["expired"] is True
        deleted = client.delete(f"/api/v1/preflight-cases/{case_id}")
        assert deleted.status_code == 204, deleted.text
        assert client.get(f"/api/v1/preflight-cases/{case_id}").status_code == 404
        db.expire_all()
        assert db.get(PreflightCase, case_id) is None
        assert db.get(BidNotice, notice_id) is not None                      # 공고는 그대로 남는다
    finally:
        if notice_id is not None:
            for case in db.query(PreflightCase).filter(PreflightCase.notice_id == notice_id):
                db.delete(case)
            db.commit()
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
                db.commit()
        db.close()


def test_copilot_chat_is_blocked_for_limited_accounts_on_expired_cases(monkeypatch) -> None:
    db = SessionLocal()
    notice_no = f"R26EXC{uuid4().hex[:8].upper()}"
    notice_id = None
    try:
        _, notice, version = save_notice_snapshot(
            db, item=_notice_item(notice_no), business_type=BusinessType.SERVICE, source_endpoint="getBidPblancListInfoServc",
        )
        db.commit()
        notice_id = notice.id
        case = PreflightCase(notice_id=notice_id, current_version_id=version.id, title="만료 채팅 확인")
        db.add(case)
        db.commit()
        user = AppUser(username=f"expiry-{uuid4().hex[:10]}", password_hash="x", role="USER", active=True)
        admin = AppUser(username=f"expiry-{uuid4().hex[:10]}", password_hash="x", role="SYSTEM_ADMIN", active=True)

        def set_deadline(value: datetime) -> None:
            db.get(BidNoticeVersion, version.id).bid_closed_at = value
            db.commit()

        monkeypatch.setattr(membership, "get_settings", lambda: SimpleNamespace(membership_limits_enabled=True, membership_demo_code=None))
        set_deadline(datetime.now(timezone.utc) + timedelta(days=1))
        membership.ensure_case_not_expired(db, user, case)                  # 마감 전에는 통과
        set_deadline(datetime.now(timezone.utc) - timedelta(minutes=1))
        with pytest.raises(ApiError) as blocked:
            membership.ensure_case_not_expired(db, user, case)
        assert blocked.value.status_code == 409 and blocked.value.code == "CASE_EXPIRED"
        membership.ensure_case_not_expired(db, admin, case)                 # 시스템 관리자는 한도 대상이 아니다
        monkeypatch.setattr(membership, "get_settings", lambda: SimpleNamespace(membership_limits_enabled=False, membership_demo_code=None))
        membership.ensure_case_not_expired(db, user, case)                  # 한도를 켜지 않은 환경에서는 막지 않는다
    finally:
        if notice_id is not None:
            for item in db.query(PreflightCase).filter(PreflightCase.notice_id == notice_id):
                db.delete(item)
            db.commit()
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
                db.commit()
        db.close()
