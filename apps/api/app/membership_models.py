"""요금제 사용량 기록(membership.py)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class MembershipUsage(Base):
    """계정이 한 달 동안 쓴 것 한 줄.

    NOTICE_CHECK 는 (계정, 달, 공고)마다 한 줄뿐이다 — 같은 공고를 다시 검토해도 늘지 않는다.
    COPILOT_QUESTION 은 질문마다 한 줄이다(subject_id 는 검토 건).
    """

    __tablename__ = "membership_usage"
    __table_args__ = (
        CheckConstraint("kind IN ('NOTICE_CHECK', 'COPILOT_QUESTION')", name="ck_membership_usage_kind"),
        Index("ix_membership_usage_user_period", "user_id", "period", "kind"),
        Index(
            "uq_membership_usage_notice_check", "user_id", "period", "subject_id",
            unique=True, postgresql_where=text("kind = 'NOTICE_CHECK'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), ForeignKey("app_users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[str] = mapped_column(Text)
    # 한국 시간의 달력 달, "2026-10".
    period: Mapped[str] = mapped_column(String(7))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
