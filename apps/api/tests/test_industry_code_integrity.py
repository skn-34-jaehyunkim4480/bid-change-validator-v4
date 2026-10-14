"""Official G2B code integrity without rewriting historical Golden evidence."""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.database import SessionLocal
from apps.api.app.errors import ApiError
from apps.api.app.models import IndustryCode
from apps.api.app.routers.companies import _validate_industry_codes
from apps.api.app.scripts.seed_golden_v02_accounts import (
    golden_profile_industry_code,
    synthetic_industry_code,
)


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")


def test_golden_j22_j24_use_official_codes_only_in_shared_demo():
    item = {"name": "국내외여행업", "code": "", "verified": False}
    assert golden_profile_industry_code("J22", 1, item, shared_db=True) == "1262"
    assert golden_profile_industry_code("J22", 1, item, shared_db=False) == synthetic_industry_code("J22", 1)
    item["name"] = "건설엔지니어링업(종합)"
    assert golden_profile_industry_code("J24", 1, item, shared_db=True) == "4966"
    item["name"] = "산업디자인전문회사"
    assert golden_profile_industry_code("J23", 1, item, shared_db=True) == "GOLDEN-J23-01"


def test_supplied_explicit_golden_code_is_not_silently_rewritten():
    data = {"name": "국내외여행업", "code": "GOLDEN-J22-01"}
    assert golden_profile_industry_code("J22", 1, data, shared_db=True) == "GOLDEN-J22-01"


def test_public_picker_hides_synthetic_and_test_only_codes():
    with SessionLocal() as db:
        existing = db.get(IndustryCode, "GOLDEN-J22-01")
        assert existing is None
        synthetic = IndustryCode(
            code="GOLDEN-J22-01", name="국내외여행업", active=True,
            source_window="golden-v0.2", collected_at=datetime.now(timezone.utc), raw_json={"source": "golden-v0.2"},
        )
        stray = IndustryCode(
            code="0004", name="정보통신공사업", active=True,
            source_window="pytest", collected_at=datetime.now(timezone.utc), raw_json={"source": "pytest"},
        )
        db.add_all([synthetic, stray])
        db.commit()
        try:
            client = TestClient(app)
            default = client.get("/api/v1/master-codes/industries", params={"q": "국내외여행업"})
            assert default.status_code == 200
            assert all(x["code"] != "GOLDEN-J22-01" for x in default.json()["items"])
            hidden = client.get("/api/v1/master-codes/industries", params={"q": "0004"})
            assert hidden.status_code == 200
            assert all(x["code"] != "0004" for x in hidden.json()["items"])
            history = client.get("/api/v1/master-codes/industries", params={"q": "GOLDEN-J22-01", "active_only": False})
            assert any(x["code"] == "GOLDEN-J22-01" for x in history.json()["items"])
            direct = client.get("/api/v1/master-codes/industries/GOLDEN-J22-01")
            assert direct.status_code == 200
        finally:
            db.delete(synthetic)
            db.delete(stray)
            db.commit()


def test_company_write_rejects_nonofficial_code_even_when_active():
    with SessionLocal() as db:
        good = _validate_industry_codes(db, ["0036"])
        assert set(good) == {"0036"}
        for bad in ("GOLDEN-J22-01", "0004"):
            with pytest.raises(ApiError) as excinfo:
                _validate_industry_codes(db, [bad])
            assert excinfo.value.code == "INVALID_INDUSTRY_CODE"


def test_legacy_repair_is_atomic_and_preserves_evidence_flags():
    """Create old-AWS state inside one transaction, assert changes, rollback all."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from apps.api.app.models import Company, CompanyIndustry
    from apps.api.app.scripts.repair_golden_industry_codes import (
        _CANONICAL, _EXPECTED_SYNTHETIC, inspect_and_repair,
    )

    from pathlib import Path
    import json
    golden = json.loads(Path("eval/golden/qualification-v0.2/fixture_bundle.json").read_text(encoding="utf-8"))
    golden_prefix = next(x["profile_name"].rsplit(" ",1)[0] for x in golden["cases"] if x["case_id"]=="J22")
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        try:
            for label, (cid, old, new, official_name) in _CANONICAL.items():
                master = db.get(IndustryCode, new)
                if master is None:
                    db.add(IndustryCode(code=new, name=official_name, active=True,
                                        collected_at=now, source_window="all",
                                        raw_json={"source": "official-fixture"}))
            db.flush()
            for code in sorted(_EXPECTED_SYNTHETIC):
                master = db.get(IndustryCode, code)
                case_id = code.split("-")[1]
                if master is None:
                    master = IndustryCode(code=code, name="Synthetic " + case_id,
                                          active=True, collected_at=now,
                                          source_window="golden-v0.2",
                                          raw_json={"source": "golden-v0.2", "case_id": case_id})
                    db.add(master)
                else:
                    master.active = True
            official_tele = db.get(IndustryCode, "0036")
            assert official_tele is not None
            stray = db.get(IndustryCode, "0004")
            if stray is None:
                db.add(IndustryCode(code="0004", name=official_tele.name,
                                    active=True, collected_at=now,
                                    source_window="pytest", raw_json={"source": "pytest"}))
            else:
                assert stray.source_window == "pytest"
                stray.active = True
            db.flush()
            for label, (cid, old, new, official_name) in _CANONICAL.items():
                company = db.get(Company, cid)
                if company is None:
                    company = Company(id=cid, name=golden_prefix + " " + label, company_size="SMALL")
                    db.add(company)
                    db.flush()
                else:
                    assert company.name.endswith(label)
                existing = db.scalars(select(CompanyIndustry).where(
                    CompanyIndustry.company_id == cid)).all()
                if not existing:
                    db.add(CompanyIndustry(company_id=cid, industry_code=old, verified=False))
                else:
                    assert len(existing)==1 and existing[0].industry_code in (old,new)
                    existing[0].industry_code = old
                    existing[0].verified = False
            db.flush()
            plan=inspect_and_repair(db,apply=False)
            assert len(plan["test_masters_to_deactivate"]) == 17
            assert len(plan["company_code_replacements"]) == 2
            assert all(db.get(IndustryCode,k).active for k in _EXPECTED_SYNTHETIC)
            report=inspect_and_repair(db,apply=True)
            assert len(report["company_code_replacements"])==2
            assert all(not db.get(IndustryCode,k).active for k in _EXPECTED_SYNTHETIC)
            assert db.get(IndustryCode,"0004").active is False
            for label,(cid,old,new,official_name) in _CANONICAL.items():
                owned=db.scalars(select(CompanyIndustry).where(
                    CompanyIndustry.company_id==cid)).all()
                assert len(owned)==1 and owned[0].industry_code==new
                assert owned[0].verified is False
            # A repeated run must not rewrite anything.
            after=inspect_and_repair(db,apply=True)
            assert after["company_code_replacements"]==[]
            assert after["test_masters_to_deactivate"]==[]
        finally:
            # None of the simulated changes reach the shared test DB.
            db.rollback()
