from rest_framework import serializers
from .models import Conversation, Message, Attachment
from apps.classifier.models import Classification


class AttachmentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    def get_url(self, obj):
        return f"/api/conversations/attachments/{obj.id}/download/"

    class Meta:
        model  = Attachment
        fields = ["id", "filename", "mime_type", "size", "downloaded", "gmail_attachment_id", "url"]


class MessageSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Message
        fields = ["id","direction","sender_email","recipient_email","cc","subject",
                  "snippet","body_text","body_html","ai_draft","created_at","sent_by","attachments"]


class ClassificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classification
        fields = ["category","subcategory","priority","ai_summary","confidence","model_version"]


def _conversation_unread(obj):
    # A conversation is unread when a new inbound message has arrived since the
    # last time the user (any user — coarse for v1) marked it read.
    if not obj.last_message_at:
        return False
    if obj.read_at is None:
        return True
    return obj.last_message_at > obj.read_at


class ConversationSerializer(serializers.ModelSerializer):
    messages         = MessageSerializer(many=True, read_only=True)
    company_name     = serializers.CharField(source="mailbox.company.name", read_only=True)
    company_id       = serializers.CharField(source="mailbox.company.id", read_only=True)
    mailbox_email    = serializers.CharField(source="mailbox.email_address", read_only=True)
    latest_classification = serializers.SerializerMethodField()
    unread           = serializers.SerializerMethodField()

    def get_latest_classification(self, obj):
        msg = obj.messages.filter(direction="inbound").last()
        if msg:
            cls = Classification.objects.filter(message=msg).first()
            if cls:
                return ClassificationSerializer(cls).data
        return None

    def get_unread(self, obj):
        return _conversation_unread(obj)

    class Meta:
        model = Conversation
        fields = ["id","gmail_thread_id","company_name","company_id","mailbox_email",
                  "category","priority","status","last_message_at","read_at",
                  "is_starred","unread","created_at","related_load_id",
                  "auto_monitor","last_followup_alert_at",
                  "messages","latest_classification"]


class ConversationListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for the inbox list.

    Reads the denormalized `preview_*` columns on Conversation that the
    ingest task fills at write time. The list endpoint therefore needs zero
    follow-up queries beyond the main SELECT (one JOIN for company name +
    MC number). Anything that wants full bodies + attachments + the message
    chain should hit the detail endpoint.
    """

    company_name  = serializers.CharField(source="mailbox.company.name", read_only=True)
    company_id    = serializers.CharField(source="mailbox.company.id", read_only=True)
    # mc_number is now a local denormalized column on Conversation — no FK
    # traversal at serialization time. Set at ingest, healed by migration
    # 0008's backfill.
    mailbox_email = serializers.CharField(source="mailbox.email_address", read_only=True)
    unread        = serializers.SerializerMethodField()
    # Prefer the denormalized columns (filled at ingest); fall back to the
    # `_fallback_*` Subquery annotations the view adds for the list action so
    # conversations that pre-date the denormalization still render a usable
    # subject / sender / snippet in the inbox.
    preview_sender  = serializers.SerializerMethodField()
    preview_subject = serializers.SerializerMethodField()
    preview_snippet = serializers.SerializerMethodField()

    def get_unread(self, obj):
        return _conversation_unread(obj)

    def get_preview_sender(self, obj):
        return obj.preview_sender or getattr(obj, "_fallback_sender", "") or ""

    def get_preview_subject(self, obj):
        return obj.preview_subject or getattr(obj, "_fallback_subject", "") or ""

    def get_preview_snippet(self, obj):
        return obj.preview_snippet or getattr(obj, "_fallback_snippet", "") or ""

    class Meta:
        model = Conversation
        fields = [
            "id", "gmail_thread_id",
            "company_name", "company_id", "mc_number", "mailbox_email",
            "category", "priority", "status",
            "last_message_at", "read_at", "is_starred", "unread", "created_at",
            "preview_sender", "preview_subject", "preview_snippet",
            "related_load_id", "auto_monitor",
        ]
