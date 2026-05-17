import json, logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from apps.core.error_utils import parse_error, parse_google_error

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, name="conversations.send_outbound_email")
def send_outbound_email(self, message_id):
    """Send an outbound reply via Gmail using MailboxSettings OAuth/SA auth."""
    from apps.conversations.models import Message, Attachment
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    try:
        msg = Message.objects.select_related(
            "conversation__mailbox__company", "sent_by"
        ).get(id=message_id)
    except Message.DoesNotExist:
        logger.error("send_outbound_email: message %s not found", message_id)
        return

    conv    = msg.conversation
    mailbox = conv.mailbox

    # Get Gmail service via MailboxSettings (OAuth or SA)
    try:
        from apps.settings.models import MailboxSettings
        from apps.settings.gmail_oauth import get_gmail_service

        settings_mb = MailboxSettings.objects.select_related(
            "oauth_credential", "service_account"
        ).get(email_address=mailbox.email_address, is_active=True)
        svc = get_gmail_service(settings_mb)
    except Exception as e:
        logger.error("send_outbound_email: could not get Gmail service for %s: %s", mailbox.email_address, e)
        raise self.retry(exc=e)

    # Build the MIME message
    last_in = conv.messages.filter(direction="inbound").order_by("-created_at").first()

    # Check if message has attachments — use mixed multipart if so
    attachments = list(Attachment.objects.filter(message=msg, file__isnull=False).exclude(file=""))
    if attachments:
        mime = MIMEMultipart("mixed")
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(msg.body_text, "plain"))
        if msg.body_html:
            body_part.attach(MIMEText(msg.body_html, "html"))
        mime.attach(body_part)
        for att in attachments:
            try:
                att.file.open("rb")
                file_data = att.file.read()
                att.file.close()
                maintype, _, subtype = (att.mime_type or "application/octet-stream").partition("/")
                part = MIMEBase(maintype, subtype or "octet-stream")
                part.set_payload(file_data)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment", filename=att.filename)
                mime.attach(part)
            except Exception as att_err:
                logger.warning("Could not attach file %s: %s", att.filename, att_err)
    else:
        mime = MIMEMultipart("alternative")
        mime.attach(MIMEText(msg.body_text, "plain"))
        if msg.body_html:
            mime.attach(MIMEText(msg.body_html, "html"))

    mime["From"]    = mailbox.email_address
    mime["To"]      = msg.recipient_email
    mime["Subject"] = msg.subject
    if msg.cc:
        mime["Cc"] = msg.cc
    if last_in and last_in.raw_message_id:
        mime["In-Reply-To"] = last_in.raw_message_id
        mime["References"]  = last_in.raw_message_id

    raw  = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
    body = {"raw": raw}
    # Only set threadId for real Gmail threads — not compose-generated placeholder IDs
    if conv.gmail_thread_id and not conv.gmail_thread_id.startswith("compose-"):
        body["threadId"] = conv.gmail_thread_id

    try:
        result = svc.users().messages().send(userId="me", body=body).execute()
        sent_id    = result.get("id", "")
        real_thread = result.get("threadId", "")
        msg.gmail_message_id = sent_id
        msg.save(update_fields=["gmail_message_id"])
        # Update conversation with the real Gmail thread ID so future replies thread correctly
        if real_thread and conv.gmail_thread_id.startswith("compose-"):
            Conversation = conv.__class__
            Conversation.objects.filter(id=conv.id).update(gmail_thread_id=real_thread)
        logger.info("Sent reply %s for conversation %s", sent_id, conv.id)

        from apps.auditlog.models import AuditEvent
        AuditEvent.objects.create(conversation=conv, message=msg, actor=msg.sent_by, action="replied")
        compliance_audit_scan.delay(str(msg.id))

    except Exception as exc:
        logger.error("send_outbound_email: Gmail send failed for msg %s: %s", message_id, exc, exc_info=True)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, name="conversations.compliance_audit_scan")
def compliance_audit_scan(self, message_id):
    from apps.conversations.models import Message
    from apps.classifier.models import ComplianceScan
    import anthropic
    try:
        msg = Message.objects.select_related("conversation__mailbox__company", "sent_by").get(id=message_id)
    except Message.DoesNotExist:
        return
    if not settings.ANTHROPIC_API_KEY:
        ComplianceScan.objects.get_or_create(message=msg, defaults={"risk_level":"LOW","flags":[],"recommendation":"AI scan disabled.","is_clean":True})
        return
    if ComplianceScan.objects.filter(message=msg).exists():
        return
    company  = msg.conversation.mailbox.company
    sender   = msg.sent_by.get_full_name() if msg.sent_by else "Unknown"
    prompt   = f"""Company: {company.name}\nSender: {sender}\nSubject: {msg.subject}\n\nEmail body:\n{msg.body_text[:2000]}\n\nCheck for: unauthorized rates, legal promises, sensitive info, unusual recipients.\nRespond ONLY with JSON: {{"risk_level":"LOW|MEDIUM|HIGH","flags":["issue"],"recommendation":"one line","is_clean":true}}"""
    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp   = client.messages.create(model=settings.ANTHROPIC_MODEL, max_tokens=300, messages=[{"role":"user","content":prompt}])
        raw    = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
        result = json.loads(raw)
        ComplianceScan.objects.create(
            message=msg, risk_level=result.get("risk_level","LOW"),
            flags=result.get("flags",[]), recommendation=result.get("recommendation",""),
            is_clean=result.get("is_clean",True), model_version=settings.ANTHROPIC_MODEL,
        )
        if not result.get("is_clean", True):
            from apps.notifications.tasks import send_compliance_alert
            send_compliance_alert.delay(str(msg.id))
    except Exception as exc:
        ComplianceScan.objects.get_or_create(message=msg, defaults={"risk_level":"LOW","flags":[],"recommendation":"Scan failed.","is_clean":True})
        raise self.retry(exc=exc)
