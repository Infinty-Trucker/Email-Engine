from rest_framework import serializers

from apps.automations.models import MailRule, MailRuleExecution


class MailRuleSerializer(serializers.ModelSerializer):
    company_mc_number = serializers.CharField(
        source="company.mc_number", read_only=True, default=None
    )

    class Meta:
        model = MailRule
        fields = [
            "id",
            "company",
            "company_mc_number",
            "name",
            "description",
            "sender_pattern",
            "subject_pattern",
            "require_attachment",
            "attachment_mime_prefix",
            "action",
            "action_config",
            "enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MailRuleExecutionSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source="rule.name", read_only=True)
    message_subject = serializers.CharField(source="message.subject", read_only=True)
    message_sender = serializers.CharField(source="message.sender_email", read_only=True)

    class Meta:
        model = MailRuleExecution
        fields = [
            "id",
            "rule",
            "rule_name",
            "message",
            "message_subject",
            "message_sender",
            "status",
            "response_summary",
            "error",
            "attempted_at",
        ]
        read_only_fields = fields
