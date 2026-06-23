import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, name="classifier.classify_message")
def classify_message(self, message_id):
    from apps.conversations.models import Message
    from apps.classifier.models import Classification
    from apps.classifier.engine import run_classification
    from apps.mailboxes.gmail_client import get_message, get_body
    try:
        msg = Message.objects.select_related("conversation__mailbox__company").get(id=message_id)
    except Message.DoesNotExist:
        return
    try:
        # Try new MailboxSettings auth first, fall back to legacy gmail_client
        from apps.settings.models import MailboxSettings
        smb = MailboxSettings.objects.filter(
            email_address=msg.conversation.mailbox.email_address, is_active=True
        ).select_related("service_account", "oauth_credential").first()
        if smb:
            from apps.settings.gmail_oauth import get_gmail_service
            import base64
            svc = get_gmail_service(smb)
            raw = svc.users().messages().get(userId="me", id=msg.gmail_message_id, format="full").execute()
            body, _ = get_body(raw)
        else:
            raw  = get_message(msg.conversation.mailbox.email_address, msg.gmail_message_id)
            body, _ = get_body(raw)
    except Exception:
        body = msg.snippet
    try:
        result = run_classification(msg.sender_email, msg.subject, body)
    except Exception as exc:
        raise self.retry(exc=exc)
    Classification.objects.update_or_create(
        message=msg,
        defaults={"category": result["category"], "priority": result["priority"],
                  "ai_summary": result["summary"], "confidence": result["confidence"],
                  "model_version": result.get("model","")},
    )
    conv = msg.conversation
    conv.category = result["category"]
    conv.priority = result["priority"]
    conv.save(update_fields=["category","priority","updated_at"])
    if result["priority"] == "HIGH" or result["category"] in ("SAFETY","COMPLIANCE","AUDIT"):
        try:
            from apps.notifications.tasks import send_inbound_alert
            send_inbound_alert.delay(str(msg.id))
        except Exception:
            pass
