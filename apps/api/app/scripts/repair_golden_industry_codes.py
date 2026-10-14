"""Guarded, reversible-in-transaction AWS Golden industry-code repair.

Default is READ-ONLY: python -m app.scripts.repair_golden_industry_codes
Writes require an explicit --apply; do not run before the fix is deployed.
Never deletes masters or rewrites historical judgments. Only verified Golden
J22/J24 code links and test-master visibility are changed.
"""
from __future__ import annotations

import argparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Company, CompanyIndustry, IndustryCode

_CANONICAL = {
    "J22": (UUID("cf0191a6-24c1-5cee-945a-9d8caa151040"), "GOLDEN-J22-01", "1262", "국내외여행업"),
    "J24": (UUID("c360c421-f24a-5785-8119-612bc6e57a81"), "GOLDEN-J24-01", "4966", "건설엔지니어링업(종합)"),
}
_EXPECTED_SYNTHETIC = {
    "GOLDEN-J09-01", "GOLDEN-J09-02", "GOLDEN-J09-03",
    "GOLDEN-J10-01", "GOLDEN-J10-02",
    "GOLDEN-J11-01", "GOLDEN-J11-02", "GOLDEN-J11-03",
    "GOLDEN-J12-01", "GOLDEN-J12-02", "GOLDEN-J12-03",
    "GOLDEN-J19-01", "GOLDEN-J22-01", "GOLDEN-J23-01",
    "GOLDEN-J24-01", "GOLDEN-J26-01",
}


def inspect_and_repair(db: Session, *, apply: bool = False) -> dict[str, object]:
    # Prevent modifying any unexpected test codes, companies or real masters.
    fake = db.scalars(
        select(IndustryCode).where(IndustryCode.code.like("GOLDEN-%")).order_by(IndustryCode.code)
        .with_for_update() if apply else
        select(IndustryCode).where(IndustryCode.code.like("GOLDEN-%")).order_by(IndustryCode.code)
    ).all()
    # New shared seeds create 14 synthetic codes; old DBs have all 16.
    found = {x.code for x in fake}
    required = _EXPECTED_SYNTHETIC - {"GOLDEN-J22-01", "GOLDEN-J24-01"}
    if not found.issubset(_EXPECTED_SYNTHETIC) or not required.issubset(found):
        raise RuntimeError("Golden master set differs from verified 14/16; aborting")
    for industry in fake:
        if (industry.source_window != "golden-v0.2"
                or (industry.raw_json or {}).get("source") != "golden-v0.2"):
            raise RuntimeError(f"Untrusted Golden master provenance: {industry.code}")
    stray = db.get(IndustryCode, "0004", with_for_update=apply)
    if stray is not None and (stray.name, stray.source_window) != ("정보통신공사업", "pytest"):
        raise RuntimeError("0004 unexpectedly exists as a non-test code")
    if stray is not None and db.scalar(select(CompanyIndustry.company_id).where(CompanyIndustry.industry_code == "0004")):
        raise RuntimeError("Unexpected company references test-only 0004")

    result: dict[str, object] = {"mode": "APPLY" if apply else "READ_ONLY",
                                 "test_masters_to_deactivate": sorted(x.code for x in fake if x.active)
                                 + (["0004"] if stray is not None and stray.active else []),
                                 "company_code_replacements": []}
    for label, (company_id, old, new, expected_name) in _CANONICAL.items():
        company = db.get(Company, company_id, with_for_update=apply)
        if company is None or company.name != f"합성회사 {label}":
            raise RuntimeError(f"Unexpected Golden company identity: {label}")
        canonical = db.get(IndustryCode, new)
        if canonical is None or not canonical.active or canonical.name != expected_name:
            raise RuntimeError(f"Verified official master code {new} changed")
        rows = db.scalars(
            select(CompanyIndustry).where(CompanyIndustry.company_id == company_id)
            .with_for_update() if apply else
            select(CompanyIndustry).where(CompanyIndustry.company_id == company_id)
        ).all()
        if len(rows) != 1 or rows[0].industry_code not in (old, new):
            raise RuntimeError(f"Unexpected Golden {label} industry holdings")
        if rows[0].industry_code == old:
            result["company_code_replacements"].append({"company": label, "from": old, "to": new})
            if apply:
                # Keep existing verification false; changing an identifier is
                # NOT evidence of having a legally valid license.
                rows[0].industry_code = new

    # The other 14 synthetic codes remain referenced by Golden company records.
    # Verify no public/non-Golden company relies on them before hiding them.
    for code in _EXPECTED_SYNTHETIC:
        case = code.split("-")[1]
        references = db.execute(
            select(Company.name).join(CompanyIndustry, CompanyIndustry.company_id == Company.id)
            .where(CompanyIndustry.industry_code == code)
        ).scalars().all()
        if references and any(name != f"합성회사 {case}" for name in references):
            raise RuntimeError(f"Unexpected real company references {code}")

    if apply:
        for row in fake:
            row.active = False
        if stray is not None:
            stray.active = False
        db.flush()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Commit guarded changes to the connected DB")
    args = parser.parse_args()
    import json
    with SessionLocal() as db:
        try:
            report = inspect_and_repair(db, apply=args.apply)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if args.apply:
                db.commit()
                print("GUARDED_REPAIR_COMMITTED")
            else:
                db.rollback()
                print("READ_ONLY_NO_CHANGES")
        except BaseException:
            db.rollback()
            raise


if __name__ == "__main__":
    main()
