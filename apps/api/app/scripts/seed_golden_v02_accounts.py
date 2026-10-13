"""Seed Golden Set v0.2 companies and login accounts for product testing.

The Golden bundle remains the source of truth. This script only adapts its
company profiles to the normalized backend tables. It is intentionally blocked
in production and does not contact G2B or OpenAI.

여럿이 쓰는 DB(AWS 개발 환경)에 넣을 때는 `--shared-db` 를 준다(2026-10-13). 로컬 시험 DB 와 달리 다른 사람의
데이터가 함께 있으므로, 골든 계정·회사·검토 건 밖의 것은 바꾸지 않는다:
  - 이미 수집된 공고의 현재 차수를 바꾸지 않는다. 골든 차수는 현재가 아닌 차수로 덧붙인다.
  - 없는 공고를 새로 만들 때는 게시일을 옛날로 두어 공고 목록의 맨 뒤에 오게 한다.
  - 업종 코드 목록에 없는 코드는 비활성으로 넣어, 업종 검색이나 다른 회사의 프로필에 나타나지 않게 한다.
  - 기본 비밀번호를 쓰지 못하고(12자 이상을 따로 줘야 한다), 비밀번호를 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..analysis_models import (
    QualificationAnalysisRun,
    QualificationEvidenceRecord,
    QualificationRequirementRecord,
)
from ..auth import hash_password
from ..auth_models import AppUser, AuthSession
from ..config import get_settings
from ..database import SessionLocal
from ..judgment_models import CompanyQualificationProfileCompleteness
from ..models import (
    BidNotice,
    BidNoticeVersion,
    Company,
    CompanyCertification,
    CompanyIndustry,
    CompanyPerformance,
    CompanyPerformanceField,
    CompanyStaff,
    CompanyStaffRole,
    IndustryCode,
    NoticeDocument,
    PreflightCase,
)
from ..qualification.analysis import qualification_analysis_version_fingerprint


GOLDEN_CONTRACT_VERSION = "golden-v0.2-draft"
DEFAULT_PASSWORD = "golden-test"
PASSWORD_ENV = "GOLDEN_SEED_PASSWORD"
SHARED_DB_MIN_PASSWORD = 12
# 여럿이 쓰는 DB 에 새로 만드는 골든 공고의 게시일. 마감일이 없고 게시된 지 40일이 넘은 공고는 목록의 맨 뒤 묶음에 온다.
SHARED_DB_POSTED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
CASE_PATTERN = re.compile(r"J\d{2}")


def golden_username(case_id: str) -> str:
    if CASE_PATTERN.fullmatch(case_id) is None:
        raise ValueError(f"unsupported Golden case id: {case_id}")
    return f"golden-{case_id.casefold()}"


def golden_business_number(case_id: str) -> str:
    return f"9902{int(case_id[1:]):06d}"


EXCERPT_NAME_PREFIX = "[골든셋 근거 발췌] "
EXCERPT_EXTRACTOR = "GOLDEN_EVIDENCE_EXCERPT"


def load_golden_documents(bundle_dir: Path) -> dict[str, dict[str, Any]]:
    """근거가 나온 원래 문서의 이름·주소(sources/sources24.json). 없으면 빈 것 — 문서 이름만 덜 친절해진다."""
    path = bundle_dir / "sources" / "sources24.json"
    if not path.is_file():
        return {}
    return {item["document_id"]: item for item in json.loads(path.read_text(encoding="utf-8"))}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ensure_evidence_documents(
    db: Session,
    *,
    version: BidNoticeVersion,
    items: list[dict[str, Any]],
    documents: dict[str, dict[str, Any]],
) -> dict[str, tuple[str | None, str | None]]:
    """골든 근거가 가리키는 문서를 이 차수에 붙인다. 돌려주는 것은 문서 id → (파일 해시, 추출문 해시).

    판정은 요건마다 "인용한 문장이 저장된 공고문에 있는가"를 먼저 확인하고, 없으면 회사 프로필과 비교하지 않는다
    (qualification/impact_adapter.current_grounded_requirement_keys). 골든셋에는 원본 첨부가 없고 발췌한 근거 문장만
    있으므로, 그 문장들을 모은 「근거 발췌」 문서를 만든다. 원본 파일이 아니라는 것을 이름·추출기 이름·내려받기 상태로 남긴다.
    그 id 의 문서가 이미 있으면(진짜로 수집된 문서) 건드리지 않고 그 해시를 쓴다.
    """
    hashes: dict[str, tuple[str | None, str | None]] = {}
    by_document: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_document.setdefault(item["document_id"], []).append(item)
    now = datetime.now(timezone.utc)
    for order, (document_id, quotes) in enumerate(sorted(by_document.items()), start=1):
        existing = db.get(NoticeDocument, UUID(document_id))
        if existing is not None and existing.text_extractor != EXCERPT_EXTRACTOR:
            hashes[document_id] = (existing.file_sha256, existing.extracted_text_sha256)
            continue
        meta = documents.get(document_id, {})
        blocks = [
            {"block_index": index, "location": item.get("location") or "", "text": item["quote"]}
            for index, item in enumerate(sorted(quotes, key=lambda row: row["evidence_id"]))
        ]
        text = "\n\n".join(block["text"] for block in blocks)
        digest = _sha256(text)
        document = existing or NoticeDocument(id=UUID(document_id), notice_version_id=version.id)
        document.notice_version_id = version.id
        document.document_order = 900 + order
        document.name = EXCERPT_NAME_PREFIX + str(meta.get("document_name") or f"공고문 {document_id[:8]}")
        document.url = str(meta.get("source_url") or quotes[0].get("source_url") or "")
        document.source_field = f"golden-v0.2:{document_id}"
        # 원본 파일은 없다. 내려받기 실패로 두어 원본 열기·재추출 대상에서 빠지게 한다.
        document.download_status = "FAILED"
        document.download_error = "골든셋 근거 발췌문입니다. 원본 첨부 파일은 저장돼 있지 않습니다."
        document.storage_key = None
        document.content_type = "text/plain"
        document.file_size_bytes = len(text.encode("utf-8"))
        document.file_sha256 = digest
        document.extraction_status = "EXTRACTED"
        document.extracted_text = text
        document.extracted_blocks = blocks
        document.extracted_char_count = len(text)
        document.extracted_text_sha256 = digest
        document.text_extractor = EXCERPT_EXTRACTOR
        document.extracted_at = now
        db.add(document)
        hashes[document_id] = (digest, digest)
    db.flush()
    return hashes


def synthetic_industry_code(case_id: str, index: int) -> str:
    return f"GOLDEN-{case_id}-{index:02d}"


def load_golden_bundle(bundle_dir: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    bundle_path = bundle_dir / "fixture_bundle.json"
    evidence_path = bundle_dir / "sources" / "evidence_all.json"
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Golden bundle not found: {bundle_path}")
    if not evidence_path.is_file():
        raise FileNotFoundError(f"Golden evidence not found: {evidence_path}")

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    cases = [item for item in bundle.get("cases", []) if CASE_PATTERN.fullmatch(item.get("case_id", ""))]
    if not cases:
        raise ValueError("Golden bundle has no J01~J32 cases")
    case_ids = [item["case_id"] for item in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Golden bundle contains duplicate case ids")

    evidence_rows = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item for item in evidence_rows}
    return sorted(cases, key=lambda item: item["case_id"]), evidence


def _as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _replace_company_profile(db: Session, case: dict[str, Any], *, shared_db: bool = False) -> Company:
    case_id = case["case_id"]
    profile = case["profile"]
    company_id = UUID(profile["company_id"])
    company = db.get(Company, company_id)
    if company is None:
        company = Company(id=company_id, name=case["profile_name"], company_size=profile["company_size"])
        db.add(company)
    company.name = case["profile_name"]
    company.business_registration_number = golden_business_number(case_id)
    company.region_code = profile.get("region_code")
    company.region_name = profile.get("region_name")
    company.company_size = profile["company_size"]
    db.flush()

    performance_ids = select(CompanyPerformance.id).where(CompanyPerformance.company_id == company_id)
    db.execute(delete(CompanyPerformanceField).where(CompanyPerformanceField.performance_id.in_(performance_ids)))
    db.execute(delete(CompanyPerformance).where(CompanyPerformance.company_id == company_id))
    db.execute(delete(CompanyCertification).where(CompanyCertification.company_id == company_id))
    db.execute(delete(CompanyStaffRole).where(CompanyStaffRole.company_id == company_id))
    db.execute(delete(CompanyStaff).where(CompanyStaff.company_id == company_id))
    db.execute(delete(CompanyIndustry).where(CompanyIndustry.company_id == company_id))

    now = datetime.now(timezone.utc)
    for index, item in enumerate(profile.get("industries", []), start=1):
        industry_code = str(item.get("code") or synthetic_industry_code(case_id, index))
        industry = db.get(IndustryCode, industry_code)
        if industry is None:
            industry = IndustryCode(
                code=industry_code,
                name=str(item.get("name") or industry_code),
                # 여럿이 쓰는 DB 에서는 비활성으로 넣는다 — 업종 검색에 나오지 않고 다른 회사가 고를 수 없다.
                active=not shared_db,
                changed_at=None,
                source_window="golden-v0.2",
                collected_at=now,
                raw_json={"source": "golden-v0.2", "case_id": case_id},
            )
            db.add(industry)
        db.add(
            CompanyIndustry(
                company_id=company_id,
                industry_code=industry_code,
                verified=bool(item.get("verified", False)),
            )
        )

    staff = profile.get("staff")
    if staff is not None:
        db.add(
            CompanyStaff(
                company_id=company_id,
                total_count=int(staff.get("total_count", 0)),
                verified=bool(staff.get("verified", False)),
            )
        )
        for role in staff.get("roles", []):
            db.add(
                CompanyStaffRole(
                    company_id=company_id,
                    role_name=role["role_name"],
                    headcount=int(role["headcount"]),
                    career_years=(
                        Decimal(str(role["career_years"]))
                        if role.get("career_years") is not None
                        else None
                    ),
                    verified=bool(role.get("verified", False)),
                )
            )

    for item in profile.get("performances", []):
        performance = CompanyPerformance(
            id=uuid5(NAMESPACE_URL, f"bidcheck:golden-v0.2:{case_id}:performance:{item['ref']}"),
            company_id=company_id,
            name=item["name"],
            client_name=item.get("client_name"),
            client_institution_code=item.get("client_institution_code"),
            amount=Decimal(str(item["amount"])),
            started_at=_as_date(item.get("started_at")),
            completed_at=_as_date(item.get("completed_at")),
            completed_year=item.get("completed_year"),
            description=None,
            verified=bool(item.get("verified", False)),
        )
        db.add(performance)
        for field in item.get("fields", []):
            db.add(CompanyPerformanceField(performance_id=performance.id, field_name=field))

    for item in profile.get("certifications", []):
        db.add(
            CompanyCertification(
                id=uuid5(NAMESPACE_URL, f"bidcheck:golden-v0.2:{case_id}:certification:{item['ref']}"),
                company_id=company_id,
                name=item["name"],
                certification_code=item.get("certification_code"),
                certificate_number=item.get("ref"),
                issuer_name=item.get("issuer_name"),
                issued_at=_as_date(item.get("issued_at")),
                expires_at=_as_date(item.get("expires_at")),
                verified=bool(item.get("verified", False)),
            )
        )

    completeness = profile.get("completeness", {})
    record = db.get(CompanyQualificationProfileCompleteness, company_id)
    if record is None:
        record = CompanyQualificationProfileCompleteness(company_id=company_id)
        db.add(record)
    for source, target in (
        ("region", "region_complete"),
        ("company_size", "company_size_complete"),
        ("industries", "industries_complete"),
        ("staff_total", "staff_total_complete"),
        ("staff_roles", "staff_roles_complete"),
        ("performances", "performances_complete"),
        ("certifications", "certifications_complete"),
    ):
        setattr(record, target, bool(completeness.get(source, False)))
    return company


def _upsert_login(db: Session, *, company: Company, case_id: str, password: str) -> AppUser:
    username = golden_username(case_id)
    user = db.scalar(select(AppUser).where(AppUser.username == username))
    if user is None:
        user = AppUser(username=username, password_hash="", role="ADMIN", active=True)
        db.add(user)
        db.flush()
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    user.password_hash = hash_password(password)
    user.company_id = company.id
    user.role = "ADMIN"
    user.active = True
    user.failed_login_attempts = 0
    user.locked_until = None
    return user


def _ensure_notice_version(
    db: Session,
    case: dict[str, Any],
    *,
    create_missing_notices: bool,
    shared_db: bool = False,
) -> BidNoticeVersion | None:
    version_id = UUID(case["notice_version_id"])
    version = db.get(BidNoticeVersion, version_id)
    if version is not None or not create_missing_notices:
        return version

    notice = db.scalar(select(BidNotice).where(BidNotice.bid_notice_no == case["notice_no"]))
    now = datetime.now(timezone.utc)
    if notice is None:
        notice = BidNotice(
            id=uuid5(NAMESPACE_URL, f"bidcheck:golden-v0.2:notice:{case['notice_no']}"),
            bid_notice_no=case["notice_no"],
            title=case["title"],
            business_type="SERVICE",
            notice_kind="골든셋 테스트",
            announcing_institution_code=None,
            announcing_institution_name="골든셋 테스트",
            demanding_institution_code=None,
            demanding_institution_name=None,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(notice)
        db.flush()
    max_version = db.scalar(
        select(func.max(BidNoticeVersion.version_number)).where(BidNoticeVersion.notice_id == notice.id)
    ) or 0
    # 로컬 시험 DB 에서는 골든 차수를 현재 차수로 바꿔 놓는다. 여럿이 쓰는 DB 에서는 이미 수집된 공고의 현재 차수를
    # 건드리지 않는다 — 차수가 하나도 없던(방금 만든) 공고만 골든 차수가 현재가 된다.
    if not shared_db:
        db.execute(
            BidNoticeVersion.__table__.update()
            .where(BidNoticeVersion.notice_id == notice.id)
            .values(is_current=False)
        )
    bid_notice_order = case["source_order"]
    if shared_db and db.scalar(
        select(BidNoticeVersion.id).where(
            BidNoticeVersion.notice_id == notice.id, BidNoticeVersion.bid_notice_order == bid_notice_order,
        )
    ) is not None:
        # 같은 공고의 같은 차수가 이미 수집돼 있다. 그 차수(와 그 분석)는 다른 사람이 쓰는 진짜 자료라 덮어쓰지 않고,
        # 골든 차수를 다른 이름으로 따로 둔다((공고, 차수) 는 하나뿐이어야 한다).
        bid_notice_order = f"{bid_notice_order}-golden"
    version = BidNoticeVersion(
        id=version_id,
        notice_id=notice.id,
        version_number=max_version + 1,
        bid_notice_order=bid_notice_order,
        is_current=not shared_db or max_version == 0,
        notice_kind="골든셋 테스트",
        registration_type="테스트",
        is_reannouncement=False,
        posted_at=SHARED_DB_POSTED_AT if shared_db else now,
        changed_at=None,
        bid_started_at=None,
        bid_closed_at=None,
        opened_at=None,
        allocated_budget=None,
        estimated_price=None,
        contract_method=None,
        change_reason=None,
        detail_url=None,
        source_endpoint="golden-v0.2",
        payload_hash=hashlib.sha256(f"golden-v0.2:{version_id}".encode()).hexdigest(),
        raw_json={"source": "golden-v0.2", "draft": True},
        collected_at=now,
    )
    db.add(version)
    db.flush()
    return version


def _replace_analysis(
    db: Session,
    *,
    case: dict[str, Any],
    version: BidNoticeVersion,
    evidence: dict[str, dict[str, Any]],
    documents: dict[str, dict[str, Any]] | None = None,
) -> QualificationAnalysisRun:
    existing = db.scalar(
        select(QualificationAnalysisRun).where(
            QualificationAnalysisRun.notice_version_id == version.id,
            QualificationAnalysisRun.contract_version == GOLDEN_CONTRACT_VERSION,
        )
    )
    if existing is not None:
        db.delete(existing)
        db.flush()

    run = QualificationAnalysisRun(
        notice_version_id=version.id,
        contract_version=GOLDEN_CONTRACT_VERSION,
        analysis_kind="QUALIFICATION_REQUIREMENTS",
        status=case.get("analysis_status", "PARTIAL"),
        target_chunk_ids=[],
        diagnostics=[{"code": "GOLDEN_DRAFT", "message": "독립 검토자 승인 전 골든셋 초안"}],
        dropped_requirements=[],
        input_fingerprint=qualification_analysis_version_fingerprint(version),
    )
    db.add(run)
    db.flush()

    used_evidence: set[str] = set()
    for canonical in case.get("canonical_inputs", []):
        requirement = canonical["requirement"]
        db.add(
            QualificationRequirementRecord(
                analysis_run_id=run.id,
                requirement_key=requirement["requirement_key"],
                requirement_group_key=requirement.get("requirement_group_key"),
                group_operator=requirement.get("group_operator"),
                type=requirement["type"],
                operator=requirement.get("operator"),
                value_json=requirement.get("value"),
                unit=requirement.get("unit"),
                period_months=(
                    Decimal(str(requirement["period_months"]))
                    if requirement.get("period_months") is not None
                    else None
                ),
                scope=requirement.get("scope", {}),
                requirement_role=requirement.get("requirement_role", "mandatory"),
                condition_complexity=requirement.get("condition_complexity", "simple"),
                required=bool(requirement.get("required", True)),
                raw=requirement["raw"],
                confidence=(
                    Decimal(str(requirement["confidence"]))
                    if requirement.get("confidence") is not None
                    else None
                ),
                evidence_keys=requirement.get("evidence_keys", []),
            )
        )
        used_evidence.update(requirement.get("evidence_keys", []))

    missing = sorted(key for key in used_evidence if key not in evidence)
    if missing:
        raise ValueError(f"missing evidence {missing[0]} for {case['case_id']}")
    # 근거가 가리키는 문서를 차수에 붙이고, 근거에 그 문서의 해시를 적는다 — 둘이 맞아야 판정이 근거를 인정한다.
    hashes = _ensure_evidence_documents(
        db, version=version, items=[evidence[key] for key in sorted(used_evidence)], documents=documents or {},
    )
    # 지문은 차수의 문서까지 넣어 만든다. 문서를 붙인 뒤에 다시 계산하지 않으면 "문서가 바뀌어 다시 분석해야 한다" 로 읽힌다.
    db.expire(version, ["documents"])
    run.input_fingerprint = qualification_analysis_version_fingerprint(version)
    for evidence_key in sorted(used_evidence):
        item = evidence[evidence_key]
        source_sha256, text_sha256 = hashes.get(item["document_id"], (None, None))
        db.add(
            QualificationEvidenceRecord(
                analysis_run_id=run.id,
                evidence_key=evidence_key,
                source_type="NOTICE_DOCUMENT",
                document_id=item["document_id"],
                notice_version_id=str(version.id),
                case_id=None,
                chunk_id=evidence_key,
                location={"display": item.get("location")},
                quote=item["quote"],
                source_sha256=source_sha256,
                extracted_text_sha256=text_sha256,
            )
        )
    return run


def _preserved_baseline_id(
    baseline: BidNoticeVersion | None,
    *,
    current: BidNoticeVersion,
) -> UUID | None:
    """Keep only a real earlier version of the same notice as the comparison baseline."""

    if baseline is None:
        return None
    if baseline.notice_id != current.notice_id:
        return None
    if baseline.version_number >= current.version_number:
        return None
    return baseline.id


def seed_golden_v02_accounts(
    db: Session,
    *,
    bundle_dir: Path,
    password: str = DEFAULT_PASSWORD,
    include_analysis: bool = False,
    create_missing_notices: bool = False,
    shared_db: bool = False,
) -> dict[str, Any]:
    if get_settings().app_environment == "production":
        raise RuntimeError("Golden Set accounts cannot be seeded in production")
    if len(password) < 8:
        raise ValueError("Golden test password must be at least 8 characters")
    if shared_db and (password == DEFAULT_PASSWORD or len(password) < SHARED_DB_MIN_PASSWORD):
        raise ValueError(
            f"A shared database needs its own Golden password of at least {SHARED_DB_MIN_PASSWORD} characters"
        )
    if create_missing_notices and not include_analysis:
        raise ValueError("--create-missing-notices requires --include-analysis")

    cases, evidence = load_golden_bundle(bundle_dir)
    documents = load_golden_documents(bundle_dir)
    versions: dict[UUID, tuple[BidNoticeVersion, QualificationAnalysisRun | None]] = {}
    seeded_cases: list[dict[str, str]] = []
    missing_versions: list[dict[str, str]] = []

    for case in cases:
        company = _replace_company_profile(db, case, shared_db=shared_db)
        user = _upsert_login(db, company=company, case_id=case["case_id"], password=password)
        version = _ensure_notice_version(
            db,
            case,
            create_missing_notices=create_missing_notices,
            shared_db=shared_db,
        )
        analysis = None
        if version is None:
            missing_versions.append(
                {"case_id": case["case_id"], "notice_version_id": case["notice_version_id"]}
            )
        else:
            if include_analysis:
                cached = versions.get(version.id)
                if cached is None:
                    analysis = _replace_analysis(db, case=case, version=version, evidence=evidence, documents=documents)
                    versions[version.id] = (version, analysis)
                else:
                    analysis = cached[1]
            title = f"Golden v0.2 {case['case_id']} · {case['focus']}"
            preflight_case = db.scalar(
                select(PreflightCase).where(
                    PreflightCase.company_id == company.id,
                    PreflightCase.title == title,
                )
            )
            if preflight_case is None:
                preflight_case = PreflightCase(
                    company_id=company.id,
                    notice_id=version.notice_id,
                    baseline_version_id=None,
                    current_version_id=version.id,
                    title=title,
                    status="READY",
                )
                db.add(preflight_case)
                db.flush()
            else:
                existing_baseline = (
                    db.get(BidNoticeVersion, preflight_case.baseline_version_id)
                    if preflight_case.baseline_version_id is not None
                    else None
                )
                preflight_case.notice_id = version.notice_id
                preflight_case.baseline_version_id = _preserved_baseline_id(
                    existing_baseline,
                    current=version,
                )
                preflight_case.current_version_id = version.id
                preflight_case.status = "READY"
            seeded_cases.append(
                {
                    "case_id": case["case_id"],
                    "username": user.username,
                    "company_id": str(company.id),
                    "preflight_case_id": str(preflight_case.id),
                    "analysis_run_id": str(analysis.id) if analysis is not None else "",
                }
            )
        if version is None:
            seeded_cases.append(
                {
                    "case_id": case["case_id"],
                    "username": user.username,
                    "company_id": str(company.id),
                    "preflight_case_id": "",
                    "analysis_run_id": "",
                }
            )

    db.commit()
    return {
        "account_count": len(cases),
        "case_count": sum(bool(item["preflight_case_id"]) for item in seeded_cases),
        "analysis_count": len(versions),
        "password": password,
        "accounts": seeded_cases,
        "missing_versions": missing_versions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="골든셋 v0.2 회사 프로필과 테스트 계정을 적재합니다.")
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument(
        "--password",
        default=os.environ.get(PASSWORD_ENV) or DEFAULT_PASSWORD,
        help=f"골든 계정의 비밀번호. 주지 않으면 환경 변수 {PASSWORD_ENV}, 그것도 없으면 로컬용 기본값을 씁니다.",
    )
    parser.add_argument(
        "--shared-db",
        action="store_true",
        help="여럿이 쓰는 DB(AWS 개발 환경)에 넣습니다. 수집된 공고의 현재 차수와 업종 코드 목록을 건드리지 않습니다.",
    )
    parser.add_argument(
        "--include-analysis",
        action="store_true",
        help="고정 Canonical Requirement와 검토 건도 함께 적재합니다.",
    )
    parser.add_argument(
        "--create-missing-notices",
        action="store_true",
        help="로컬 테스트 DB에 공고가 없을 때 최소 공고/버전을 생성합니다.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = seed_golden_v02_accounts(
            db,
            bundle_dir=args.bundle_dir.resolve(),
            password=args.password,
            include_analysis=args.include_analysis,
            create_missing_notices=args.create_missing_notices,
            shared_db=args.shared_db,
        )
        print("Golden Set v0.2 test accounts ready")
        print(f"accounts: {result['account_count']}")
        print(f"preflight cases: {result['case_count']}")
        print(f"analysis runs: {result['analysis_count']}")
        # 여럿이 쓰는 DB 에 넣을 때는 비밀번호가 배포 기록에 남지 않게 출력하지 않는다.
        print("login pattern: golden-j01 ~ golden-j32" + ("" if args.shared_db else f" / {result['password']}"))
        if result["missing_versions"]:
            print(f"missing notice versions: {len(result['missing_versions'])}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
