"""Company-scoped persisted qualification judgment history.

Historical judgments are read as saved, even if the notice has a newer version
or its AI analysis cache has expired. Shared companies share their history.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session, joinedload, selectinload

from ..analysis_models import QualificationAnalysisRun
from ..judgment_models import QualificationJudgmentRun
from ..matching_schemas import NoticeMatchRead, NoticeMatchSearchResponse
from ..models import BidNotice, BidNoticeVersion, PreflightCase
from .judgment import _load_company



def _load_latest_valid_analysis_runs(
    db: Session,
    fingerprints: dict[UUID, str],
) -> dict[UUID, QualificationAnalysisRun]:
    """Return one newest run per version whose input still matches current documents.

    Ranking happens after the fingerprint filter, so a newer stale run does not hide
    an older still-valid run. Status is intentionally not filtered: if the newest
    valid run failed, callers must not silently fall back to an older success.
    """
    if not fingerprints:
        return {}

    ranked = (
        select(
            QualificationAnalysisRun.id.label("run_id"),
            func.row_number()
            .over(
                partition_by=QualificationAnalysisRun.notice_version_id,
                order_by=(
                    QualificationAnalysisRun.created_at.desc(),
                    QualificationAnalysisRun.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(
            tuple_(
                QualificationAnalysisRun.notice_version_id,
                QualificationAnalysisRun.input_fingerprint,
            ).in_(list(fingerprints.items()))
        )
        .subquery()
    )
    runs = db.scalars(
        select(QualificationAnalysisRun)
        .join(ranked, ranked.c.run_id == QualificationAnalysisRun.id)
        .where(ranked.c.rank == 1)
        .options(
            joinedload(QualificationAnalysisRun.notice_version),
            selectinload(QualificationAnalysisRun.requirements),
            selectinload(QualificationAnalysisRun.evidence),
        )
    ).all()
    return {run.notice_version_id: run for run in runs}


def match_cached_notices(
    db: Session,
    *,
    company_id: UUID,
    reference_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> NoticeMatchSearchResponse:
    """Company-wide *stored judgment history*, never a global AI-cache search.

    Multiple accounts of the same company share this history. Historical notice
    versions and stale analysis fingerprints stay visible as historical results.
    Only the latest judgment for each (notice, analyzed version) is shown.
    """
    _load_company(db, company_id)
    # Kept in the HTTP contract for compatibility; historical verdicts must not
    # be silently recomputed with a different reference date or live profile.
    _ = reference_date

    ranked = (
        select(
            QualificationJudgmentRun.id.label("run_id"),
            QualificationJudgmentRun.created_at.label("judged_at"),
            func.row_number().over(
                partition_by=(PreflightCase.notice_id, QualificationJudgmentRun.notice_version_id),
                order_by=(QualificationJudgmentRun.created_at.desc(), QualificationJudgmentRun.id.desc()),
            ).label("rank"),
        )
        .join(PreflightCase, QualificationJudgmentRun.preflight_case_id == PreflightCase.id)
        .join(BidNoticeVersion, QualificationJudgmentRun.notice_version_id == BidNoticeVersion.id)
        .where(
            QualificationJudgmentRun.company_id == company_id,
            PreflightCase.company_id == company_id,
            PreflightCase.notice_id == BidNoticeVersion.notice_id,
        )
        .subquery()
    )
    total = db.scalar(select(func.count()).select_from(ranked).where(ranked.c.rank == 1)) or 0
    if total == 0:
        return NoticeMatchSearchResponse(
            company_id=company_id, analyzed_notice_count=0,
            returned_count=0, offset=offset, items=[],
        )

    run_ids = db.scalars(
        select(ranked.c.run_id)
        .where(ranked.c.rank == 1)
        .order_by(ranked.c.judged_at.desc(), ranked.c.run_id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    if not run_ids:
        return NoticeMatchSearchResponse(
            company_id=company_id, analyzed_notice_count=total,
            returned_count=0, offset=offset, items=[],
        )

    records = db.execute(
        select(QualificationJudgmentRun, BidNotice, BidNoticeVersion)
        .join(PreflightCase, QualificationJudgmentRun.preflight_case_id == PreflightCase.id)
        .join(BidNoticeVersion, QualificationJudgmentRun.notice_version_id == BidNoticeVersion.id)
        .join(BidNotice, PreflightCase.notice_id == BidNotice.id)
        .where(
            QualificationJudgmentRun.id.in_(run_ids),
            QualificationJudgmentRun.company_id == company_id,
            PreflightCase.company_id == company_id,
            BidNoticeVersion.notice_id == BidNotice.id,
        )
        .options(
            joinedload(QualificationJudgmentRun.analysis_run).selectinload(QualificationAnalysisRun.requirements),
            joinedload(QualificationJudgmentRun.analysis_run).selectinload(QualificationAnalysisRun.evidence),
            selectinload(QualificationJudgmentRun.judgments),
        )
    ).all()

    stored_status_to_display = {"eligible": "core_met", "ineligible": "core_unmet", "insufficient_data": "needs_review", "needs_review": "needs_review", "core_met": "core_met", "core_unmet": "core_unmet"}
    items = []
    for judgment, notice, version in records:
        analysis = judgment.analysis_run
        statuses = [row.status for row in judgment.judgments]
        items.append(NoticeMatchRead(
            notice_id=notice.id,
            case_id=judgment.preflight_case_id,
            bid_notice_no=notice.bid_notice_no,
            title=notice.title,
            institution_name=notice.announcing_institution_name,
            version_number=version.version_number,
            is_current_version=version.is_current,
            analysis_run_id=judgment.analysis_run_id,
            analysis_status=analysis.status,
            overall_status=stored_status_to_display[judgment.overall_status],
            satisfied_count=statuses.count("SATISFIED"),
            unknown_count=statuses.count("UNKNOWN"),
            unsatisfied_count=statuses.count("UNSATISFIED"),
            requirement_count=len(analysis.requirements),
            evidence_count=len(analysis.evidence),
            analyzed_at=analysis.created_at,
            judged_at=judgment.created_at,
        ))
    items.sort(key=lambda item: (item.judged_at, str(item.analysis_run_id)), reverse=True)
    return NoticeMatchSearchResponse(
        company_id=company_id,
        analyzed_notice_count=total,
        returned_count=len(items),
        offset=offset,
        items=items,
    )
