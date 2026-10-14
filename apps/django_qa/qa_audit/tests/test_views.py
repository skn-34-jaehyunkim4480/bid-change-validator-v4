"""Isolated Django API tests: no AWS/real LLM access or migrations against RDS."""
from unittest.mock import patch
from uuid import uuid4

import httpx
from django.test import TestCase, override_settings
from django.urls import reverse

from qa_audit.models import QaRequest

CASE_ID = str(uuid4())
API_PATH = "/api/v1/django-qa/chat"
HISTORY_PATH = "/api/v1/django-qa/history"
USER = {"id": "user-22", "company_id": "company-j22", "role": "ADMIN"}


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.auth_status = 200
        self.answer_status = 200
        self.auth_user = USER
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, *, headers, timeout):
        self.calls.append(("GET", url, headers))
        return httpx.Response(self.auth_status, json=self.auth_user)

    def post(self, url, *, headers, content, timeout):
        self.calls.append(("POST", url, headers))
        return httpx.Response(self.answer_status, json={"answer": "Verified source", "intent": "DOCUMENT_QA", "citations": []})


def body(**overrides):
    data = {"case_id": CASE_ID, "message": "원문 근거는?", "public_document_question": "원문 근거는?",
            "allow_external_processing": True, "response_version": "legacy"}
    data.update(overrides)
    return data


@override_settings(QA_ALLOWED_ORIGINS=frozenset({"https://example.test"}))
class QaTests(TestCase):
    def setUp(self):
        self.fake = FakeClient()
        self.client.cookies["bidcheck_session"] = "sample-session"
        self.patcher = patch("qa_audit.views.httpx.Client", return_value=self.fake)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def post(self, data=None, **headers):
        return self.client.post(API_PATH, data=body() if data is None else data,
                                content_type="application/json", HTTP_ORIGIN="https://example.test", **headers)

    def test_document_question_round_trips_and_persists_metadata_only(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Verified source")
        row = QaRequest.objects.get()
        self.assertEqual(row.user_id, USER["id"])
        self.assertEqual(row.company_id, USER["company_id"])
        self.assertEqual(str(row.case_id), CASE_ID)
        self.assertEqual(row.question_length, len("원문 근거는?"))
        self.assertEqual(row.answer_length, len("Verified source"))
        self.assertNotIn("원문", str(row.__dict__))
        self.assertEqual(self.fake.calls[0][2]["Cookie"], "bidcheck_session=sample-session")
        history = self.client.get(HISTORY_PATH)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()["items"]), 1)
        self.assertNotIn("question_sha256", history.json()["items"][0])

    def test_v31_document_free_question_is_forwarded(self):
        response = self.post(body(response_version="3.1", free_chat=True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(QaRequest.objects.all()), 1)
        self.assertEqual(self.fake.calls[-1][1], "/api/v1/copilot/chat")

    def test_blocks_anonymous_and_does_not_call_copilot(self):
        self.fake.auth_user = None
        response = self.post()
        self.assertEqual(response.status_code, 401)
        self.assertFalse(any(call[0] == "POST" for call in self.fake.calls))
        self.assertFalse(QaRequest.objects.exists())

    def test_blocks_cross_site_origin(self):
        response = self.client.post(API_PATH, data=body(), content_type="application/json", HTTP_ORIGIN="https://evil.test")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.fake.calls)

    def test_blocks_no_origin_with_session_cookie(self):
        response = self.client.post(API_PATH, data=body(), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_rejects_actions_without_upstream_call(self):
        for addition in ({"user_input": {"apply_to_profile": True}}, {"intent": "ACTION_REQUEST"},
                         {"allow_external_processing": False}, {"response_version": "3.1", "free_chat": False},
                         {"public_document_question": None}, {"case_id": "bad-uuid"}):
            with self.subTest(addition=addition):
                self.assertEqual(self.post(body(**addition)).status_code, 422)
        self.assertFalse(self.fake.calls)

    def test_does_not_leak_other_user_history(self):
        self.post()
        self.fake.auth_user = {"id": "other", "company_id": "other-company"}
        self.assertEqual(self.client.get(HISTORY_PATH).json()["items"], [])

    def test_upstream_denial_propagates_without_fake_answer(self):
        self.fake.answer_status = 403
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(QaRequest.objects.get().status_code, 403)

    def test_missing_cookie_is_not_authenticated(self):
        self.client.cookies.clear()
        self.assertEqual(self.post().status_code, 401)
        self.assertFalse(self.fake.calls)
