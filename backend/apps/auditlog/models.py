import uuid
from django.db import models
from django.conf import settings
from apps.conversations.models import Conversation, Message


class AuditEvent(models.Model):
    ACTIONS = [("viewed","Viewed"),("replied","Replied"),("approved","Approved"),
               ("rejected","Rejected"),("classified","Classified"),("assigned","Assigned")]
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="audit_events")
    message      = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True)
    actor        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action       = models.CharField(max_length=20, choices=ACTIONS)
    details      = models.JSONField(default=dict, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
