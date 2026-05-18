"""Mail-rule automations.

A `MailRule` matches an inbound `Message` by sender pattern + subject pattern
and (optionally) the presence of an attachment, then runs a named action.

Designed to start small: today there is one action — `phoenix_capital_schedule`
— that forwards a factoring schedule PDF to TMS-Backend. The dispatcher and
action registry are pluggable so adding rules later is just code + a row.

`MailRuleExecution` is the audit trail (one row per (rule, message) attempt).
"""

import uuid

from django.db import models

from apps.companies.models import Company
from apps.conversations.models import Message


class MailRule(models.Model):
    """A rule that fires an action when a matching inbound message lands."""

    ACTION_PHOENIX_CAPITAL = "phoenix_capital_schedule"
    ACTION_CHOICES = [
        (ACTION_PHOENIX_CAPITAL, "Phoenix Capital factoring schedule"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="mail_rules",
        null=True,
        blank=True,
        help_text=(
            "Tenant the rule belongs to. NULL = global; applied to every "
            "inbound message regardless of mailbox tenant."
        ),
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")

    sender_pattern = models.CharField(
        max_length=300,
        help_text="Regex matched against Message.sender_email (case-insensitive).",
    )
    subject_pattern = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text="Regex matched against Message.subject. Empty = match any.",
    )
    require_attachment = models.BooleanField(default=False)
    attachment_mime_prefix = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Optional, e.g. 'application/pdf'. Empty = any mime.",
    )

    action = models.CharField(max_length=64, choices=ACTION_CHOICES)
    action_config = models.JSONField(default=dict, blank=True)

    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["company__mc_number", "name"]
        indexes = [
            models.Index(fields=["enabled"], name="mail_rule_enabled_idx"),
        ]

    def __str__(self) -> str:
        tenant = self.company.mc_number if self.company_id else "*"
        return f"[{tenant}] {self.name}"


class MailRuleExecution(models.Model):
    """One attempt of one rule against one message."""

    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = [
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.ForeignKey(
        MailRule, on_delete=models.CASCADE, related_name="executions"
    )
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="automation_executions"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    response_summary = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-attempted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "message"],
                name="unique_rule_message_execution",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rule.name} -> {self.message.gmail_message_id} ({self.status})"
