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