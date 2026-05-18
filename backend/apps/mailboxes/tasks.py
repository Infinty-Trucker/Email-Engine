"""
apps/mailboxes/tasks.py

Email ingestion pipeline.
Uses apps.settings.MailboxSettings for Gmail auth (OAuth or Service Account).
Auto-bridges to apps.mailboxes.Mailbox for Conversation FKs.
"""
import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


def _get_or_create_legacy_mailbox(settings_mb):
    """
    Ensure a legacy Mailbox row exists for this MailboxSettings entry.
    Conversation.mailbox FKs to the legacy Mailbox, so we need this bridge.
    """
    from apps.mailboxes.models import Mailbox
    mb, created = Mailbox.objects.get_or_create(
        email_address=settings_mb.email_address,
        defaults={
            "company":        settings_mb.company,
            "display_name":   settings_mb.display_name or settings_mb.email_address,
            "is_active":      True,
            "watch_status":   settings_mb.watch_status,
            "last_history_id": settings_mb.last_history_id or "",
        }
    )
    if not created and mb.company_id != settings_mb.company_id:
        mb.company = settings_mb.company
        mb.save(update_fields=["company"])
    return mb


def _get_gmail_service(settings_mb):
    from apps.settings.gmail_oauth import get_gmail_service
    return get_gmail_service(settings_mb)


def _parse_headers(msg):
    h = {x["name"].lower(): x["value"] for x in msg.get("payload", {}).get("headers", [])}
    # Extract real Gmail send time
    sent_at = None
    try:
        from email.utils import parsedate_to_datetime
        import datetime
        date_str = h.get("date", "")
        if date_str:
            sent_at = parsedate_to_datetime(date_str)
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=datetime.timezone.utc)
        if not sent_at:
            ms = msg.get("internalDate")
            if ms:
                sent_at = datetime.datetime.fromtimestamp(int(ms)/1000, tz=datetime.timezone.utc)
    except Exception:
        sent_at = None
    return {
        "message_id":  h.get("message-id", ""),
        "in_reply_to": h.get("in-reply-to", ""),
        "subject":     h.get("subject", "") or "",
        "from":        h.get("from", ""),
        "to":          h.get("to", ""),
        "sent_at":     sent_at,
    }


def _extract_body(payload):
    """
    Recursively extract plain text and HTML body from a Gmail message payload.
    Returns (text, html).
    """
    import base64

    def decode(data):
        try:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        except Exception:
            return ""

    mime = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")
    parts = payload.get("parts", [])

    if mime == "text/plain" and body_data:
        return decode(body_data), ""
    if mime == "text/html" and body_data:
        return "", decode(body_data)

    if parts:
        text_parts, html_parts = [], []
        for part in parts:
            t, h = _extract_body(part)
            if t: text_parts.append(t)
            if h: html_parts.append(h)
        return "\n".join(text_parts), "\n".join(html_parts)

    return "", ""


def _clean_body_text(text):
    """Strip Gmail quoted reply text from plain text body."""
    import re
    if not text:
        return ""
    cleaned = re.sub(r"\nOn .{10,200}wrote:[\s\S]*", "", text)
    cleaned = re.sub("\n>.*", "", cleaned)
    cleaned = re.sub(r"\n-{4,}[\s\S]*", "", cleaned)
    return cleaned.strip()


def _extract_attachments(payload, msg_id):
    """
    Return list of attachment metadata dicts from a Gmail message payload.
    Does NOT download binary data — just records name, mime, size, attachment_id.
    """
    attachments = []

    def walk(p):
        filename = p.get("filename", "")
        body     = p.get("body", {})
        if filename and body.get("attachmentId"):
            attachments.append({
                "filename":      filename,
                "mime_type":     p.get("mimeType", "application/octet-stream"),
                "size":          body.get("size", 0),
                "attachment_id": body["attachmentId"],
                "gmail_msg_id":  msg_id,
            })
        for part in p.get("parts", []):
            walk(part)

    walk(payload)
    return attachments


def _extract_email(from_header):
    if "<" in from_header:
        return from_header.split("<")[1].split(">")[0].strip()
    return from_header.strip()


