"""조달청 나라장터에 등록된 업체 정보를 사업자등록번호로 찾는다(2026-10-13).

조달청 「사용자정보 서비스」(UsrInfoService02)의 세 조회를 쓴다. 공고 수집과 같은 서비스 키로 부른다.

    getPrcrmntCorpBasicInfo02      inqryDiv=3 + bizno   업체명·소재지(rgnCd)·주소·개업일
    getPrcrmntCorpIndstrytyInfo02  inqryDiv=1 + bizno   등록 업종(업종코드는 industry_codes 와 같은 4자리)
    getPrcrmntCorpSplyPrdctInfo02  inqryDiv=1 + bizno   공급 물품(세부품명번호)

나라장터에 입찰참가자격을 등록한 업체만 나온다. 등록하지 않은 사업자번호는 None 을 돌려준다.
대표자 이름과 전화번호도 응답에 있지만 프로필에 쓰지 않으므로 꺼내지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import requests

from .g2b import G2BApiError, G2BClient

USER_INFO_BASE_URL = "https://apis.data.go.kr/1230000/ao/UsrInfoService02"
# 조달청 소재지 코드(법정동 코드 앞 5자리)의 앞 두 자리가 시·도다. 이름이 바뀐 시·도는 지금 쓰는 코드로 옮긴다
# (apps/web/lib/company-regions.ts 와 같은 기준).
_LEGACY_PROVINCE = {"42": "51", "45": "52", "46": "12", "29": "12"}
_MAX_ROWS = 300


@dataclass(frozen=True)
class ProcurementCompany:
    business_registration_number: str
    name: str
    province_code: str | None
    region_name: str | None
    address: str | None
    opened_on: str | None
    head_office: str | None
    # (업종코드, 업종명, 대표 업종 여부)
    industries: list[tuple[str, str, bool]] = field(default_factory=list)
    # (세부품명번호, 품명)
    products: list[tuple[str, str]] = field(default_factory=list)


def normalize_business_number(value: str) -> str:
    digits = "".join(character for character in str(value) if character.isdigit())
    if len(digits) != 10:
        raise ValueError("사업자등록번호는 숫자 10자리입니다.")
    return digits


def _text(item: dict, key: str) -> str:
    return str(item.get(key) or "").strip()


def _all_pages(client: G2BClient, endpoint: str, params: dict[str, str]) -> list[dict]:
    items: list[dict] = []
    page_number = 1
    while len(items) < _MAX_ROWS:
        page = client.fetch_endpoint_page(endpoint, {**params, "pageNo": page_number, "numOfRows": 100})
        items.extend(page.items)
        if not page.items or page_number * page.page_size >= page.total_count:
            break
        page_number += 1
    return items


def fetch_procurement_company(
    business_registration_number: str,
    *,
    service_key: str,
    base_url: str = USER_INFO_BASE_URL,
    timeout_seconds: float = 15.0,
    session: requests.Session | None = None,
) -> ProcurementCompany | None:
    """사업자등록번호로 조달업체 정보를 모은다. 나라장터에 없으면 None. 호출 실패는 G2BApiError."""
    bizno = normalize_business_number(business_registration_number)
    client = G2BClient(service_key, base_url, timeout_seconds=timeout_seconds, session=session)
    basics = [
        item for item in _all_pages(client, "getPrcrmntCorpBasicInfo02", {"inqryDiv": "3", "bizno": bizno})
        if _text(item, "bizno") == bizno
    ]
    if not basics:
        return None
    # 한 번호에 본사와 지점이 함께 나올 수 있다. 본사를 먼저 쓴다.
    basic = next((item for item in basics if _text(item, "hdoffceDivNm") == "본사"), basics[0])
    region_code = _text(basic, "rgnCd")
    province = region_code[:2] if len(region_code) >= 2 and region_code[:2].isdigit() else None
    industries: dict[str, tuple[str, str, bool]] = {}
    for item in _all_pages(client, "getPrcrmntCorpIndstrytyInfo02", {"inqryDiv": "1", "bizno": bizno}):
        code = _text(item, "indstrytyCd")
        if code and code not in industries:
            industries[code] = (code, _text(item, "indstrytyNm"), _text(item, "rprsntIndstrytyYn") == "Y")
    products: dict[str, tuple[str, str]] = {}
    for item in _all_pages(client, "getPrcrmntCorpSplyPrdctInfo02", {"inqryDiv": "1", "bizno": bizno}):
        code = _text(item, "dtilPrdctClsfcNo")
        if code and code not in products:
            products[code] = (code, _text(item, "dtilPrdctClsfcNoNm"))
    address = " ".join(part for part in (_text(basic, "adrs"), _text(basic, "dtlAdrs")) if part) or None
    return ProcurementCompany(
        business_registration_number=bizno,
        name=_text(basic, "corpNm"),
        province_code=_LEGACY_PROVINCE.get(province, province) if province else None,
        region_name=_text(basic, "rgnNm") or None,
        address=address,
        opened_on=_text(basic, "opbizDt")[:10] or None,
        head_office=_text(basic, "hdoffceDivNm") or None,
        industries=sorted(industries.values(), key=lambda row: (not row[2], row[0])),
        products=list(products.values()),
    )


__all__ = ["G2BApiError", "ProcurementCompany", "fetch_procurement_company", "normalize_business_number"]
