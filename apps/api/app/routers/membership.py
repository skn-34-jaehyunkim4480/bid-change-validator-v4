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
from ..membership import membership_state, subscribe_with_code

router = APIRouter(prefix="/api/v1/membership", tags=["membership"])


class PlanRead(BaseModel):
    code: Literal["FREE", "BASIC", "UNLIMITED"]
    name: str
    monthly_price: int
    notice_checks: int | None
    copilot_questions: int | None


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
    demo_code_enabled: bool


class MembershipSubscribe(BaseModel):
    """가입 요청. 카드 정보를 받는 칸은 없다 — 화면의 결제 입력은 서버로 오지 않는다."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    plan: Literal["BASIC", "UNLIMITED"]
    membership_code: str = Field(min_length=1, max_length=64)


@router.get("", response_model=MembershipRead)
def read_membership(
    case_id: UUID | None = None,
    db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user),
) -> MembershipRead:
    # case_id 를 주면 그 공고 대화에서 쓴 Copilot 질문 수를 함께 준다. 자기 계정이 쓴 것만 세므로 권한 검사는 따로 필요 없다.
    return MembershipRead.model_validate(membership_state(db, user, case_id))


@router.post("/subscribe", response_model=MembershipRead)
def subscribe(
    payload: MembershipSubscribe,
    db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user),
) -> MembershipRead:
    # 고른 요금제와 상관없이 멤버십 코드는 가장 저렴한 유료 요금제를 연다(membership.DEMO_CODE_PLAN).
    return MembershipRead.model_validate(subscribe_with_code(db, user, payload.membership_code))
