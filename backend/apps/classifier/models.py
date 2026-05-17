import uuid
from django.db import models
from apps.conversations.models import Message


class Classification(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message       = models.OneToOneField(Message, on_delete=models.CASCADE, related_name="classification")
    category      = models.CharField(max_length=20)
    # Finer-grained label inside `category` — e.g. category=BILLING, subcategory=PAYMENT_ISSUE.
    # Drives the 9-bucket UI taxonomy on the consolidated Email view.
    subcategory   = models.CharField(max_length=30, blank=True)
    priority      = models.CharField(max_length=10)
    ai_summary    = models.CharField(max_length=300, blank=True)
    confidence    = models.FloatField(default=0.9)
    model_version = models.CharField(max_length=50, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)


class ComplianceScan(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message        = models.OneToOneField(Message, on_delete=models.CASCADE, related_name="compliance_scan")
    risk_level     = models.CharField(max_length=10, default="LOW")
    flags          = models.JSONField(default=list)
    recommendation = models.TextField(blank=True)
    is_clean       = models.BooleanField(default=True)
    model_version  = models.CharField(max_length=50, blank=True)
    scanned_at     = models.DateTimeField(auto_now_add=True)
