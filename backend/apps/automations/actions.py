"""Action handlers for mail-rule automations.

Each action is a callable ``(rule, message) -> ActionResult``. The dispatcher
looks the handler up by ``rule.action`` in ``ACTION_REGISTRY``. New actions
register here and add a (slug, label) entry to ``MailRule.ACTION_CHOICES``.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import Callable

import requests

from apps.automations.models import MailRule, MailRuleExecution
from apps.conversations.models import Attachment, Message

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    status: str  # one of MailRuleExecution.STATUS_*
    summary: str = ""
    error: str = ""


# --- helpers ---------------------------------------------------------------

def _tms_base() -> str:
    return (os.environ.get("TMS_BACKEND_URL") or "http://localhost:8000").rstrip("/")


def _ingest_token() -> str:
    return os.environ.get("FACTORING_INGEST_TOKEN", "")


def _find_pdf_attachment(message: Message) -> Attachment | None:
    """Pick the first PDF on the message. Phoenix Capital schedules arrive
    as a single attachment, so we don't need fancier selection."""
    qs = message.attachments.all()
    pdf = qs.filter(mime_type__iexact="application/pdf").first()
    if pdf:
        return pdf
    # Fallback: filename ends in .pdf even if mime is octet-stream.
    return qs.filter(filename__iendswith=".pdf").first()


def _download_attachment_bytes(att: Attachment) -> bytes:
    """Fetch the attachment payload. Mirrors the lazy-download pattern in
    ``apps/conversations/urls.py:attachment_download``.
    """
    # Use the locally stored file if it's been downloaded already.
    if att.downloaded and att.file and att.file.name:
        with att.file.open("rb") as fh:
            return fh.read()

    if not att.gmail_attachment_id:
        raise RuntimeError(
            f"Attachment {att.id} has no gmail_attachment_id and no local file."
        )

    from apps.settings.gmail_oauth import get_gmail_service
    from apps.settings.models import MailboxSettings

    mailbox_email = att.message.conversation.mailbox.email_address
    mb_settings = (
        MailboxSettings.objects.select_related("oauth_credential", "service_account")
        .filter(email_address=mailbox_email, is_active=True)
        .first()
    )
    if not mb_settings:
        raise RuntimeError(f"Mailbox {mailbox_email} has no active MailboxSettings.")

    svc = get_gmail_service(mb_settings)
    payload = (
        svc.users()
        .messages()
        .attachments()
        .get(
            userId="me",
            messageId=att.message.gmail_message_id,
            id=att.gmail_attachment_id,
        )
        .execute()
    )
    data = payload.get("data", "")
    if not data:
        raise RuntimeError(
            f"Gmail returned empty body for attachment {att.gmail_attachment_id}."
        )
    return base64.urlsafe_b64decode(data + "==")


# --- action: Phoenix Capital factoring schedule ----------------------------

def phoenix_capital_schedule(rule: MailRule, message: Message) -> ActionResult:
    """Forward a Phoenix Capital schedule PDF to TMS-Backend's factoring
    ingest endpoint.

    Tenant: rule.company.mc_number, falling back to the message's conversation
    mc_number (denormalized at ingest time).
    """
    token = _ingest_token()
    if not token:
        return ActionResult(
            status=MailRuleExecution.STATUS_FAILED,
            error="FACTORING_INGEST_TOKEN not configured in Email-Engine env.",
        )

    mc_no = ""
    if rule.company_id:
        mc_no = rule.company.mc_number or ""
    if not mc_no:
        mc_no = message.conversation.mc_number or ""
    if not mc_no:
        return ActionResult(
            status=MailRuleExecution.STATUS_FAILED,
            error="No mc_no resolvable from rule.company or message.conversation.",
        )

    att = _find_pdf_attachment(message)
    if att is None:
        return ActionResult(
            status=MailRuleExecution.STATUS_SKIPPED,
            summary="No PDF attachment on message.",
        )

    try:
        pdf_bytes = _download_attachment_bytes(att)
    except Exception as exc:
        logger.exception("Failed to download attachment %s", att.id)
        return ActionResult(
            status=MailRuleExecution.STATUS_FAILED,
            error=f"Attachment download failed: {type(exc).__name__}: {exc}",
        )

    url = f"{_tms_base()}/factoring/api/v1/ingest-email/"
    try:
        resp = requests.post(
            url,
            headers={"X-Service-Token": token},
            data={"mc_no": mc_no, "message_id": message.gmail_message_id},
            files={"file": (att.filename or "schedule.pdf", pdf_bytes, "application/pdf")},
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.exception("POST to TMS factoring ingest failed")
        return ActionResult(
            status=MailRuleExecution.STATUS_FAILED,
            error=f"POST to {url} failed: {type(exc).__name__}: {exc}",
        )

    if resp.status_code >= 400:
        return ActionResult(
            status=MailRuleExecution.STATUS_FAILED,
            error=f"TMS rejected ingest ({resp.status_code}): {resp.text[:500]}",
        )

    try:
        body = resp.json()
    except ValueError:
        body = {}
    schedule = body.get("schedule") or {}
    report = body.get("report") or {}
    summary = (
        f"Schedule #{schedule.get('schedule_no', '?')} ingested. "
        f"matched={report.get('matched', 0)} "
        f"unmatched={report.get('unmatched', 0)} "
        f"short_paid={report.get('short_paid', 0)} "
        f"exceptions={report.get('exceptions', 0)}"
    )
    return ActionResult(status=MailRuleExecution.STATUS_SUCCESS, summary=summary)


ACTION_REGISTRY: dict[str, Callable[[MailRule, Message], ActionResult]] = {
    MailRule.ACTION_PHOENIX_CAPITAL: phoenix_capital_schedule,
}
