import uuid
from django.db import models


class AlertTask(models.Model):
    """
    A single actionable item extracted from an unanswered inbound email.
    Tracks its delivery to Slack, its urgency tier, and whether it's been handled.
    """
    URGENT  = "urgent"
    ROUTINE = "routine"
    URGENCY_CHOICES = [(URGENT, "Urgent"), (ROUTINE, "Routine")]

    PENDING = "pending"
    DONE    = "done"
    DISMISSED = "dismissed"
    STATUS_CHOICES = [(PENDING, "Pending"), (DONE, "Done"), (DISMISSED, "Dismissed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.OneToOneField(
        "conversations.Conversation",
        on_delete=models.CASCADE,
        related_name="alert_task",
    )
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="alert_tasks",
    )
    team = models.CharField(max_length=20, help_text="load or paperwork")
    urgency = models.CharField(max_length=20, choices=URGENCY_CHOICES, default=ROUTINE)
    title = models.CharField(max_length=300, blank=True)
    reason = models.CharField(max_length=500, blank=True,
        help_text="Why this was marked urgent (if applicable)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)

    # Slack delivery tracking
    first_alerted_at = models.DateTimeField(null=True, blank=True)
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    alert_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "urgency"]),
            models.Index(fields=["company", "status"]),
        ]

    def __str__(self):
        return f"{self.title or self.conversation_id} [{self.urgency}/{self.status}]"
