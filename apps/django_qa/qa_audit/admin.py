from django.contrib import admin
from .models import QaRequest

@admin.register(QaRequest)
class QaRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "user_id", "company_id", "case_id", "status_code", "duration_ms", "created_at")
    list_filter = ("status_code", "created_at")
    search_fields = ("user_id", "company_id", "case_id")
    readonly_fields = tuple(field.name for field in QaRequest._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
