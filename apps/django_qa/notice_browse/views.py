"""Django 템플릿으로 그리는 공고 조회 화면(목록·검색·상세). 읽기 전용이다.

공고 자료의 주인은 기존 FastAPI 다. Django 는 DB 를 직접 읽지 않고, 로그인한 사용자의
세션을 그대로 넘겨 `/api/v1/notices` 를 불러 HTML 로 보여 주기만 한다(qa_audit 와 같은 경계).
"""
from datetime import datetime
from uuid import UUID

import httpx
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from qa_audit.views import _authorized_user, _headers

PAGE_SIZE = 20
LIST_PATH = "/django/notices/"
BUSINESS_TYPES = {"SERVICE": "용역", "GOODS": "물품", "CONSTRUCTION": "공사", "FOREIGN": "외자"}
VERSION_DATES = ("posted_at", "changed_at", "bid_started_at", "bid_closed_at", "opened_at")


def _when(value):
    """API 의 ISO 시각을 datetime 으로 바꾼다. 템플릿이 한국 시간으로 적는다."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _page_number(raw: str | None) -> int:
    try:
        return min(max(int(raw or "1"), 1), 5000)
    except ValueError:
        return 1


def _problem(request: HttpRequest, status: int, title: str, message: str) -> HttpResponse:
    return render(request, "notice_browse/problem.html", {"title": title, "message": message}, status=status)


def _upstream(request: HttpRequest, path: str, params: dict | None = None):
    """(사용자, 응답) 을 준다. 로그인하지 않았으면 (None, None)."""
    headers = _headers(request)
    with httpx.Client(base_url=settings.FASTAPI_INTERNAL_ORIGIN, follow_redirects=False) as client:
        user = _authorized_user(client, headers)
        if not user:
            return None, None
        return user, client.get(path, headers=headers, params=params or {}, timeout=15)


def _json(response) -> dict | None:
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@require_GET
def notice_list(request: HttpRequest) -> HttpResponse:
    query = (request.GET.get("q") or "").strip()[:200]
    business_type = request.GET.get("business_type") or ""
    if business_type not in BUSINESS_TYPES:
        business_type = ""
    page = _page_number(request.GET.get("page"))
    params = {"limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE}
    if query:
        params["q"] = query
    if business_type:
        params["business_type"] = business_type
    try:
        user, response = _upstream(request, "/api/v1/notices", params)
    except httpx.HTTPError:
        return _problem(request, 503, "공고를 불러오지 못했습니다", "공고 서비스에 연결할 수 없습니다. 잠시 뒤 다시 시도해 주세요.")
    if user is None:
        return _problem(request, 401, "로그인이 필요합니다", "비드체크에 로그인한 뒤 이 화면을 다시 열어 주세요.")
    data = _json(response)
    if data is None or not isinstance(data.get("items"), list):
        return _problem(request, 502, "공고를 불러오지 못했습니다", "공고 서비스의 응답을 읽을 수 없습니다.")
    items = [
        {**item, "business_label": BUSINESS_TYPES.get(item.get("business_type"), item.get("business_type")),
         "last_seen": _when(item.get("last_seen_at"))}
        for item in data["items"] if isinstance(item, dict)
    ]
    total = int(data.get("total") or 0)
    last_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return render(request, "notice_browse/list.html", {
        "user": user, "query": query, "business_type": business_type, "business_types": BUSINESS_TYPES.items(),
        "items": items, "total": total, "page": page, "last_page": last_page,
        "previous_page": page - 1 if page > 1 else None, "next_page": page + 1 if page < last_page else None,
        "first_row": (page - 1) * PAGE_SIZE + 1 if items else 0, "last_row": (page - 1) * PAGE_SIZE + len(items),
    })


@require_GET
def notice_detail(request: HttpRequest, notice_id: UUID) -> HttpResponse:
    try:
        user, response = _upstream(request, f"/api/v1/notices/{notice_id}")
    except httpx.HTTPError:
        return _problem(request, 503, "공고를 불러오지 못했습니다", "공고 서비스에 연결할 수 없습니다. 잠시 뒤 다시 시도해 주세요.")
    if user is None:
        return _problem(request, 401, "로그인이 필요합니다", "비드체크에 로그인한 뒤 이 화면을 다시 열어 주세요.")
    if response.status_code == 404:
        return _problem(request, 404, "공고를 찾을 수 없습니다", "없는 공고이거나 주소가 잘못됐습니다.")
    notice = _json(response)
    if notice is None or not isinstance(notice.get("latest"), dict):
        return _problem(request, 502, "공고를 불러오지 못했습니다", "공고 서비스의 응답을 읽을 수 없습니다.")
    latest = notice["latest"]
    detail_url = latest.get("detail_url") or ""
    back = request.GET.get("back", "")
    return render(request, "notice_browse/detail.html", {
        "user": user, "notice": notice, "latest": latest,
        "dates": {name: _when(latest.get(name)) for name in VERSION_DATES},
        "documents": [doc for doc in latest.get("documents") or [] if isinstance(doc, dict)],
        "business_label": BUSINESS_TYPES.get(notice.get("business_type"), notice.get("business_type")),
        # 원문 링크는 나라장터 주소일 때만 건다. 돌아가기 주소도 이 화면의 목록 주소일 때만 쓴다.
        "detail_url": detail_url if detail_url.startswith("https://www.g2b.go.kr/") else "",
        "back": back if back.startswith(LIST_PATH + "?") else LIST_PATH,
    })
