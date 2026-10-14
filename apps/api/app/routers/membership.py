"""요금제 조회와 멤버십 코드 가입."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..auth import get_optional_current_user
from ..auth_models import AppUser
from ..database import get_db
from ..membership import GENERAL_SUBJECT, membership_state, subscribe_with_code

router = APIRouter(prefix="/api/v1/membership", tags=["membership"])


class PlanRead(BaseModel):
    code: Literal["FREE", "BASIC", "UNLIMITED"]
    name: str
    monthly_price: int
    notice_checks: int | None
    # 공고 하나의 질문 수 / 일반 도우미의 한 달 질문 수 / 둘을 합친 한 달 질문 수(있으면 이것만 적용된다).
    copilot_questions: int | None
    general_questions: int | None
    copilot_total: int | None


class ChatQuotaRead(BaseModel):
    """지금 대화에 적용되는 채팅 한도. scope: NOTICE(이 공고에서), GENERAL(일반 도우미 한 달), TOTAL(둘을 합쳐 한 달)."""
    scope: Literal["NOTICE", "GENERAL", "TOTAL"]
    limit: int | None
    used: int


class UsageRead(BaseModel):
    notice_checks: int | None
    copilot_questions: int | None


class MembershipRead(BaseModel):
    # False 면 이 계정에는 한도가 없다(시스템 관리자, 한도를 켜지 않은 환경).
    # used.copilot_questions 는 case_id 를 준 조회에서만 채워진다(공고 대화마다 센다).
    limited: bool
    plan: Literal["FREE", "BASIC", "UNLIMITED"]
    plan_name: str
    period: str
    expires_at: datetime | None
    limits: UsageRead
    used: UsageRead
    plans: list[PlanRead]
    # case_id 나 general 을 준 조회에서만 채워진다.
    chat: ChatQuotaRead | None = None
    demo_code_enabled: bool


class MembershipSubscribe(BaseModel):
    """가입 요청. 카드 정보를 받는 칸은 없다 — 화면의 결제 입력은 서버로 오지 않는다."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    plan: Literal["BASIC", "UNLIMITED"]
    membership_code: str = Field(min_length=1, max_length=64)


@router.get("", response_model=MembershipRead)
def read_membership(
    case_id: UUID | None = None,
    general: bool = False,
    db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user),
) -> MembershipRead:
    # case_id(공고 대화)나 general(일반 도우미)을 주면 그 대화에 적용되는 채팅 한도를 함께 준다.
    # 자기 계정이 쓴 것만 세므로 권한 검사는 따로 필요 없다.
    return MembershipRead.model_validate(membership_state(db, user, GENERAL_SUBJECT if general else case_id))


@router.post("/subscribe", response_model=MembershipRead)
def subscribe(
    payload: MembershipSubscribe,
    db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user),
) -> MembershipRead:
    # 고른 요금제와 상관없이 멤버십 코드는 가장 저렴한 유료 요금제를 연다(membership.DEMO_CODE_PLAN).
    return MembershipRead.model_validate(subscribe_with_code(db, user, payload.membership_code))
