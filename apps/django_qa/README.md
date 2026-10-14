# Django document QA gateway (optional)

This is **real Django** for the existing user-facing Copilot public-notice-document QA workflow, not a rewrite of FastAPI. Django checks the existing FastAPI session and forwards *only* explicitly consented document QA to the existing RAG endpoint. Django ORM creates `qa_audit.QaRequest` metadata rows; Django Admin can review them without storing question/answer text.

## Boundary and safe rollout

- The original `FastAPI /api/v1/copilot/chat` and all eligibility, company, document, and AI logic are unchanged.
- The existing frontend stays on FastAPI by default. Only `NEXT_PUBLIC_DJANGO_QA_ENABLED=true` **at frontend build time**, and document-processing consent with either the existing 3.1 free-question path or legacy document QA (never guided/action requests), selects `/api/v1/django-qa/chat`.
- Existing session cookie (`bidcheck_session`) or Bearer auth is checked through upstream `/api/v1/auth/me`; Django never trusts a company ID in the client payload. FastAPI checks case ownership again in `/api/v1/copilot/chat`.
- Origin allowlist is required for cookie-authenticated POST to protect against cross-site LLM spending. Upstream redirect is disabled; only the configured internal API address is contacted.
- Only user ID, company ID, case ID, SHA-256 of question, text lengths, upstream status and duration are saved to Django ORM. **Questions, answers, source documents, tokens, passwords, or session cookies are never persisted.**
- Django owns an isolated SQLite database volume, **never the existing RDS schema**. Its migrations are local to the sidecar. No new Postgres migration is required.
- Django Admin exists at `/django-admin/` **inside the sidecar only**; the optional Caddyfile exposes just `/api/v1/django-qa/*`. To use Admin from a trusted local tunnel, create a separate Django superuser and do not publish Admin externally.

## Test locally

```bash
cd apps/django_qa
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test qa_audit
```

On Windows, replace `.venv/bin` with `.venv/Scripts`.

## Opt-in Docker run and future AWS rollout

The default AWS Compose/Caddyfile and CI/CD pipeline **do not deploy Django automatically**. To stage it without disrupting the current service, configure `SITE_DOMAIN` and a random 32+ character `DJANGO_QA_SECRET_KEY` in the Docker Compose environment, then use the **explicit opt-in** compose overlay:

```bash
cd deploy/aws
docker compose -f docker-compose.yml -f docker-compose.django-qa.yml config
docker compose -f docker-compose.yml -f docker-compose.django-qa.yml up -d --build django-qa caddy
```

Verify internal `/internal/health`, same-origin `/api/v1/django-qa/history`, POST `/api/v1/django-qa/chat`, and compare resulting answer/citations with the original FastAPI endpoint. Build the frontend with `NEXT_PUBLIC_DJANGO_QA_ENABLED=true` **only after** sidecar proxy verification. Revert by rebuilding with flag off and using the original Caddyfile/Compose. For AWS auto-deploy integration, add an immutable Django ECR image, container rollout, health gate, and opt-in env to the existing pipeline in a separately reviewed change. Do not flip the flag before Django is healthy.

### Contracts

- `POST /api/v1/django-qa/chat` accepts existing Copilot payload, with `case_id` UUID, `message`, explicit `public_document_question`, `allow_external_processing: true` and `response_version: legacy` or 3.1 (3.1 requires `free_chat: true`). Django returns the existing FastAPI Copilot response JSON and status unchanged.
- `GET /api/v1/django-qa/history` returns only the current authenticated user's latest 30 audit metadata records.
- Unauthorized access: 401; cross-site cookie request: 403; non-document/action request: 422. No fallback to fake model responses.

## 공고 조회 화면 (`notice_browse`, 2026-10-14)

Django 템플릿으로 그리는 읽기 전용 화면입니다. 기존 서비스 화면(React)은 그대로 두고 나란히 둡니다.

- `GET /django/notices/` — 목록과 검색(`q`, `business_type`, `page`). 한 쪽에 20건입니다.
- `GET /django/notices/<공고 UUID>/` — 상세(기관, 일정, 예산, 첨부 문서 목록, 나라장터 원문 링크).
- 공고 자료의 주인은 FastAPI 입니다. Django 는 DB 를 직접 읽지 않고, 로그인 세션(`bidcheck_session`)을 그대로 넘겨 `/api/v1/notices` 를 불러 HTML 로 보여 줍니다. 로그인하지 않았으면 401 화면이 나옵니다.
- 원문 링크는 `https://www.g2b.go.kr/` 주소일 때만 걸고, 목록으로 돌아가는 주소는 이 화면의 목록 주소일 때만 씁니다.

로컬에서 보기(FastAPI 가 8001 에 떠 있을 때):

```bash
cd apps/django_qa
DJANGO_QA_FASTAPI_URL=http://localhost:8001 python manage.py runserver 8002 --noreload
# 서비스 화면(localhost:3000)에 로그인한 브라우저로 http://localhost:8002/django/notices/
python manage.py test qa_audit notice_browse
```

AWS 에서는 선택 배포 묶음(`docker-compose.django-qa.yml` + `Caddyfile.django-qa`)을 올릴 때 `/django/*` 가 함께 열립니다. 기본 배포에는 들어 있지 않습니다.
