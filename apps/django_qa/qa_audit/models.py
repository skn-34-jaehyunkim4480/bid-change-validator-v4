"""Privacy-minimal request metadata; never store raw company questions or LLM answers."""
from django.db import models

class QaRequest(models.Model):
    user_id = models.CharField(max_length=64, db_index=True)
    company_id = models.CharField(max_length=64, null=True, blank=True)
    case_id = models.UUIDField()
    question_sha256 = models.CharField(max_length=64)
    question_length = models.PositiveIntegerField()
    answer_length = models.PositiveIntegerField(default=0)
    status_code = models.PositiveSmallIntegerField()
    duration_ms = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user_id", "-created_at"], name="qa_user_recent_idx")]

    def __str__(self):
        return f"QA {self.id} / {self.status_code}"
