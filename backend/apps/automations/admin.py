from django.contrib import admin

from apps.automations.models import MailRule, MailRuleExecution


@admin.register(MailRule)
class MailRuleAdmin(admin.ModelAdmin):
    list_display = (
        "name", "company", "action", "sender_pattern", "subject_pattern",
        "require_attachment", "enabled", "updated_at",
    )
    list_filter = ("action", "enabled", "company")
    search_fields = ("name", "sender_pattern", "subject_pattern", "company__mc_number")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(MailRuleExecution)
class MailRuleExecutionAdmin(admin.ModelAdmin):
    list_display = ("rule", "message", "status", "attempted_at")
    list_filter = ("status", "rule")
    search_fields = ("rule__name", "message__gmail_message_id", "response_summary", "error")
    readonly_fields = (
        "id", "rule", "message", "status", "response_summary",
        "error", "attempted_at",
    )
