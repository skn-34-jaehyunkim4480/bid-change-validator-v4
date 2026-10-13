"""사업자등록번호로 조달청 등록 정보를 찾아 프로필에 쓸 값으로 바꾼다(2026-10-13)."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.routers import companies as companies_router
from apps.api.app.services.g2b import G2BApiError
from apps.api.app.services.procurement_company import ProcurementCompany, fetch_procurement_company


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")
client = TestClient(app)


class _Response:
    def __init__(self, payload: dict) -> None:
        self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class _Session:
    """조회 이름(주소 끝)마다 정해 둔 응답을 돌려준다."""

    def __init__(self, items_by_endpoint: dict[str, list[dict]], error_for: str | None = None) -> None:
        self.items_by_endpoint = items_by_endpoint
        self.error_for = error_for
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, *, params: dict, timeout: float) -> _Response:
        endpoint = url.rsplit("/", 1)[-1]
        self.calls.append((endpoint, params))
        if endpoint == self.error_for:
            return _Response({"nkoneps.com.response.ResponseError": {"header": {"resultCode": "08", "resultMsg": "필수값 입력 에러"}}})
        items = self.items_by_endpoint.get(endpoint, [])
        body = {"numOfRows": params["numOfRows"], "pageNo": params["pageNo"], "totalCount": len(items)}
        if items:
            body["items"] = items
        return _Response({"response": {"header": {"resultCode": "00", "resultMsg": "정상"}, "body": body}})


BASIC = {
    "bizno": "4397100120", "corpNm": "선유건기", "rgnCd": "41450", "rgnNm": "경기도 하남시 덕풍동",
    "adrs": "경기도 하남시 덕산로", "dtlAdrs": "50", "opbizDt": "2017-11-10 00:00:00", "hdoffceDivNm": "본사",
    "ceoNm": "대표자", "telNo": "000-0000-0000",
}


def test_lookup_reads_basics_industries_and_products_by_business_number() -> None:
    session = _Session({
        "getPrcrmntCorpBasicInfo02": [{**BASIC, "corpNm": "선유건기 지점", "hdoffceDivNm": "지사"}, BASIC],
        "getPrcrmntCorpIndstrytyInfo02": [
            {"bizno": "4397100120", "indstrytyCd": "9999", "indstrytyNm": "기타자유업종", "rprsntIndstrytyYn": "N"},
            {"bizno": "4397100120", "indstrytyCd": "4902", "indstrytyNm": "개별건설기계대여업", "rprsntIndstrytyYn": "Y"},
            {"bizno": "4397100120", "indstrytyCd": "4902", "indstrytyNm": "개별건설기계대여업", "rprsntIndstrytyYn": "Y"},
        ],
        "getPrcrmntCorpSplyPrdctInfo02": [
            {"bizno": "4397100120", "dtilPrdctClsfcNo": "8210169801", "dtilPrdctClsfcNoNm": "음원제작서비스"},
        ],
    })
    company = fetch_procurement_company("439-71-00120", service_key="decoded-key", base_url="https://example.test/Usr", session=session)

    assert company is not None and company.name == "선유건기"                 # 본사를 먼저 쓴다
    assert company.business_registration_number == "4397100120"
    assert (company.province_code, company.region_name) == ("41", "경기도 하남시 덕풍동")
    assert company.address == "경기도 하남시 덕산로 50" and company.opened_on == "2017-11-10"
    assert company.industries == [("4902", "개별건설기계대여업", True), ("9999", "기타자유업종", False)]   # 대표 업종 먼저, 중복 없음
    assert company.products == [("8210169801", "음원제작서비스")]
    assert not hasattr(company, "ceo_name")                                   # 대표자·전화번호는 꺼내지 않는다
    by_endpoint = {endpoint: params for endpoint, params in session.calls}
    assert by_endpoint["getPrcrmntCorpBasicInfo02"]["inqryDiv"] == "3"
    assert by_endpoint["getPrcrmntCorpIndstrytyInfo02"]["inqryDiv"] == "1"
    assert all(params["bizno"] == "4397100120" for params in by_endpoint.values())


def test_lookup_maps_renamed_provinces_and_reports_unregistered_numbers() -> None:
    gangwon = _Session({"getPrcrmntCorpBasicInfo02": [{**BASIC, "rgnCd": "42110", "rgnNm": "강원특별자치도 춘천시"}]})
    company = fetch_procurement_company("4397100120", service_key="k", session=gangwon)
    assert company is not None and company.province_code == "51" and company.industries == []

    assert fetch_procurement_company("4397100120", service_key="k", session=_Session({})) is None   # 나라장터에 없는 번호
    with pytest.raises(ValueError):
        fetch_procurement_company("12345", service_key="k", session=_Session({}))
    with pytest.raises(G2BApiError) as failed:                                # 오류 응답의 사유를 읽는다
        fetch_procurement_company("4397100120", service_key="k", session=_Session({}, error_for="getPrcrmntCorpBasicInfo02"))
    assert failed.value.code == "08"


def test_lookup_endpoint_marks_registrable_industries(monkeypatch) -> None:
    monkeypatch.setattr(companies_router, "get_settings", lambda: type("S", (), {"decoded_g2b_service_key": "k"})())
    monkeypatch.setattr(companies_router, "fetch_procurement_company", lambda bizno, service_key: ProcurementCompany(
        business_registration_number=bizno, name="테스트 조달업체", province_code="11", region_name="서울특별시 중구",
        address="서울특별시 중구 세종대로 1", opened_on="2020-01-02", head_office="본사",
        industries=[("0001", "마스터에 있는 업종", True), ("zz99", "마스터에 없는 업종", False)],
        products=[("4321150101", "노트북컴퓨터")],
    ))
    response = client.get("/api/v1/companies/procurement-lookup", params={"business_registration_number": "123-45-67890"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["found"] is True and body["business_registration_number"] == "1234567890"
    assert (body["name"], body["region_code"]) == ("테스트 조달업체", "11")
    assert [(row["code"], row["registrable"]) for row in body["industries"]] == [("0001", True), ("zz99", False)]
    assert body["products"] == [{"code": "4321150101", "name": "노트북컴퓨터"}]
    assert "ceo" not in json.dumps(body).lower() and "tel" not in json.dumps(body).lower()

    monkeypatch.setattr(companies_router, "fetch_procurement_company", lambda bizno, service_key: None)
    missing = client.get("/api/v1/companies/procurement-lookup", params={"business_registration_number": "1234567890"})
    assert missing.status_code == 200 and missing.json()["found"] is False

    invalid = client.get("/api/v1/companies/procurement-lookup", params={"business_registration_number": "123"})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "INVALID_BUSINESS_NUMBER"

    def fail(bizno, service_key):
        raise G2BApiError("G2B_TRANSPORT_ERROR", "boom")
    monkeypatch.setattr(companies_router, "fetch_procurement_company", fail)
    failed = client.get("/api/v1/companies/procurement-lookup", params={"business_registration_number": "1234567890"})
    assert failed.status_code == 502 and failed.json()["error"]["code"] == "PROCUREMENT_LOOKUP_FAILED"


def test_company_with_a_saved_number_looks_up_only_that_number(monkeypatch) -> None:
    from apps.api.app.auth import get_optional_current_user
    from apps.api.app.auth_models import AppUser
    from apps.api.app.database import SessionLocal
    from apps.api.app.models import Company

    monkeypatch.setattr(companies_router, "get_settings", lambda: type("S", (), {"decoded_g2b_service_key": "k"})())
    monkeypatch.setattr(companies_router, "fetch_procurement_company", lambda bizno, service_key: None)
    db = SessionLocal()
    saved = f"{uuid4().int % 10_000_000_000:010d}"
    company = Company(name="번호가 있는 회사", business_registration_number=saved, region_code="11", company_size="SMALL")
    db.add(company)
    db.commit()
    user = AppUser(username=f"lookup-{uuid4().hex[:10]}", password_hash="x", role="ADMIN", company_id=company.id, active=True)
    app.dependency_overrides[get_optional_current_user] = lambda: user
    try:
        own = client.get("/api/v1/companies/procurement-lookup", params={"business_registration_number": saved})
        assert own.status_code == 200, own.text
        other = client.get("/api/v1/companies/procurement-lookup", params={"business_registration_number": "1234567890"})
        assert other.status_code == 403 and other.json()["error"]["code"] == "BUSINESS_NUMBER_MISMATCH"
    finally:
        app.dependency_overrides.pop(get_optional_current_user, None)
        db.delete(company)
        db.commit()
        db.close()
