import uuid
from django.db import models


class Company(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=200)
    mc_number  = models.CharField(max_length=50, unique=True)
    dot_number = models.CharField(max_length=50, blank=True)
    status     = models.CharField(max_length=20, default="active")
    rate_floor = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    slack_channel    = models.CharField(max_length=100, blank=True)
    slack_channel_id = models.CharField(max_length=50,  blank=True)
    slack_channel_loads_id     = models.CharField(max_length=50, blank=True)
    slack_channel_loads_name   = models.CharField(max_length=100, blank=True)
    slack_channel_paperwork_id   = models.CharField(max_length=50, blank=True)
    slack_channel_paperwork_name = models.CharField(max_length=100, blank=True)
    ai_auto_reply_enabled = models.BooleanField(default=False,
        help_text="If true, the AI agent will auto-reply to routine emails that don't need human decisions.")
    slack_alerts_enabled = models.BooleanField(default=False,
        help_text="If true, Dispatch OS will post urgent and hourly digest alerts to this company's Slack channels.")

    @property
    def slug(self):
        """Slugified company name for Slack channel naming."""
        import re
        s = self.name.lower().strip()
        s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
        return s

    @property
    def slack_load_ops_channel(self):
        return self.slack_channel_loads_name or f"{self.slug}-load-ops"

    @property
    def slack_paperwork_ops_channel(self):
        return self.slack_channel_paperwork_name or f"{self.slug}-paperwork-ops"
    color      = models.CharField(max_length=10, default="#38bdf8")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "companies"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.mc_number})"
