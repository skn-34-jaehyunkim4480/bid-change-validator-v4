"""요금제와 사용 한도(2026-10-13).

계정마다 쓸 수 있는 양을 요금제로 정한다.

    요금제     월 요금    참가자격 확인(한 달 공고 수)   공고 하나의 Copilot 질문
    FREE          0원              3                       6
    BASIC     5,999원             20                      30
    UNLIMITED 15,999원          제한 없음               제한 없음

세는 것:
  - 참가자격 확인: 그 달에 판정을 실행한 **서로 다른 공고** 수. 같은 공고를 다시 검토하는 것은 더 세지 않는다.
    달은 한국 시간의 달력 달이다. 달이 바뀌면 다시 0 부터 센다.
  - Copilot 질문: **공고 대화 하나(검토 건)마다** AI 가 답한 질문 수(입력창 질문과 추천 질문). 달이 바뀌어도, 화면에서
    '새 대화' 를 눌러도 다시 세지 않는다 — 그 공고의 대화에서 쓴 횟수다. 근거 보기 같은 단추와 일반 도우미는 세지 않는다.

세지 않는 계정: 시스템 관리자(SYSTEM_ADMIN), 그리고 로그인 없이 쓰는 개발 환경(user 가 None).
한도는 `MEMBERSHIP_LIMITS_ENABLED` 를 켠 환경에서만 적용한다. 설정의 기본값은 꺼짐이고(테스트·스크립트),
compose 로 띄우는 서비스(로컬·AWS)는 기본으로 켠다.

결제는 붙어 있지 않다. 시연 환경에서는 `MEMBERSHIP_DEMO_CODE` 로 정한 멤버십 코드를 넣으면 BASIC 이 한 달 적용된다.
카드 정보는 이 서버가 받지 않는다(가입 요청에 그런 칸이 없다).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .auth_models import AppUser
from .config import get_settings
from .errors import ApiError
from .membership_models import MembershipUsage
from .models import BidNoticeVersion

PlanCode = Literal["FREE", "BASIC", "UNLIMITED"]
UsageKind = Literal["NOTICE_CHECK", "COPILOT_QUESTION"]
KST = timezone(timedelta(hours=9))
MEMBERSHIP_DAYS = 30


@dataclass(frozen=True)
class Plan:
    code: PlanCode
    name: str
    monthly_price: int
    notice_checks: int | None        # None = 제한 없음
    copilot_questions: int | None


PLANS: dict[str, Plan] = {
    "FREE": Plan("FREE", "무료", 0, 3, 6),
    "BASIC": Plan("BASIC", "베이직", 5_999, 20, 30),
    "UNLIMITED": Plan("UNLIMITED", "무제한", 15_999, None, None),
}
# 멤버십 코드로 열리는 요금제. 시연에서는 가장 저렴한 유료 요금제를 연다.
DEMO_CODE_PLAN: PlanCode = "BASIC"


def version_expired(version: BidNoticeVersion) -> bool:
    """입찰서 제출 마감이 지났는가. 마감을 모르는 공고는 만료로 보지 않는다."""
    closed = version.bid_closed_at
    if closed is None:
        return False
    if closed.tzinfo is None:
        closed = closed.replace(tzinfo=timezone.utc)
    return closed < datetime.now(timezone.utc)


def ensure_case_not_expired(db: Session, user: AppUser | None, case) -> None:
    """마감이 지난 공고의 Copilot 대화는 막는다(한도를 적용하는 계정). 이미 끝난 입찰에 모델 호출을 쓰지 않게 한다."""
    if not limits_apply(user):
        return
    version = db.get(BidNoticeVersion, case.current_version_id)
    if version is not None and version_expired(version):
        raise ApiError(409, "CASE_EXPIRED", "입찰 마감이 지난 공고라 더 질문할 수 없습니다. 대화는 삭제할 수 있습니다.")


def limits_apply(user: AppUser | None) -> bool:
    """이 계정에 한도를 적용하는가."""
    return bool(get_settings().membership_limits_enabled) and user is not None and user.role != "SYSTEM_ADMIN"


def current_period(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(KST).strftime("%Y-%m")


def effective_plan(user: AppUser, now: datetime | None = None) -> Plan:
    """지금 유효한 요금제. 유료 요금제는 기한이 지나면 무료로 돌아간다."""
    plan = PLANS.get(user.membership_plan or "FREE", PLANS["FREE"])
    expires = user.membership_expires_at
    if plan.code != "FREE" and expires is not None and expires < (now or datetime.now(timezone.utc)):
        return PLANS["FREE"]
    return plan


def notice_checks_used(db: Session, user: AppUser, period: str | None = None) -> int:
    """이번 달에 참가자격을 확인한 서로 다른 공고 수."""
    return db.scalar(
        select(func.count(MembershipUsage.id)).where(
            MembershipUsage.user_id == user.id, MembershipUsage.kind == "NOTICE_CHECK",
            MembershipUsage.period == (period or current_period()),
        )
    ) or 0


def copilot_questions_used(db: Session, user: AppUser, case_id: UUID | str) -> int:
    """이 공고 대화(검토 건)에서 쓴 Copilot 질문 수. 달과 무관하게 센다."""
    return db.scalar(
        select(func.count(MembershipUsage.id)).where(
            MembershipUsage.user_id == user.id, MembershipUsage.kind == "COPILOT_QUESTION",
            MembershipUsage.subject_id == str(case_id),
        )
    ) or 0


def _required(kind: UsageKind, plan: Plan, used: int, limit: int) -> ApiError:
    scope = (f"이번 달 참가자격을 확인할 수 있는 공고는 {limit}건" if kind == "NOTICE_CHECK"
             else f"공고 하나에서 AI Copilot 에 물을 수 있는 질문은 {limit}회")
    return ApiError(
        402, "MEMBERSHIP_REQUIRED",
        f"{plan.name} 요금제에서 {scope}까지입니다. 멤버십에 가입하면 더 쓸 수 있습니다.",
        {"kind": kind, "plan": plan.code, "used": used, "limit": limit},
    )


def _notice_counted(db: Session, user: AppUser, notice_id: UUID | str, period: str) -> bool:
    return db.scalar(
        select(MembershipUsage.id).where(
            MembershipUsage.user_id == user.id, MembershipUsage.kind == "NOTICE_CHECK",
            MembershipUsage.period == period, MembershipUsage.subject_id == str(notice_id),
        ).limit(1)
    ) is not None


def ensure_notice_check_allowed(db: Session, user: AppUser | None, notice_id: UUID | str) -> None:
    """이 공고의 참가자격을 확인해도 되는가. 이번 달에 이미 확인한 공고는 늘 된다."""
    if not limits_apply(user):
        return
    plan, period = effective_plan(user), current_period()
    if plan.notice_checks is None or _notice_counted(db, user, notice_id, period):
        return
    used = notice_checks_used(db, user, period)
    if used >= plan.notice_checks:
        raise _required("NOTICE_CHECK", plan, used, plan.notice_checks)


def record_notice_check(db: Session, user: AppUser | None, notice_id: UUID | str) -> None:
    """참가자격을 확인한 공고를 적는다. 같은 달의 같은 공고는 한 번만 남는다. 커밋은 부르는 쪽이 한다."""
    if not limits_apply(user):
        return
    db.execute(
        insert(MembershipUsage)
        .values(user_id=user.id, kind="NOTICE_CHECK", subject_id=str(notice_id), period=current_period())
        .on_conflict_do_nothing()
    )


def consume_copilot_question(db: Session, user: AppUser | None, case_id: UUID | str) -> None:
    """이 공고 대화의 Copilot 질문 한 번을 쓴다. 한도를 넘으면 쓰지 않고 막는다. 커밋은 부르는 쪽이 한다."""
    if not limits_apply(user):
        return
    plan = effective_plan(user)
    if plan.copilot_questions is not None:
        used = copilot_questions_used(db, user, case_id)
        if used >= plan.copilot_questions:
            raise _required("COPILOT_QUESTION", plan, used, plan.copilot_questions)
    db.add(MembershipUsage(user_id=user.id, kind="COPILOT_QUESTION", subject_id=str(case_id), period=current_period()))
    db.flush()


def membership_state(db: Session, user: AppUser | None, case_id: UUID | str | None = None) -> dict:
    """화면에 줄 요금제·사용량. 한도를 적용하지 않는 계정은 limited=False 다.

    Copilot 질문은 공고 대화마다 세므로 `case_id` 를 준 때만 그 대화에서 쓴 횟수를 싣는다(없으면 None).
    """
    plans = [
        {"code": plan.code, "name": plan.name, "monthly_price": plan.monthly_price,
         "notice_checks": plan.notice_checks, "copilot_questions": plan.copilot_questions}
        for plan in PLANS.values()
    ]
    if not limits_apply(user):
        return {"limited": False, "plan": "UNLIMITED", "plan_name": "제한 없음", "period": current_period(), "expires_at": None,
                "limits": {"notice_checks": None, "copilot_questions": None},
                "used": {"notice_checks": 0, "copilot_questions": None}, "plans": plans,
                "demo_code_enabled": False}
    plan = effective_plan(user)
    return {
        "limited": True, "plan": plan.code, "plan_name": plan.name, "period": current_period(),
        "expires_at": user.membership_expires_at if plan.code != "FREE" else None,
        "limits": {"notice_checks": plan.notice_checks, "copilot_questions": plan.copilot_questions},
        "used": {"notice_checks": notice_checks_used(db, user),
                 "copilot_questions": copilot_questions_used(db, user, case_id) if case_id is not None else None},
        "plans": plans,
        "demo_code_enabled": bool(get_settings().membership_demo_code),
    }


def subscribe_with_code(db: Session, user: AppUser | None, code: str) -> dict:
    """멤버십 코드로 가입한다(시연용). 코드가 맞으면 가장 저렴한 유료 요금제를 한 달 적용한다."""
    if user is None:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "로그인 후 멤버십에 가입할 수 있습니다.")
    expected = get_settings().membership_demo_code
    if not expected:
        raise ApiError(503, "MEMBERSHIP_PAYMENT_UNAVAILABLE", "이 환경에서는 멤버십 가입을 지원하지 않습니다.")
    if code.strip() != expected:
        raise ApiError(400, "MEMBERSHIP_CODE_INVALID", "멤버십 코드가 맞지 않습니다.")
    now = datetime.now(timezone.utc)
    user.membership_plan = DEMO_CODE_PLAN
    user.membership_started_at = now
    user.membership_expires_at = now + timedelta(days=MEMBERSHIP_DAYS)
    user.updated_at = now
    db.commit()
    db.refresh(user)
    return membership_state(db, user)
