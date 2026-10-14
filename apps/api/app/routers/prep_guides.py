"""입찰 준비 지침서: 판정이 끝난 공고를 고르면 준비할 것과 순서를 정리해 준다."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import authorize_case_access, get_current_user
from ..auth_models import AppUser
from ..database import get_db
from ..errors import ApiError
from ..membership import consume_copilot_question
from ..services import prep_guide

router = APIRouter(prefix="/api/v1/prep-guides", tags=["prep-guides"])


class JudgedCaseRead(BaseModel):
    case_id: UUID
    bid_notice_no: str
    notice_title: str
    institution: str | None
    bid_closed_at: datetime | None
    expired: bool
    overall_status: str
    overall_label: str
    judged_at: datetime


class PrepGuideRequest(BaseModel):
    # 공고 문서 발췌와 회사 프로필이 외부 AI 로 나간다. Copilot 과 같은 동의를 받는다.
    allow_external_processing: bool = False


def json_caller() -> prep_guide.JsonCaller:
    try:
        return prep_guide.openai_json_caller()
    except RuntimeError as error:
        raise ApiError(503, "PREP_GUIDE_UNAVAILABLE", "지침서를 만드는 AI 를 쓸 수 없습니다.") from error


@router.get("/cases", response_model=list[JudgedCaseRead])
def list_judged_cases(db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    if user.company_id is None:
        return []
    return prep_guide.judged_cases(db, user.company_id)


@router.post("/cases/{case_id}")
def create_prep_guide(
    case_id: UUID,
    payload: PrepGuideRequest,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
    call: prep_guide.JsonCaller = Depends(json_caller),
) -> dict[str, Any]:
    case = authorize_case_access(db, user, case_id)
    if not payload.allow_external_processing:
        raise ApiError(422, "EXTERNAL_PROCESSING_CONSENT_REQUIRED", "공고 문서와 회사 프로필을 외부 AI 로 보내는 데 동의해야 지침서를 만들 수 있습니다.")
    if not prep_guide.has_judgment(db, case):
        raise ApiError(409, "PREP_GUIDE_JUDGMENT_REQUIRED", "참가자격 판정을 마친 공고만 지침서를 만들 수 있습니다.")
    # 지침서 한 번은 그 공고의 Copilot 질문 한 번으로 센다(모델을 두 번 부른다). 한도를 넘으면 여기서 막힌다.
    consume_copilot_question(db, user, case.id)
    try:
        guide = prep_guide.guide_for_case(db, case, call=call)
    except ApiError:
        raise
    except Exception as error:  # noqa: BLE001 - 모델 호출 실패는 쓴 횟수를 되돌리고 알린다
        db.rollback()
        raise ApiError(502, "PREP_GUIDE_FAILED", "지침서를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요.") from error
    db.commit()
    return {"case_id": str(case.id), **guide}
