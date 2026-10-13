"""요금제와 사용 한도(2026-10-13).

계정마다 쓸 수 있는 양을 요금제로 정한다.

    요금제     월 요금    참가자격 확인(한 달 공고 수)   AI Copilot 질문
    FREE          0원              3                    공고 하나에 6회, 일반 도우미 한 달 10회
    BASIC     5,999원             20                    한 달 50회(공고 대화와 일반 도우미를 합쳐서)
    UNLIMITED 15,999원          제한 없음             제한 없음

세는 것:
  - 참가자격 확인: 그 달에 판정을 실행한 **서로 다른 공고** 수. 같은 공고를 다시 검토하는 것은 더 세지 않는다.
    달은 한국 시간의 달력 달이다. 달이 바뀌면 다시 0 부터 센다.
  - Copilot 질문: AI 가 답한 질문 수(입력창 질문과 추천 질문). 근거 보기 같은 단추는 세지 않는다.
      무료   공고 대화 하나(검토 건)마다 6회 — 달이 바뀌어도, '새 대화' 를 눌러도 다시 세지 않는다.
             일반 도우미는 한 달 10회.
      베이직 공고 대화와 일반 도우미를 합쳐 한 달 50회. 공고마다 따로 두는 한도는 없다.

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
    copilot_questions: int | None    # 공고 대화 하나에서 물을 수 있는 횟수
    general_questions: int | None    # 일반 도우미에 한 달 동안 물을 수 있는 횟수
    copilot_total: int | None        # 공고 대화와 일반 도우미를 합쳐 한 달 동안 물을 수 있는 횟수(있으면 위 둘 대신 이것만 본다)


PLANS: dict[str, Plan] = {
    "FREE": Plan("FREE", "무료", 0, 3, 6, 10, None),
    "BASIC": Plan("BASIC", "베이직", 5_999, 20, None, None, 50),
    "UNLIMITED": Plan("UNLIMITED", "무제한", 15_999, None, None, None, None),
}
# 일반 도우미의 질문은 공고 대화와 같은 종류(COPILOT_QUESTION)로 적고 subject_id 만 이 값으로 둔다.
GENERAL_SUBJECT = "general"
ChatScope = Literal["NOTICE", "GENERAL", "TOTAL"]
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


def chat_quota(db: Session, user: AppUser, plan: Plan, subject: UUID | str) -> tuple[ChatScope, int | None, int]:
    """이 대화(공고 검토 건 또는 일반 도우미)에 적용되는 채팅 한도: (어디까지 합쳐 세는가, 한도, 쓴 횟수)."""
    mine = (MembershipUsage.user_id == user.id, MembershipUsage.kind == "COPILOT_QUESTION")
    if plan.copilot_total is not None:
        used = db.scalar(select(func.count(MembershipUsage.id)).where(*mine, MembershipUsage.period == current_period())) or 0
        return "TOTAL", plan.copilot_total, used
    if str(subject) == GENERAL_SUBJECT:
        used = db.scalar(select(func.count(MembershipUsage.id)).where(
            *mine, MembershipUsage.subject_id == GENERAL_SUBJECT, MembershipUsage.period == current_period())) or 0
        return "GENERAL", plan.general_questions, used
    return "NOTICE", plan.copilot_questions, copilot_questions_used(db, user, subject)


_CHAT_LIMIT_TEXT = {
    "NOTICE": "공고 하나에서 AI Copilot 에 물을 수 있는 질문은 {limit}회",
    "GENERAL": "이번 달 일반 도우미에 물을 수 있는 질문은 {limit}회",
    "TOTAL": "이번 달 AI Copilot 에 물을 수 있는 질문은 공고 대화와 일반 도우미를 합쳐 {limit}회",
}


def _required(kind: UsageKind, plan: Plan, used: int, limit: int, scope: ChatScope | None = None) -> ApiError:
    text = (f"이번 달 참가자격을 확인할 수 있는 공고는 {limit}건" if kind == "NOTICE_CHECK"
            else _CHAT_LIMIT_TEXT[scope or "NOTICE"].format(limit=limit))
    more = "멤버십에 가입하면 더 쓸 수 있습니다." if plan.code == "FREE" else "다음 달에 다시 쓸 수 있습니다."
    details = {"kind": kind, "plan": plan.code, "used": used, "limit": limit}
    if scope is not None:
        details["scope"] = scope
    return ApiError(402, "MEMBERSHIP_REQUIRED", f"{plan.name} 요금제에서 {text}까지입니다. {more}", details)


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
    """Copilot 질문 한 번을 쓴다. case_id 는 공고 검토 건이거나 일반 도우미(GENERAL_SUBJECT)다.

    한도를 넘으면 쓰지 않고 막는다. 커밋은 부르는 쪽이 한다.
    """
    if not limits_apply(user):
        return
    plan = effective_plan(user)
    scope, limit, used = chat_quota(db, user, plan, case_id)
    if limit is not None and used >= limit:
        raise _required("COPILOT_QUESTION", plan, used, limit, scope)
    db.add(MembershipUsage(user_id=user.id, kind="COPILOT_QUESTION", subject_id=str(case_id), period=current_period()))
    db.flush()


def consume_general_question(db: Session, user: AppUser | None) -> None:
    """일반 도우미의 질문 한 번을 쓴다."""
    consume_copilot_question(db, user, GENERAL_SUBJECT)


def membership_state(db: Session, user: AppUser | None, case_id: UUID | str | None = None) -> dict:
    """화면에 줄 요금제·사용량. 한도를 적용하지 않는 계정은 limited=False 다.

    `case_id` 에 공고 검토 건이나 일반 도우미(GENERAL_SUBJECT)를 주면 그 대화에 적용되는 채팅 한도를 `chat` 에 싣는다.
    """
    plans = [
        {"code": plan.code, "name": plan.name, "monthly_price": plan.monthly_price,
         "notice_checks": plan.notice_checks, "copilot_questions": plan.copilot_questions,
         "general_questions": plan.general_questions, "copilot_total": plan.copilot_total}
        for plan in PLANS.values()
    ]
    if not limits_apply(user):
        return {"limited": False, "plan": "UNLIMITED", "plan_name": "제한 없음", "period": current_period(), "expires_at": None,
                "limits": {"notice_checks": None, "copilot_questions": None},
                "used": {"notice_checks": 0, "copilot_questions": None}, "plans": plans, "chat": None,
                "demo_code_enabled": False}
    plan = effective_plan(user)
    chat = None
    if case_id is not None:
        scope, limit, used = chat_quota(db, user, plan, case_id)
        chat = {"scope": scope, "limit": limit, "used": used}
    return {
        "limited": True, "plan": plan.code, "plan_name": plan.name, "period": current_period(),
        "expires_at": user.membership_expires_at if plan.code != "FREE" else None,
        "limits": {"notice_checks": plan.notice_checks, "copilot_questions": plan.copilot_questions},
        "used": {"notice_checks": notice_checks_used(db, user),
                 "copilot_questions": (copilot_questions_used(db, user, case_id)
                                       if case_id is not None and str(case_id) != GENERAL_SUBJECT else None)},
        "plans": plans, "chat": chat,
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
