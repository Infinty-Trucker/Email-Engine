import uuid
from django.db import models
from django.conf import settings
from apps.conversations.models import Conversation, Message


class Approval(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="approvals")
    message      = models.OneToOneField(Message, on_delete=models.CASCADE, related_name="approval")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name="requested_approvals")
    approved_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="reviewed_approvals")
    status      = models.CharField(max_length=10, default="pending",
                    choices=[("pending","Pending"),("approved","Approved"),("rejected","Rejected")])
    reason      = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