# ── Pub/Sub push ──────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=5, name="mailboxes.process_gmail_push")
def process_gmail_push(self, email_address, new_history_id):
    from apps.settings.models import MailboxSettings

    settings_mb = MailboxSettings.objects.filter(
        email_address=email_address, is_active=True
    ).select_related("service_account", "oauth_credential", "company").first()

    if not settings_mb:
        logger.warning("process_gmail_push: no MailboxSettings for %s", email_address)
        return

    # Skip mailboxes whose watch is broken (revoked OAuth, etc.) — otherwise
    # every Pub/Sub push retries forever and floods the queue.
    if settings_mb.watch_status == "error":
        logger.info("Skipping push for %s — watch_status=error (%s)",
                    email_address, settings_mb.watch_error)
        return
    cred = settings_mb.oauth_credential
    if cred and not cred.is_valid:
        logger.info("Skipping push for %s — OAuth credential invalid", email_address)
        return

    if not settings_mb.last_history_id:
        settings_mb.last_history_id = new_history_id
        settings_mb.save(update_fields=["last_history_id"])
        return

    try:
        svc = _get_gmail_service(settings_mb)
        results, page_token = [], None
        while True:
            kwargs = {
                "userId": "me",
                "startHistoryId": settings_mb.last_history_id,
                "historyTypes": ["messageAdded"],
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = svc.users().history().list(**kwargs).execute()
            results.extend(resp.get("history", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        err_str = str(exc)
        # Auth is dead — mark the mailbox broken and stop retrying.
        if "invalid_grant" in err_str or "revoked" in err_str or "unauthorized_client" in err_str:
            logger.error("OAuth dead for %s — marking watch as error and skipping retry", email_address)
            settings_mb.watch_status = "error"
            settings_mb.watch_error = f"OAuth refresh failed: {err_str[:200]}"
            settings_mb.save(update_fields=["watch_status", "watch_error"])
            if settings_mb.oauth_credential:
                settings_mb.oauth_credential.is_valid = False
                settings_mb.oauth_credential.save(update_fields=["is_valid"])
            return
        logger.error("push history failed for %s: %s", email_address, exc)
        raise self.retry(exc=exc)

    msg_ids = set()
    for rec in results:
        for added in rec.get("messagesAdded", []):
            mid = added.get("message", {}).get("id")
            if mid:
                msg_ids.add(mid)

    for mid in msg_ids:
        ingest_from_settings.delay(str(settings_mb.id), mid)

    settings_mb.last_history_id = new_history_id
    settings_mb.save(update_fields=["last_history_id", "updated_at"])


# ── Primary ingest (MailboxSettings auth) ────────────────────────────────────

@shared_task(bind=True, max_retries=3, name="mailboxes.ingest_from_settings")
def ingest_from_settings(self, settings_mailbox_id, gmail_message_id):
    """Ingest one email using MailboxSettings (OAuth or SA) for auth."""
    from apps.settings.models import MailboxSettings
    from apps.conversations.models import Conversation, Message

    if Message.objects.filter(gmail_message_id=gmail_message_id).exists():
        return

    try:
        smb = MailboxSettings.objects.select_related(
            "service_account", "oauth_credential", "company"
        ).get(id=settings_mailbox_id)
    except MailboxSettings.DoesNotExist:
        logger.error("ingest_from_settings: MailboxSettings %s not found", settings_mailbox_id)
        return

    try:
        svc = _get_gmail_service(smb)
        # Get the triggering message to find its thread_id
        trigger = svc.users().messages().get(userId="me", id=gmail_message_id, format="minimal").execute()
        thread_id = trigger.get("threadId", gmail_message_id)
        # Fetch the full thread to capture the entire conversation
        thread = svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
    except Exception as exc:
        from googleapiclient.errors import HttpError
        if isinstance(exc, HttpError) and exc.resp.status == 404:
            logger.warning("Message %s not found (deleted/trashed) — skipping", gmail_message_id)
            return
        logger.error("fetch thread for %s failed: %s", gmail_message_id, exc)
        raise self.retry(exc=exc)

    legacy_mb = _get_or_create_legacy_mailbox(smb)
    thread_msgs = thread.get("messages", [])

    from apps.conversations.models import Attachment
    from apps.classifier.tasks import classify_message

    for raw in thread_msgs:
        msg_id = raw.get("id", "")
        if not msg_id or Message.objects.filter(gmail_message_id=msg_id).exists():
            continue

        headers    = _parse_headers(raw)
        from_email = _extract_email(headers["from"])
        direction  = "outbound" if from_email.lower() == smb.email_address.lower() else "inbound"
        sent_at    = headers.get("sent_at") or timezone.now()

        payload        = raw.get("payload", {})
        body_text_raw, body_html = _extract_body(payload)
        body_text      = _clean_body_text(body_text_raw)
        att_meta       = _extract_attachments(payload, msg_id)

        # Snapshot mc_number onto the conversation row so the list endpoint
        # can filter by tenant without joining `mailbox → company`. The
        # legacy mailbox always carries a company; if it ever doesn't, the
        # default-empty string keeps the column safe and the X-Tenant filter
        # simply won't match.
        mc_number_cached = ""
        try:
            mc_number_cached = legacy_mb.company.mc_number or ""
        except Exception:
            pass

        conv, created = Conversation.objects.get_or_create(
            gmail_thread_id=thread_id,
            mailbox=legacy_mb,
            defaults={
                "status": "open",
                "last_message_at": sent_at,
                "mc_number": mc_number_cached,
            },
        )
        if not created and (not conv.last_message_at or sent_at > conv.last_message_at):
            Conversation.objects.filter(id=conv.id).update(last_message_at=sent_at, stale_alerted=False)
        # Heal rows created before the denormalization landed.
        if not conv.mc_number and mc_number_cached:
            Conversation.objects.filter(id=conv.id).update(mc_number=mc_number_cached)
            conv.mc_number = mc_number_cached

        msg = Message.objects.create(
            conversation=conv,
            direction=direction,
            gmail_message_id=msg_id,
            sender_email=from_email,
            recipient_email=smb.email_address,
            subject=headers["subject"],
            snippet=raw.get("snippet", ""),
            body_text=body_text or raw.get("snippet", ""),
            body_html=body_html,
            raw_message_id=headers["message_id"],
            in_reply_to=headers["in_reply_to"],
        )

        for att in att_meta:
            try:
                Attachment.objects.create(
                    message=msg, filename=att["filename"],
                    mime_type=att["mime_type"], size=att["size"],
                    gmail_attachment_id=att["attachment_id"], downloaded=False,
                )
            except Exception as att_err:
                logger.warning("Attachment save failed (%s): %s", att["filename"], att_err)

        if direction == "inbound":
            # Backfill the denormalized inbox preview. First inbound wins for
            # sender; subject + snippet upgrade from blank when a later
            # inbound finally arrives with content (Gmail occasionally hands
            # us a reply whose Subject header is empty — the next message
            # with real text fills in the gap so the inbox row isn't blank).
            preview_updates = {}
            if not conv.preview_sender and from_email:
                preview_updates["preview_sender"] = from_email
            if conv.preview_subject in (None, "", "(no subject)") and headers["subject"]:
                preview_updates["preview_subject"] = headers["subject"]
            if not conv.preview_snippet and raw.get("snippet"):
                preview_updates["preview_snippet"] = raw.get("snippet", "")
            if preview_updates:
                Conversation.objects.filter(id=conv.id).update(**preview_updates)
                for k, v in preview_updates.items():
                    setattr(conv, k, v)

            try:
                from apps.classifier.engine import classify_fast
                result = classify_fast(from_email, headers["subject"], body_text)
                conv.category = result["category"]
                conv.priority = result["priority"]
                conv.save(update_fields=["category", "priority", "updated_at"])
                from apps.classifier.models import Classification
                Classification.objects.update_or_create(
                    message=msg,
                    defaults={"category": result["category"], "priority": result["priority"],
                              "ai_summary": result["summary"], "confidence": result["confidence"],
                              "model_version": result.get("model", "keyword")},
                )
            except Exception as cls_err:
                logger.warning("Inline classify failed: %s", cls_err)

            # Run mail-rule automations (e.g. Phoenix Capital factoring
            # schedule auto-import). Failures here are logged but do not
            # block ingest — the message has already been persisted.
            try:
                from apps.automations.dispatcher import dispatch_message
                dispatch_message(msg)
            except Exception as auto_err:
                logger.warning("Automations dispatch failed: %s", auto_err)

    logger.info("Ingested thread %s (%d messages) for %s", thread_id, len(thread_msgs), smb.email_address)


# ── Legacy ingest (kept for backward compat) ─────────────────────────────────

@shared_task(bind=True, max_retries=3, name="mailboxes.ingest_gmail_message")
def ingest_gmail_message(self, mailbox_id, gmail_message_id):
    """Legacy path using apps.mailboxes.Mailbox + old gmail_client."""
    from .models import Mailbox
    from .gmail_client import get_message, parse_headers, extract_email
    from apps.conversations.models import Conversation, Message

    if Message.objects.filter(gmail_message_id=gmail_message_id).exists():
        return
    try:
        mb = Mailbox.objects.select_related("company").get(id=mailbox_id)
    except Mailbox.DoesNotExist:
        return
    try:
        raw = get_message(mb.email_address, gmail_message_id)
    except Exception as exc:
        raise self.retry(exc=exc)

    headers    = parse_headers(raw)
    from_email = extract_email(headers["from"])
    if from_email.lower() == mb.email_address.lower():
        return

    thread_id = raw.get("threadId", "")
    snippet   = raw.get("snippet", "")

    conv, _ = Conversation.objects.get_or_create(
        gmail_thread_id=thread_id,
        mailbox=mb,
        defaults={"status": "open", "last_message_at": timezone.now()},
    )
    Conversation.objects.filter(id=conv.id).update(last_message_at=timezone.now())

    msg = Message.objects.create(
        conversation=conv,
        direction="inbound",
        gmail_message_id=gmail_message_id,
        sender_email=from_email,
        recipient_email=mb.email_address,
        subject=headers["subject"],
        snippet=snippet,
        raw_message_id=headers["message_id"],
        in_reply_to=headers["in_reply_to"],
    )
    try:
        from apps.classifier.engine import classify_fast
        result = classify_fast(from_email, headers["subject"], snippet)
        conv.category = result["category"]
        conv.priority = result["priority"]
        conv.save(update_fields=["category", "priority", "updated_at"])
        from apps.classifier.models import Classification
        Classification.objects.update_or_create(
            message=msg,
            defaults={"category": result["category"], "priority": result["priority"],
                      "ai_summary": result["summary"], "confidence": result["confidence"],
                      "model_version": result.get("model", "keyword")},
        )
    except Exception:
        pass


# ── Watch renewal ─────────────────────────────────────────────────────────────

@shared_task(name="mailboxes.renew_gmail_watches")
def renew_gmail_watches():
    from apps.settings.models import MailboxSettings
    from datetime import datetime, timezone as tz

    cutoff = timezone.now() + timezone.timedelta(days=2)
    for smb in MailboxSettings.objects.filter(is_active=True, watch_expiry__lt=cutoff).select_related("service_account", "oauth_credential"):
        try:
            svc   = _get_gmail_service(smb)
            topic = smb.service_account.pubsub_topic if smb.service_account else ""
            if not topic:
                continue
            result = svc.users().watch(userId="me", body={
                "topicName": topic, "labelIds": ["INBOX"], "labelFilterBehavior": "INCLUDE"
            }).execute()
            expiry = datetime.fromtimestamp(int(result["expiration"]) / 1000, tz=tz.utc)
            smb.watch_status    = "active"
            smb.watch_expiry    = expiry
            smb.last_history_id = result.get("historyId", smb.last_history_id)
            smb.watch_error     = ""
            smb.save()
        except Exception as e:
            from apps.core.error_utils import parse_error
            smb.watch_status = "error"
            smb.watch_error  = parse_error(e, "renewing watch")
            smb.save(update_fields=["watch_status", "watch_error"])
            logger.error("Watch renewal failed for %s: %s", smb.email_address, e)
