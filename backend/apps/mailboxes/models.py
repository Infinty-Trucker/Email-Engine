import uuid
from django.db import models
from apps.companies.models import Company


class Mailbox(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company       = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="mailboxes")
    email_address = models.EmailField(unique=True)
    display_name  = models.CharField(max_length=200, blank=True)
    last_history_id = models.CharField(max_length=50, blank=True)
    watch_expiry    = models.DateTimeField(null=True, blank=True)
    watch_status    = models.CharField(max_length=20, default="expired",
                        choices=[("active","Active"),("expired","Expired"),("error","Error")])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "mailboxes"

    def __str__(self):
        return self.email_address
