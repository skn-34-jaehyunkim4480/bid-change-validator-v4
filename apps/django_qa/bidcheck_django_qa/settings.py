"""Isolated Django document-QA audit service. Never owns BidCheck's RDS schema."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_QA_SECRET_KEY", "django-qa-local-development-only")
if os.getenv("DJANGO_QA_PRODUCTION", "false").lower() == "true" and (
    SECRET_KEY == "django-qa-local-development-only" or len(SECRET_KEY) < 32
):
    raise RuntimeError("DJANGO_QA_SECRET_KEY must be at least 32 characters in production")
DEBUG = False
ALLOWED_HOSTS = os.getenv("DJANGO_QA_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "qa_audit",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
ROOT_URLCONF = "bidcheck_django_qa.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "bidcheck_django_qa.wsgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": os.getenv("DJANGO_QA_DB_PATH", str(BASE_DIR / "qa-audit.sqlite3")),
    "OPTIONS": {"timeout": 10},
}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Seoul"
STATIC_URL = "/django-static/"
# The upstream service is always a fixed internal endpoint, never caller-controlled.
FASTAPI_INTERNAL_ORIGIN = os.getenv("DJANGO_QA_FASTAPI_URL", "http://api:8000").rstrip("/")
QA_ALLOWED_ORIGINS = frozenset(filter(None, os.getenv(
    "DJANGO_QA_ALLOWED_ORIGINS", "http://localhost:3200,http://127.0.0.1:3200"
).split(",")))
