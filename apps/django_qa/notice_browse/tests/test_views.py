"""공고 조회 화면 테스트. 실제 FastAPI·DB 를 부르지 않는다."""
from unittest.mock import patch
from uuid import uuid4

import httpx
from django.test import SimpleTestCase

LIST = "/django/notices/"
NOTICE_ID = str(uuid4())
USER = {"id": "user-1", "username": "demo-user", "company_id": None}


def summary(index: int, title: str = "전산장비 유지관리 용역") -> dict:
    return {
        "id": str(uuid4()), "bid_notice_no": f"R26BK{index:08d}", "title": title, "business_type": "SERVICE",
        "notice_kind": "등록공고", "demanding_institution_name": "한국산업인력공단", "last_seen_at": "2026-10-14T00:42:45Z",
    }


DETAIL = {
    **summary(1), "id": NOTICE_ID, "announcing_institution_name": "조달청",
    "latest": {
        "version_number": 2, "bid_notice_order": "001", "notice_kind": "변경공고", "contract_method": "제한경쟁",
        "posted_at": "2026-10-14T00:33:24Z", "bid_closed_at": "2026-10-27T01:00:00Z", "allocated_budget": 69777970,
        "change_reason": "입찰 마감 연장", "detail_url": "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R26BK00000001",
        "documents": [{"name": "제안요청서.hwp", "download_status": "DOWNLOADED", "extraction_status": "EXTRACTED", "extracted_char_count": 13782}],
    },
}


class FakeClient:
    """httpx.Client 대역. 무엇을 불렀는지 남긴다."""

    def __init__(self, *args, **kwargs):
        self.signed_in = True
        self.status = 200
        self.payload: object = {"total": 0, "items": []}
        self.calls = []
        self.error = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, *, headers, timeout, params=None):
        self.calls.append((url, dict(params or {}), headers))
        if url == "/api/v1/auth/me":
            return httpx.Response(200 if self.signed_in else 401, json=USER if self.signed_in else {})
        if self.error:
            raise httpx.ConnectError("down")
        return httpx.Response(self.status, json=self.payload)


class NoticeBrowseTests(SimpleTestCase):
    def setUp(self):
        self.fake = FakeClient()
        patcher = patch("notice_browse.views.httpx.Client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.cookies["bidcheck_session"] = "session-token"

    def upstream_calls(self):
        return [call for call in self.fake.calls if call[0] != "/api/v1/auth/me"]

    def test_list_renders_notices_as_html(self):
        self.fake.payload = {"total": 41, "items": [summary(1), summary(2, "학사정보 통합 고도화")]}
        response = self.client.get(LIST)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notice_browse/list.html")
        self.assertContains(response, "학사정보 통합 고도화")
        self.assertContains(response, "R26BK00000001")
        self.assertContains(response, "용역")
        self.assertContains(response, "2026.10.14 09:42")  # 한국 시간으로 적는다
        self.assertContains(response, "전체 41건 중 1–2 · 1 / 3쪽")
        self.assertContains(response, "demo-user 님")

    def test_search_and_page_are_passed_upstream_with_the_session(self):
        self.client.get(LIST, {"q": "  유지관리 ", "business_type": "SERVICE", "page": "3"})
        url, params, headers = self.upstream_calls()[0]
        self.assertEqual(url, "/api/v1/notices")
        self.assertEqual(params, {"limit": 20, "offset": 40, "q": "유지관리", "business_type": "SERVICE"})
        self.assertEqual(headers, {"Cookie": "bidcheck_session=session-token"})

    def test_bad_filters_fall_back_instead_of_reaching_upstream(self):
        self.client.get(LIST, {"business_type": "DROP TABLE", "page": "-7"})
        self.assertEqual(self.upstream_calls()[0][1], {"limit": 20, "offset": 0})
        self.client.get(LIST, {"page": "abc"})
        self.assertEqual(self.upstream_calls()[1][1]["offset"], 0)

    def test_paging_links_keep_the_search(self):
        self.fake.payload = {"total": 60, "items": [summary(index) for index in range(20)]}
        response = self.client.get(LIST, {"q": "유지관리", "page": "2"})
        self.assertContains(response, "page=1")
        self.assertContains(response, "page=3")
        self.assertContains(response, "q=%EC%9C%A0%EC%A7%80%EA%B4%80%EB%A6%AC")

    def test_empty_search_says_so(self):
        response = self.client.get(LIST, {"q": "없는낱말"})
        self.assertContains(response, "「없는낱말」에 맞는 공고가 없습니다.")

    def test_titles_are_escaped(self):
        self.fake.payload = {"total": 1, "items": [summary(1, "<script>alert(1)</script>")]}
        response = self.client.get(LIST)
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_sign_in_is_required(self):
        self.fake.signed_in = False
        for path in (LIST, f"{LIST}{NOTICE_ID}/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertContains(response, "로그인이 필요합니다", status_code=401)
        self.assertEqual(self.upstream_calls(), [])

    def test_missing_cookie_never_calls_upstream(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get(LIST).status_code, 401)
        self.assertEqual(self.fake.calls, [])

    def test_detail_shows_dates_budget_and_documents(self):
        self.fake.payload = DETAIL
        response = self.client.get(f"{LIST}{NOTICE_ID}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.upstream_calls()[0][0], f"/api/v1/notices/{NOTICE_ID}")
        for text in ("전산장비 유지관리 용역", "변경공고", "제한경쟁", "2026.10.27 10:00", "69,777,970원", "입찰 마감 연장",
                     "제안요청서.hwp", "13782", "나라장터에서 보기"):
            with self.subTest(text=text):
                self.assertContains(response, text)

    def test_detail_links_only_to_g2b_and_back_only_to_this_list(self):
        self.fake.payload = {**DETAIL, "latest": {**DETAIL["latest"], "detail_url": "javascript:alert(1)"}}
        response = self.client.get(f"{LIST}{NOTICE_ID}/", {"back": "https://evil.example/"})
        self.assertNotContains(response, "javascript:alert(1)")
        self.assertNotContains(response, "evil.example")
        self.assertContains(response, 'href="/django/notices/"')
        response = self.client.get(f"{LIST}{NOTICE_ID}/", {"back": "/django/notices/?q=a&page=2"})
        self.assertContains(response, 'href="/django/notices/?q=a&amp;page=2"')

    def test_unknown_notice_is_404_and_bad_id_never_reaches_upstream(self):
        self.fake.status = 404
        self.fake.payload = {"error": {"code": "NOTICE_NOT_FOUND"}}
        self.assertEqual(self.client.get(f"{LIST}{NOTICE_ID}/").status_code, 404)
        self.fake.calls.clear()
        self.assertEqual(self.client.get(f"{LIST}not-a-uuid/").status_code, 404)
        self.assertEqual(self.fake.calls, [])

    def test_upstream_trouble_is_reported_not_faked(self):
        self.fake.error = True
        self.assertEqual(self.client.get(LIST).status_code, 503)
        self.fake.error = False
        self.fake.payload = ["not", "an", "object"]
        self.assertEqual(self.client.get(LIST).status_code, 502)
        self.fake.status = 500
        self.assertEqual(self.client.get(f"{LIST}{NOTICE_ID}/").status_code, 502)

    def test_only_get_is_allowed(self):
        self.assertEqual(self.client.post(LIST).status_code, 405)
