from django.contrib import admin
from django.urls import path
from qa_audit.views import health, document_chat, my_history

urlpatterns = [
    path("internal/health", health),
    path("api/v1/django-qa/chat", document_chat),
    path("api/v1/django-qa/history", my_history),
    path("django-admin/", admin.site.urls),
]
