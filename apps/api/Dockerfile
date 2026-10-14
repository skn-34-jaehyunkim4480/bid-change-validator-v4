# Build context is the repository root (see docker-compose.yml) so the image can
# include the engine package. Dockerfile.dockerignore limits what is sent.
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine /opt/engine
RUN pip install --no-cache-dir --no-deps /opt/engine

COPY apps/api/app ./app
COPY apps/api/alembic.ini .
COPY apps/api/alembic ./alembic
# 골든 v0.2 묶음. 골든 계정·검토 건을 DB 에 넣는 스크립트(app/scripts/seed_golden_v02_accounts.py)가 읽는다.
COPY eval/golden/qualification-v0.2 ./golden/qualification-v0.2

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
