"""HTTP routes for profile completeness and deterministic qualification judgment."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import authorize_case_access, authorize_company_access, get_optional_current_user
from ...auth_models import AppUser
from ...database import get_db
from ...errors import ApiError
from ...membership import ensure_notice_check_allowed, record_notice_check
from ...judgment_schemas import QualificationJudgmentRunRead, QualificationJudgmentRunSummary, QualificationJudgmentTrigger, QualificationProfileCompletenessRead, QualificationProfileCompletenessUpdate
from ..judgment import QualificationJudgmentError, get_profile_completeness, judgment_run_response, list_qualification_judgment_runs, load_qualification_judgment_run, update_profile_completeness
from ..judgment_target import run_targeted_qualification_judgment


router = APIRouter(prefix="/api/v1", tags=["qualification judgment"])


def _as_api_error(error: QualificationJudgmentError) -> ApiError:
    return ApiError(error.status_code, error.code, error.message)


@router.get("/companies/{company_id}/qualification-profile-completeness", response_model=QualificationProfileCompletenessRead)
def read_profile_completeness(company_id: UUID, db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user)) -> QualificationProfileCompletenessRead:
    authorize_company_access(user, company_id)
    try:
        return get_profile_completeness(db, company_id)
    except QualificationJudgmentError as error:
        raise _as_api_error(error) from error


@router.patch("/companies/{company_id}/qualification-profile-completeness", response_model=QualificationProfileCompletenessRead)
def patch_profile_completeness(company_id: UUID, payload: QualificationProfileCompletenessUpdate, db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user)) -> QualificationProfileCompletenessRead:
    authorize_company_access(user, company_id, write=True)
    try:
        return update_profile_completeness(db, company_id, payload)
    except QualificationJudgmentError as error:
        raise _as_api_error(error) from error


@router.post("/preflight-cases/{case_id}/qualification-judgments", response_model=QualificationJudgmentRunRead)
def trigger_qualification_judgment(case_id: UUID, payload: QualificationJudgmentTrigger | None = None, db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user)) -> QualificationJudgmentRunRead:
    case = authorize_case_access(db, user, case_id)
    # 요금제 한도: 참가자격 확인은 공고 단위로 센다. 이번 달에 이미 확인한 공고를 다시 검토하는 것은 더 세지 않는다.
    ensure_notice_check_allowed(db, user, case.notice_id)
    payload = payload or QualificationJudgmentTrigger()
    try:
        run = run_targeted_qualification_judgment(
            db,
            case_id=case_id,
            analysis_run_id=payload.analysis_run_id,
            reference_date=payload.reference_date,
        )
        response = judgment_run_response(run)
        record_notice_check(db, user, case.notice_id)
        db.commit()
        return response
    except QualificationJudgmentError as error:
        raise _as_api_error(error) from error


@router.get("/preflight-cases/{case_id}/qualification-judgment-runs", response_model=list[QualificationJudgmentRunSummary])
def list_case_qualification_judgments(case_id: UUID, db: Session = Depends(get_db), user: AppUser | None = Depends(get_optional_current_user)) -> list[QualificationJudgmentRunSummary]:
    authorize_case_access(db, user, case_id)
    try:
        return list_qualification_judgment_runs(db, case_id=case_id)
    except QualificationJudgmentError as error:
        raise _as_api_error(error) from error


@router.get("/qualification-judgment-runs/{run_id}", response_model=QualificationJudgmentRunRead)
def read_qualification_judgment_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> QualificationJudgmentRunRead:
    try:
        run = load_qualification_judgment_run(db, run_id)
        authorize_case_access(db, user, run.preflight_case_id)
        return judgment_run_response(run)
    except QualificationJudgmentError as error:
        raise _as_api_error(error) from error
