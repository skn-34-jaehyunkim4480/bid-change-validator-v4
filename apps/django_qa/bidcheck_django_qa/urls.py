from django.contrib import admin
from django.urls import path
from notice_browse.views import notice_detail, notice_list
from qa_audit.views import health, document_chat, my_history

urlpatterns = [
    path("internal/health", health),
    path("api/v1/django-qa/chat", document_chat),
    path("api/v1/django-qa/history", my_history),
    path("django/notices/", notice_list),
    path("django/notices/<uuid:notice_id>/", notice_detail),
    path("django-admin/", admin.site.urls),
]
