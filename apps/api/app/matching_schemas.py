from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class NoticeMatchRead(BaseModel):
    notice_id: UUID
    case_id: UUID
    bid_notice_no: str
    title: str
    institution_name: str | None
    version_number: int
    is_current_version: bool
    analysis_run_id: UUID
    analysis_status: str
    overall_status: Literal["core_met", "core_unmet", "needs_review"]
    satisfied_count: int
    unknown_count: int
    unsatisfied_count: int
    requirement_count: int
    evidence_count: int
    analyzed_at: datetime
    judged_at: datetime


class NoticeMatchSearchResponse(BaseModel):
    company_id: UUID
    analyzed_notice_count: int
    returned_count: int
    offset: int = 0
    items: list[NoticeMatchRead] = Field(default_factory=list)
    note: str = "해당 회사가 실제 판정한 공고 이력입니다. 이전 차수의 결과도 보존하며, 현재 자격 충족을 의미하지 않습니다."
