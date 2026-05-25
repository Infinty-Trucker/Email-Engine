import uuid
from django.db import models
from django.conf import settings
from apps.mailboxes.models import Mailbox


class Conversation(models.Model):
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mailbox         = models.ForeignKey(Mailbox, on_delete=models.PROTECT, related_name="conversations")
    gmail_thread_id = models.CharField(max_length=200)
    slack_channel_id = models.CharField(max_length=50, blank=True)
    slack_thread_ts  = models.CharField(max_length=50, blank=True)
    category    = models.CharField(max_length=20, blank=True)
    priority    = models.CharField(max_length=10, blank=True)
    status      = models.CharField(max_length=20, default="open",
                    choices=[("open","Open"),("pending_approval","Pending Approval"),
                             ("replied","Replied"),("closed","Closed")])
    assigned_dispatcher = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_conversations")
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    stale_alerted   = models.BooleanField(default=False)
    # `read_at` is the timestamp of the last time a user marked the thread read.
    # A conversation is "unread" when last_message_at > read_at (or read_at is null).
    read_at         = models.DateTimeField(null=True, blank=True)
    is_starred      = models.BooleanField(default=False)
    # Denormalized tenant key. Lets the inbox list endpoint filter without
    # joining `mailbox → company`, and lets a composite index serve the
    # `WHERE mc_number = ? ORDER BY last_message_at DESC` pattern in a single
    # range scan. Backfilled on migration; ingest writes it on every new
    # conversation (mailboxes can't change company so this is set-once).
    mc_number        = models.CharField(max_length=32, blank=True, default="", db_index=True)
    # Denormalized inbound preview — populated at ingest time. Lets the inbox
    # list endpoint serve from a single SELECT instead of prefetching every
    # inbound message just to render sender + subject + snippet in the sidebar.
    preview_sender   = models.EmailField(blank=True, default="")
    preview_subject  = models.CharField(max_length=500, blank=True, default="")
    preview_snippet  = models.TextField(blank=True, default="")
    # Loose link to a TMS load (TMS owns the load record). Stored as opaque id
    # to avoid a cross-service FK; indexed so "all email for load X" is a
    # single range scan.
    related_load_id  = models.CharField(max_length=64, blank=True, default="", db_index=True)
    # Per-thread opt-in for the AI follow-up monitor. When True and the last
    # message was outbound + we've gone silent past the cooldown, the
    # check_monitored_followups beat task drafts a follow-up and posts it to
    # the company's Slack channel for human approval.
    auto_monitor     = models.BooleanField(default=False, db_index=True)
    last_followup_alert_at = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("gmail_thread_id", "mailbox")]
        ordering = ["-last_message_at"]
        # Composite index for the canonical inbox query
        # (filter by tenant + sort by recency). Postgres can satisfy
        # WHERE mc_number = ? ORDER BY last_message_at DESC LIMIT N with a
        # single index range scan.
        indexes = [
            models.Index(
                fields=["mc_number", "-last_message_at"],
                name="conv_mc_recency_idx",
            ),
        ]

    def __str__(self):
        return f"{self.mailbox.company.name} | {self.gmail_thread_id}"


class Message(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation     = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    direction        = models.CharField(max_length=10, choices=[("inbound","Inbound"),("outbound","Outbound")])
    gmail_message_id = models.CharField(max_length=200, unique=True)
    raw_message_id   = models.CharField(max_length=500, blank=True)
    in_reply_to      = models.CharField(max_length=500, blank=True)
    sender_email     = models.EmailField()
    recipient_email  = models.EmailField()
    subject          = models.CharField(max_length=500, blank=True)
    snippet          = models.TextField(blank=True)
    cc               = models.TextField(blank=True)   # comma-separated CC addresses
    body_text        = models.TextField(blank=True)   # outbound only
    body_html        = models.TextField(blank=True)   # outbound only
    # `ai_draft` is a tentative reply suggested by the AI engine. It's stashed
    # on the inbound Message it's drafted *for* — survives reloads, lets the
    # dispatcher edit-then-send. Cleared once a real outbound Message is created.
    ai_draft         = models.TextField(blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="sent_messages")
    # Groups outbound messages produced by a single load-channel post that
    # fans out to N brokers (N threads, N Message rows). The channel UI
    # collapses rows sharing this id into one entry. NULL on regular replies.
    channel_post_id  = models.UUIDField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class Attachment(models.Model):
    """File attachment belonging to an inbound email message."""
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message          = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="attachments")
    filename         = models.CharField(max_length=500)
    mime_type        = models.CharField(max_length=200, blank=True)
    size             = models.PositiveIntegerField(default=0)   # bytes
    gmail_attachment_id = models.CharField(max_length=500, blank=True)  # for lazy download
    file             = models.FileField(upload_to="attachments/%Y/%m/", blank=True)  # local storage
    downloaded       = models.BooleanField(default=False)
    created_at       = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.filename} ({self.message.gmail_message_id})"

    @property
    def size_display(self):
        if self.size < 1024:
            return f"{self.size} B"
        if self.size < 1024 * 1024:
            return f"{self.size // 1024} KB"
        return f"{self.size / (1024*1024):.1f} MB"
