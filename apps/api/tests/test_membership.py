"""요금제 한도: 계정별·월별로 세고, 넘으면 멤버십이 필요하다고 막는다(2026-10-13)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.api.app import membership
from apps.api.app.auth_models import AppUser
from apps.api.app.database import SessionLocal
from apps.api.app.errors import ApiError
from apps.api.app.membership_models import MembershipUsage
from apps.api.app.routers.membership import MembershipRead, MembershipSubscribe


@pytest.fixture
def limits_on(monkeypatch):
    monkeypatch.setattr(membership, "get_settings", lambda: SimpleNamespace(membership_limits_enabled=True, membership_demo_code="1234"))


@pytest.fixture
def db():
    session = SessionLocal()
    created: list[AppUser] = []

    def make(role="USER") -> AppUser:
        user = AppUser(username=f"membership-{uuid4().hex[:12]}", password_hash="x", role=role, active=True)
        session.add(user)
        session.commit()
        created.append(user)
        return user

    session.make_user = make  # type: ignore[attr-defined]
    try:
        yield session
    finally:
        session.rollback()
        for user in created:
            session.delete(session.get(AppUser, user.id))
        session.commit()
        session.close()


def _blocked(call) -> dict:
    with pytest.raises(ApiError) as caught:
        call()
    assert caught.value.status_code == 402 and caught.value.code == "MEMBERSHIP_REQUIRED"
    return caught.value.details


def _check(db, user, notice) -> None:
    membership.ensure_notice_check_allowed(db, user, notice)
    membership.record_notice_check(db, user, notice)
    db.commit()


def test_free_plan_checks_three_notices_a_month_and_rechecks_are_free(limits_on, db) -> None:
    user = db.make_user()
    notices = [uuid4() for _ in range(4)]
    for notice in notices[:3]:
        _check(db, user, notice)
    details = _blocked(lambda: membership.ensure_notice_check_allowed(db, user, notices[3]))
    assert details == {"kind": "NOTICE_CHECK", "plan": "FREE", "used": 3, "limit": 3}
    # 이미 확인한 공고를 다시 검토하는 것은 한도와 무관하고, 다시 세지도 않는다.
    _check(db, user, notices[0])
    assert membership.notice_checks_used(db, user) == 3


def test_free_plan_asks_six_copilot_questions_in_each_notice_conversation(limits_on, db) -> None:
    user = db.make_user()
    case, other_case = uuid4(), uuid4()
    for _ in range(6):
        membership.consume_copilot_question(db, user, case)
    db.commit()
    details = _blocked(lambda: membership.consume_copilot_question(db, user, case))
    assert details == {"kind": "COPILOT_QUESTION", "plan": "FREE", "used": 6, "limit": 6, "scope": "NOTICE"}
    assert membership.copilot_questions_used(db, user, case) == 6            # 막힌 질문은 세지 않는다
    # 다른 공고의 대화는 자기 횟수를 따로 쓴다.
    membership.consume_copilot_question(db, user, other_case)
    db.commit()
    assert membership.membership_state(db, user, other_case)["used"]["copilot_questions"] == 1
    assert membership.membership_state(db, user)["used"]["copilot_questions"] is None
    # 달이 바뀌어도 그 공고 대화에서 쓴 횟수는 그대로다.
    db.query(MembershipUsage).filter(MembershipUsage.user_id == user.id).update({"period": "2000-01"})
    db.commit()
    _blocked(lambda: membership.consume_copilot_question(db, user, case))


def test_usage_is_counted_per_account_and_per_month(limits_on, db) -> None:
    user, other = db.make_user(), db.make_user()
    for _ in range(3):
        _check(db, user, uuid4())
    _check(db, other, uuid4())                                              # 다른 계정은 자기 한도를 쓴다
    assert membership.notice_checks_used(db, other) == 1
    # 지난달에 쓴 것은 이번 달 한도에 들지 않는다.
    db.query(MembershipUsage).filter(MembershipUsage.user_id == user.id).update({"period": "2000-01"})
    db.commit()
    assert membership.notice_checks_used(db, user) == 0
    _check(db, user, uuid4())
    assert membership.current_period(datetime(2026, 10, 31, 15, 30, tzinfo=timezone.utc)) == "2026-11"   # 한국 시간 기준


def test_system_admin_and_environments_without_limits_are_not_counted(limits_on, db, monkeypatch) -> None:
    admin = db.make_user(role="SYSTEM_ADMIN")
    for _ in range(5):
        _check(db, admin, uuid4())
        membership.consume_copilot_question(db, admin, uuid4())
    assert membership.notice_checks_used(db, admin) == 0
    assert db.query(MembershipUsage).filter(MembershipUsage.user_id == admin.id).count() == 0
    assert membership.membership_state(db, admin)["limited"] is False
    membership.ensure_notice_check_allowed(db, None, uuid4())               # 로그인 없이 쓰는 개발 환경

    user = db.make_user()
    monkeypatch.setattr(membership, "get_settings", lambda: SimpleNamespace(membership_limits_enabled=False, membership_demo_code="1234"))
    for _ in range(5):
        _check(db, user, uuid4())
    assert membership.notice_checks_used(db, user) == 0                     # 한도를 켜지 않은 환경에서는 세지도 않는다


def test_membership_code_opens_the_basic_plan_for_a_month(limits_on, db) -> None:
    user = db.make_user()
    for _ in range(3):
        _check(db, user, uuid4())
    with pytest.raises(ApiError) as wrong:
        membership.subscribe_with_code(db, user, "0000")
    assert wrong.value.code == "MEMBERSHIP_CODE_INVALID" and user.membership_plan == "FREE"

    state = MembershipRead.model_validate(membership.subscribe_with_code(db, user, " 1234 "))
    assert state.plan == "BASIC" and state.limits.notice_checks == 20 and state.limits.copilot_questions is None
    assert [(plan.code, plan.copilot_total) for plan in state.plans] == [("FREE", None), ("BASIC", 50), ("UNLIMITED", None)]
    assert state.used.notice_checks == 3 and state.expires_at is not None
    assert [(plan.code, plan.monthly_price) for plan in state.plans] == [("FREE", 0), ("BASIC", 5999), ("UNLIMITED", 15999)]
    _check(db, user, uuid4())                                               # 늘어난 한도 안에서 다시 쓸 수 있다

    # 기한이 지나면 무료 요금제로 돌아간다.
    user.membership_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert membership.effective_plan(user).code == "FREE"
    _blocked(lambda: membership.ensure_notice_check_allowed(db, user, uuid4()))


def test_subscribing_needs_a_login_and_a_configured_code_and_takes_no_card_fields(limits_on, db, monkeypatch) -> None:
    with pytest.raises(ApiError) as anonymous:
        membership.subscribe_with_code(db, None, "1234")
    assert anonymous.value.status_code == 401
    monkeypatch.setattr(membership, "get_settings", lambda: SimpleNamespace(membership_limits_enabled=True, membership_demo_code=None))
    with pytest.raises(ApiError) as unavailable:
        membership.subscribe_with_code(db, db.make_user(), "1234")
    assert unavailable.value.code == "MEMBERSHIP_PAYMENT_UNAVAILABLE"
    # 가입 요청에는 카드 정보를 실을 수 없다.
    with pytest.raises(ValueError):
        MembershipSubscribe.model_validate({"plan": "BASIC", "membership_code": "1234", "card_number": "4111111111111111"})


def test_free_plan_asks_the_general_helper_ten_times_a_month(limits_on, db) -> None:
    user = db.make_user()
    case = uuid4()
    for _ in range(10):
        membership.consume_general_question(db, user)
    db.commit()
    details = _blocked(lambda: membership.consume_general_question(db, user))
    assert details == {"kind": "COPILOT_QUESTION", "plan": "FREE", "used": 10, "limit": 10, "scope": "GENERAL"}
    # 일반 도우미를 다 써도 공고 대화는 자기 한도(6회)를 따로 쓴다.
    membership.consume_copilot_question(db, user, case)
    db.commit()
    assert membership.membership_state(db, user, case)["chat"] == {"scope": "NOTICE", "limit": 6, "used": 1}
    assert membership.membership_state(db, user, membership.GENERAL_SUBJECT)["chat"] == {"scope": "GENERAL", "limit": 10, "used": 10}
    assert membership.membership_state(db, user)["chat"] is None
    # 일반 도우미는 달마다 다시 센다.
    db.query(MembershipUsage).filter(MembershipUsage.user_id == user.id).update({"period": "2000-01"})
    db.commit()
    membership.consume_general_question(db, user)


def test_basic_plan_shares_fifty_questions_across_notices_and_the_general_helper(limits_on, db) -> None:
    user = db.make_user()
    user.membership_plan = "BASIC"
    user.membership_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    db.commit()
    cases = [uuid4(), uuid4()]
    # 공고 하나에 30회를 넘겨도 된다 — 베이직에는 공고마다 두는 한도가 없다.
    for _ in range(35):
        membership.consume_copilot_question(db, user, cases[0])
    for _ in range(5):
        membership.consume_copilot_question(db, user, cases[1])
    for _ in range(10):
        membership.consume_general_question(db, user)
    db.commit()
    total = {"scope": "TOTAL", "limit": 50, "used": 50}
    assert membership.membership_state(db, user, cases[1])["chat"] == total
    assert membership.membership_state(db, user, membership.GENERAL_SUBJECT)["chat"] == total
    details = _blocked(lambda: membership.consume_general_question(db, user))
    assert details == {"kind": "COPILOT_QUESTION", "plan": "BASIC", "used": 50, "limit": 50, "scope": "TOTAL"}
    _blocked(lambda: membership.consume_copilot_question(db, user, uuid4()))
    # 합산 한도는 달마다 다시 센다.
    db.query(MembershipUsage).filter(MembershipUsage.user_id == user.id).update({"period": "2000-01"})
    db.commit()
    membership.consume_copilot_question(db, user, cases[0])
