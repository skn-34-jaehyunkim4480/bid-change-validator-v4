"""Django-backed document QA gateway, session validation and privacy-safe audit trail.

The existing FastAPI remains the sole authority for user access and the document
RAG answer. Never trust a client-provided company or user identifier.
"""
import hashlib
import json
import logging
import time
from uuid import UUID

import httpx
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import QaRequest

log = logging.getLogger(__name__)
MAX_BODY = 32768
MAX_UPSTREAM_RESPONSE = 2_000_000


def fail(status: int, code: str, message: str) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def _headers(request: HttpRequest) -> dict[str, str]:
    """Pass only the BidCheck credential; never forward arbitrary browser headers."""
    headers = {}
    session = request.COOKIES.get("bidcheck_session")
    bearer = request.headers.get("Authorization", "")
    if bearer.startswith("Bearer "):
        headers["Authorization"] = bearer
    elif session:
        headers["Cookie"] = f"bidcheck_session={session}"
    return headers


def _authorized_user(client: httpx.Client, headers: dict[str, str]):
    if not headers:
        return None
    response = client.get("/api/v1/auth/me", headers=headers, timeout=6)
    if response.status_code != 200:
        return None
    try:
        user = response.json()
        return user if isinstance(user, dict) and user.get("id") else None
    except (ValueError, TypeError):
        return None


def _check_origin(request: HttpRequest, headers: dict[str, str]) -> bool:
    # Existing auth uses cookies, not a Django CSRF session. Enforce explicit
    # same-origin on browser writes to prevent cross-site chargeable LLM calls.
    origin = request.headers.get("Origin", "")
    if origin:
        return origin in settings.QA_ALLOWED_ORIGINS
    return "Authorization" in headers and "Cookie" not in headers


@require_GET
def health(request: HttpRequest):
    return JsonResponse({"status": "ok", "service": "django-document-qa"})


@require_GET
def my_history(request: HttpRequest):
    headers = _headers(request)
    try:
        with httpx.Client(base_url=settings.FASTAPI_INTERNAL_ORIGIN, follow_redirects=False) as client:
            user = _authorized_user(client, headers)
    except httpx.HTTPError:
        return fail(503, "QA_AUTH_UNAVAILABLE", "로그인 확인 서비스에 연결할 수 없습니다.")
    if not user:
        return fail(401, "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.")
    rows = QaRequest.objects.filter(user_id=str(user["id"])).values(
        "id", "case_id", "question_length", "answer_length", "status_code", "duration_ms", "created_at"
    )[:30]
    return JsonResponse({"items": list(rows)})


@csrf_exempt
@require_POST
def document_chat(request: HttpRequest):
    credential = _headers(request)
    if not credential:
        return fail(401, "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.")
    if not _check_origin(request, credential):
        return fail(403, "QA_ORIGIN_FORBIDDEN", "허용되지 않은 요청 출처입니다.")
    if request.content_type != "application/json" or len(request.body) > MAX_BODY:
        return fail(413, "QA_BODY_INVALID", "요청 크기 또는 형식이 올바르지 않습니다.")
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError("not an object")
        case_id = str(UUID(str(payload.get("case_id", ""))))
        message = payload.get("message")
        public_question = payload.get("public_document_question")
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
            raise ValueError("invalid question")
        if not isinstance(public_question, str) or not 1 <= len(public_question.strip()) <= 2000:
            raise ValueError("explicit public question required")
        if payload.get("allow_external_processing") is not True:
            raise ValueError("explicit document-processing consent required")
        if payload.get("intent") not in (None, "DOCUMENT_QA"):
            raise ValueError("not a document question")
        if payload.get("user_input") is not None or payload.get("job_id") or payload.get("question_id"):
            raise ValueError("action/guided execution is not supported")
        if payload.get("response_version", "legacy") not in ("legacy", "3.1"):
            raise ValueError("unsupported Copilot version")
        # The current UI's public-document free-question flow uses version 3.1.
        if payload.get("response_version") == "3.1" and payload.get("free_chat") is not True:
            raise ValueError("3.1 document questions must be explicit free questions")
    except (ValueError, TypeError, OverflowError):
        return fail(422, "DOCUMENT_QA_ONLY", "동의한 공고문 질문만 이 경로로 처리할 수 있습니다.")

    started = time.monotonic()
    headers = {**credential, "Content-Type": "application/json"}
    if request.headers.get("X-Copilot-Semantic-Processing", "").lower() == "true":
        headers["X-Copilot-Semantic-Processing"] = "true"
    try:
        with httpx.Client(base_url=settings.FASTAPI_INTERNAL_ORIGIN, follow_redirects=False) as client:
            user = _authorized_user(client, credential)
            if not user:
                return fail(401, "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.")
            response = client.post(
                "/api/v1/copilot/chat", headers=headers, content=request.body,
                timeout=httpx.Timeout(65.0, connect=5.0),
            )
    except httpx.HTTPError:
        return fail(503, "DOCUMENT_QA_UPSTREAM_UNAVAILABLE", "문서 QA 서비스에 연결할 수 없습니다.")
    if len(response.content) > MAX_UPSTREAM_RESPONSE:
        return fail(502, "DOCUMENT_QA_RESPONSE_TOO_LARGE", "문서 QA 응답이 너무 큽니다.")
    try:
        data = response.json()
    except ValueError:
        return fail(502, "DOCUMENT_QA_INVALID_RESPONSE", "문서 QA 응답 형식이 올바르지 않습니다.")
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    try:
        QaRequest.objects.create(
            user_id=str(user["id"]), company_id=str(user.get("company_id") or "") or None,
            case_id=case_id, question_sha256=hashlib.sha256(message.encode("utf-8")).hexdigest(),
            question_length=len(message),
            answer_length=len(data.get("answer", "")) if isinstance(data, dict) and isinstance(data.get("answer"), str) else 0,
            status_code=response.status_code, duration_ms=duration_ms,
        )
    except Exception:
        # No retry of a billable upstream request on audit-storage failure.
        log.exception("Django QA metadata save failed")
    return JsonResponse(data, status=response.status_code, safe=isinstance(data, dict))
