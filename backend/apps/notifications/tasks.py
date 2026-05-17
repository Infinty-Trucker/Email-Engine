import logging
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_slack_token():
    """Get Slack bot token — from env var or DB (SlackSettings)."""
    if settings.SLACK_BOT_TOKEN:
        return settings.SLACK_BOT_TOKEN
    try:
        from apps.settings.models import SlackSettings
        ss = SlackSettings.get()
        return ss.bot_token if ss.bot_token_set else ""
    except Exception:
        return ""


_channel_id_cache = {}


def _resolve_channel(client, channel_name):
    """Look up a Slack channel ID by name, with caching."""
    if channel_name.startswith("C") and len(channel_name) >= 9:
        return channel_name  # already an ID
    name = channel_name.lstrip("#").lower()
    if name in _channel_id_cache:
        return _channel_id_cache[name]
    try:
        cursor = None
        while True:
            resp = client.conversations_list(
                types="public_channel,private_channel", limit=200, cursor=cursor or ""
            )
            for ch in resp.get("channels", []):
                _channel_id_cache[ch["name"]] = ch["id"]
                if ch["name"] == name:
                    return ch["id"]
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    except Exception as e:
        logger.warning("Slack channel lookup failed for %s: %s", channel_name, e)
    return None


def _fetch_gmail_attachment(attachment):
    """Download an attachment's bytes from Gmail. Returns (bytes, None) or (None, error)."""
    try:
        from apps.settings.models import MailboxSettings
        from apps.settings.gmail_oauth import get_gmail_service
        import base64

        if not attachment.gmail_attachment_id or not attachment.message:
            return None, "no gmail id"
        mailbox_email = attachment.message.conversation.mailbox.email_address
        mb = MailboxSettings.objects.select_related(
            "service_account", "oauth_credential"
        ).filter(email_address=mailbox_email, is_active=True).first()
        if not mb:
            return None, "mailbox not configured"
        svc = get_gmail_service(mb)
        data = svc.users().messages().attachments().get(
            userId="me",
            messageId=attachment.message.gmail_message_id,
            id=attachment.gmail_attachment_id,
        ).execute()
        file_bytes = base64.urlsafe_b64decode(data.get("data", "") + "==")
        return file_bytes, None
    except Exception as e:
        return None, str(e)


def _build_email_context(conversation, last_in):
    """
    One-line caption for a file upload. Keep it minimal — the narrative summary
    already carries the full story; this just tells the user which email the
    file belongs to.
    """
    subject = (last_in.subject or "(no subject)")[:90]
    sender = (last_in.sender_email or "?").split("@")[0]
    link = _conv_link(conversation)
    return f"📎 *{subject}* — from {sender} · <{link}|open thread>"


def upload_conversation_attachments(channel, conversation):
    """
    Upload attachments from the latest INBOUND message of a conversation to Slack,
    as a single group with a rich context caption (sender, subject, snippet, link).

    Explicitly skips:
      - Outbound messages (replies our users/company sent)
      - Inbound messages where the sender is the company's own mailbox (auto-forwards)
    Returns (uploaded_count, context_comment_posted).
    """
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    token = _get_slack_token()
    if not token or not channel:
        return 0, False

    # Only look at inbound messages — never outbound replies
    last_in = conversation.messages.filter(direction="inbound").order_by("-created_at").first()
    if not last_in:
        return 0, False

    # Skip if the "inbound" message is actually from our own mailbox
    # (auto-forwarded / bounce-back / internal relay)
    mailbox_email = (conversation.mailbox.email_address or "").lower()
    sender = (last_in.sender_email or "").lower()
    if sender == mailbox_email:
        logger.info("Skipping upload — message is self-addressed (%s)", sender)
        return 0, False

    attachments = list(last_in.attachments.all())
    if not attachments:
        return 0, False

    # Strict filter: only upload critical freight docs
    critical = []
    for att in attachments:
        fn = (att.filename or "").lower()
        if fn.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ics", ".vcf")):
            continue
        if any(kw in fn for kw in IMPORTANT_DOC_KEYWORDS):
            critical.append(att)

    if not critical:
        return 0, False

    client = WebClient(token=token)
    channel_id = _resolve_channel(client, channel)
    if not channel_id:
        return 0, False

    MAX_UPLOAD_BYTES = 10 * 1024 * 1024
    MAX_FILES_PER_THREAD = 5  # never spam a channel with dozens of files
    file_uploads = []
    for att in critical[:MAX_FILES_PER_THREAD]:
        if att.size and att.size > MAX_UPLOAD_BYTES:
            logger.info("Skipping %s (%d bytes > 10 MB limit)", att.filename, att.size)
            continue
        file_bytes, err = _fetch_gmail_attachment(att)
        if not file_bytes:
            logger.warning("Could not fetch %s from Gmail: %s", att.filename, err)
            continue
        file_uploads.append({
            "content":  file_bytes,
            "filename": att.filename,
            "title":    att.filename,
        })

    if not file_uploads:
        return 0, False

    # Single initial_comment that carries the email's full context for ALL files
    caption = _build_email_context(conversation, last_in)

    def _do_upload():
        return client.files_upload_v2(
            channel=channel_id,
            file_uploads=file_uploads,
            initial_comment=caption,
        )

    try:
        _do_upload()
        return len(file_uploads), True
    except SlackApiError as e:
        err_code = e.response.get("error", "")
        if err_code == "not_in_channel":
            try:
                client.conversations_join(channel=channel_id)
                _do_upload()
                return len(file_uploads), True
            except Exception as join_err:
                logger.error("Upload failed after join for conv %s: %s", conversation.id, join_err)
        else:
            logger.error("Slack upload failed for conv %s: %s", conversation.id, err_code or str(e))
    except Exception as e:
        logger.error("Slack upload failed for conv %s: %s", conversation.id, e)
    return 0, False


# Backwards-compat wrapper in case anything still calls the old name
def upload_attachments_to_slack(channel, conversation, initial_comment=""):
    count, _ = upload_conversation_attachments(channel, conversation)
    return count


def post_to_slack(channel, text="", blocks=None):
    """
    Send a message to a Slack channel.
    - Accepts channel ID (C...) or name (with or without #)
    - Auto-joins public channels if the bot isn't a member
    - Logs a clear error for private channels that need a manual invite
    Returns True on success, False otherwise.
    """
    token = _get_slack_token()
    if not token or not channel:
        return False
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
        client = WebClient(token=token)

        channel_id = _resolve_channel(client, channel)
        if not channel_id:
            logger.error(
                "Slack channel '%s' not found. For private channels, invite the bot: "
                "/invite @<bot-name> in that channel. For public channels, make sure the bot has "
                "channels:read scope.", channel
            )
            return False

        kwargs = {"channel": channel_id, "text": text or "Dispatch OS"}
        if blocks:
            kwargs["blocks"] = blocks
        try:
            client.chat_postMessage(**kwargs)
            return True
        except SlackApiError as e:
            err_code = e.response.get("error", "")
            if err_code == "not_in_channel":
                # Try to auto-join (works for public channels only)
                try:
                    client.conversations_join(channel=channel_id)
                    client.chat_postMessage(**kwargs)
                    logger.info("Auto-joined and posted to #%s", channel)
                    return True
                except SlackApiError as join_err:
                    je = join_err.response.get("error", "")
                    if je == "method_not_supported_for_channel_type":
                        logger.error(
                            "Cannot auto-join private channel '%s'. "
                            "Invite the bot manually in Slack: /invite @<bot-name>", channel
                        )
                    else:
                        logger.error("Failed to join channel '%s': %s", channel, je)
                    return False
            elif err_code == "channel_not_found":
                logger.error("Slack channel '%s' (ID %s) not found or archived", channel, channel_id)
            else:
                logger.error("Slack post to '%s' failed: %s", channel, err_code or str(e))
            return False
    except Exception as e:
        logger.error("Slack post failed (%s): %s", channel, e)
        return False


@shared_task(name="notifications.send_inbound_alert")
def send_inbound_alert(message_id):
    """
    Fire immediately only for true emergencies (SAFETY/AUDIT) to the global safety channel.
    All other categories are handled by the batched AI summary in check_stale_conversations.
    """
    from apps.conversations.models import Message
    try:
        msg = Message.objects.select_related("conversation__mailbox__company").get(id=message_id)
    except Message.DoesNotExist:
        return
    conv    = msg.conversation
    company = conv.mailbox.company
    if not company.slack_alerts_enabled:
        return
    cat     = conv.category or "GENERAL"
    if cat not in ("SAFETY", "AUDIT"):
        return
    # Route SAFETY/AUDIT urgent alerts to the company's paperwork-ops channel
    channel = company.slack_channel_paperwork_id or company.slack_channel_paperwork_name
    if not channel:
        return
    link = f"{settings.FRONTEND_URL}/?conversation={conv.id}"
    icons = {"SAFETY":"🛡️","AUDIT":"📋"}
    text = (
        f"{icons.get(cat,'⚠️')} *URGENT {cat}* — {company.name} ({company.mc_number})\n"
        f"*{msg.subject}*\n"
        f"From: {msg.sender_email}\n"
        f"{link}"
    )
    post_to_slack(channel, text)


@shared_task(name="notifications.send_approval_request")
def send_approval_request(approval_id):
    from apps.approvals.models import Approval
    try:
        a = Approval.objects.select_related("message__conversation__mailbox__company","requested_by").get(id=approval_id)
    except Approval.DoesNotExist:
        return
    co = a.message.conversation.mailbox.company
    if not co.slack_alerts_enabled:
        return
    # Route to the company's load-ops channel (where dispatchers operate)
    channel = co.slack_channel_loads_id or co.slack_channel_loads_name
    if not channel:
        return
    name = a.requested_by.get_full_name() if a.requested_by else "Unknown"
    link = f"{settings.FRONTEND_URL}/approvals/{a.id}"
    text = f"⏳ *Approval Required* — {co.name}\nFrom: {name}\nSubject: {a.message.subject}\n{link}"
    post_to_slack(channel, text)


LOAD_CATS  = ("LOAD", "DRIVER")
PAPER_CATS = ("BILLING", "CLAIMS", "INSURANCE", "SAFETY", "AUDIT")
ALL_IMPORTANT = LOAD_CATS + PAPER_CATS + ("GENERAL",)


def _conv_link(conversation):
    """Deep link to open this conversation in Dispatch OS."""
    base = getattr(settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/?conversation={conversation.id}"


# ── Urgency classifier ──────────────────────────────────────────────────────
URGENT_KEYWORDS = [
    # Documents for loads in progress
    "bol", "bill of lading", "pod", "proof of delivery", "signed bol",
    "signed pod", "delivery receipt", "lumper receipt",
    # Direct requests for action
    "urgent", "asap", "please respond", "need your", "awaiting your",
    "please confirm", "need confirmation", "waiting on", "follow up",
    "time sensitive", "please send", "need the", "need a",
    # Disputes/escalations
    "dispute", "deduction", "chargeback", "claim", "damage",
    "shortage", "missing", "refused",
    # Check calls/tracking for booked loads
    "check call", "tracking update", "eta",
]

LOAD_OFFER_KEYWORDS = [
    "load offer", "available load", "new load", "load board",
    "lane available", "truck needed", "rate for", "quote",
    "are you interested", "do you have a truck", "covering this",
]


def _classify_urgency(category, subject, body, from_email):
    """
    Determine if an email is URGENT (needs immediate attention) or ROUTINE (can wait for hourly digest).

    Urgent:
      - BOL/POD requests (docs for booked loads)
      - Anyone directly requesting docs/response from us
      - Disputes, claims, damages
      - Safety/audit/DOT matters (always urgent)
      - Billing disputes (not just invoices)
    Routine:
      - Load offers (new loads, not yet booked)
      - Rate confirmations (acknowledgment needed but not time-critical)
      - General info
    """
    s = (subject + " " + (body or "")[:800]).lower()

    # Safety/audit always urgent
    if category in ("SAFETY", "AUDIT", "CLAIMS"):
        return "urgent", f"{category} issue — always urgent"

    # New load offers are routine (not yet committed)
    if any(kw in s for kw in LOAD_OFFER_KEYWORDS):
        # Unless the broker is asking for an explicit confirmation
        if "need confirmation" not in s and "please confirm" not in s:
            return "routine", "Load offer — not yet booked"

    # Explicit urgent keywords
    for kw in URGENT_KEYWORDS:
        if kw in s:
            return "urgent", f"Contains '{kw}'"

    # Questions directed at us (usually need response)
    if "?" in subject or "please" in s[:200] or "can you" in s[:200]:
        return "urgent", "Direct request/question"

    return "routine", ""


def _generate_summary(company, team_label, tasks_or_conversations):
    """
    Produce a Slack task board for a freight department.

    Accepts either AlertTask objects (preferred — preserves urgency + reason)
    or plain Conversation objects. Urgent tasks get a 🚨 badge + reason line.
    """
    if not tasks_or_conversations:
        return None

    from django.utils import timezone as tz
    from .models import AlertTask

    # Normalize: always work with (conversation, urgency, reason) tuples
    enriched = []
    for item in tasks_or_conversations:
        if isinstance(item, AlertTask):
            enriched.append((item.conversation, item.urgency, item.reason or ""))
        else:  # Conversation
            enriched.append((item, "routine", ""))

    # Map team_label → department context for the AI prompt
    dept_context = {
        "Load Ops":      ("DISPATCH DEPARTMENT", "load bookings, driver check-ins, rate confirmations, load status, routing"),
        "Paperwork Ops": ("ACCOUNTING / SAFETY DEPARTMENT", "billing, invoices, BOL/POD, COI/insurance, claims, disputes, DOT audits, driver onboarding"),
    }
    dept_name, dept_scope = dept_context.get(team_label, ("OPERATIONS", "general"))

    # Build thread digests with wait time + urgency computed per thread
    threads = []
    items = []  # (conversation, last_inbound, attachments, wait_label, urgency, reason)

    for conv, urgency, reason in enriched:
        msgs = list(conv.messages.order_by("created_at"))
        last_in = next((m for m in reversed(msgs) if m.direction == "inbound"), None)
        if not last_in:
            continue
        atts = list(last_in.attachments.all())
        wait_delta = tz.now() - last_in.created_at
        wait_label = _humanize_age(wait_delta)
        items.append((conv, last_in, atts, wait_label, urgency, reason))

        urgency_tag = f" [URGENT: {reason}]" if urgency == "urgent" else ""
        thread_lines = [f"=== Task: {last_in.subject or '(no subject)'} — waiting {wait_label}{urgency_tag} ==="]
        for m in msgs[-5:]:
            who = "BROKER" if m.direction == "inbound" else "US (already replied)"
            ts = m.created_at.strftime("%b %d %H:%M UTC")
            body = (m.body_text or m.snippet or "")[:800].strip()
            thread_lines.append(
                f"[{who}] {m.sender_email} — {ts}\n"
                f"Subject: {m.subject}\n"
                f"{body}"
            )
        if atts:
            thread_lines.append("Attachments: " + ", ".join(a.filename for a in atts[:8]))
        threads.append("\n".join(thread_lines))

    if not threads:
        return None

    # Sort: urgent items first
    items.sort(key=lambda x: (x[4] != "urgent", x[0].id))

    urgent_count = sum(1 for i in items if i[4] == "urgent")
    mailbox_email = items[0][0].mailbox.email_address
    header_parts = [f"📋 *{company.name} — {team_label}* · {len(items)} task(s) waiting"]
    if urgent_count:
        header_parts.insert(0, f"🚨 *{urgent_count} URGENT*")
    header = " · ".join(header_parts) + f"\n_{mailbox_email}_"

    # Plain fallback if AI is disabled or in cooldown
    from .ai_agent import _ai_is_in_cooldown
    if not settings.ANTHROPIC_API_KEY or _ai_is_in_cooldown():
        lines = [header, ""]
        for conv, last_in, atts, wait, urgency, reason in items:
            sender_short = (last_in.sender_email or "?").split("@")[0]
            badge = "🚨 *URGENT* — " if urgency == "urgent" else ""
            lines.append(f"{badge}*{last_in.subject[:90]}*")
            lines.append(f"{sender_short} is waiting {wait} for a reply.")
            if urgency == "urgent" and reason:
                lines.append(f"⚡ Why urgent: {reason}")
            if atts:
                lines.append(f"📎 {', '.join(a.filename for a in atts[:3])}")
            lines.append(f"→ <{_conv_link(conv)}|Reply in thread>")
            lines.append("")
        return "\n".join(lines)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        system = (
            "You are the operations manager of a freight carrier. You read unanswered "
            "broker/shipper emails and hand them out as concrete work tasks to your team "
            "in Slack. You are NOT writing a summary — you are writing task assignments. "
            "Each task tells a specific team member: WHO is waiting, WHAT they want, "
            "HOW LONG they've been waiting, and the exact STEPS to complete the task."
        )
        prompt = f"""You are assigning work to the *{dept_name}* at {company.name} (MC {company.mc_number}).
This team handles: {dept_scope}.

Turn each thread below into ONE task card. Each thread header tells you if it
is URGENT (marked "[URGENT: reason]" in the thread header). Urgent cards MUST be
tagged with a 🚨 badge and include the urgency reason.

NORMAL card shape (exactly 4 lines):
*[Emoji] [Broker/Sender Name] — [what they want]*
[1 sentence context: load/invoice #, driver/truck, origin→destination, rate.]
⏰ Waiting [X] for reply.
*Action:* [concrete multi-step instructions naming TMS, portal, doc, and reply.]

URGENT card shape (exactly 5 lines — add the urgency-reason line):
🚨 *URGENT — [Emoji] [Broker/Sender Name] — [what they want]*
[1 sentence context.]
⏰ Waiting [X] for reply.
⚡ *Why urgent:* [exact reason — e.g. "Broker is asking for BOL on a booked load", "Contains 'asap'", "Dispute involving $75 deduction", etc.]
*Action:* [concrete multi-step instructions.]

Emoji choice:
🚛 for load bookings / rate confirmations / driver status
📄 for BOL / POD / invoice / billing / paperwork
🛡️ for safety / DOT / audit / compliance
⚠️ for disputes / claims / damages / deductions
👤 for driver onboarding / carrier packets

Hard rules:
- Urgent cards come FIRST. The threads are already sorted urgent-first — keep that order.
- Merge related threads (same load #, same broker, follow-up reminders) into ONE card.
- DROP anything that is pure spam/marketing/newsletter. Omit entirely.
- The *Action:* line MUST name the system (TMS, broker portal, QuickBooks, etc.), name the doc (BOL, POD, RC, COI), and name the reply ("reply 'done' in this thread", "sign and return"). No vague "follow up" or "review".
- If the email has an attachment that IS the doc being asked for, say: "Download the attached [filename] from Slack above, [what to do with it], reply here when complete."
- Do NOT use numbered lists (1. 2. 3.). Do NOT use ☐ ☑ checkboxes. Do NOT quote paragraphs.
- Put ONE blank line between cards. Nothing else.
- End with ONE line: "_Reply in each thread when done — Dispatch OS will auto-close the task._"

Threads to assign ({len(items)} total, for the *{dept_name}* at {company.name}):

{chr(10).join(threads)}

Respond with ONLY the task cards. No preamble, no header repetition, no code fences. Start with the first task card."""

        msg = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=2500,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = msg.content[0].text.strip()

        # Append per-thread Dispatch OS links as a compact footer
        links_block = ["", "*Open in Dispatch OS:*"]
        for conv, last_in, atts, wait, urgency, reason in items:
            subject = (last_in.subject or "(no subject)")[:70]
            prefix = "🚨 " if urgency == "urgent" else ""
            line = f"• {prefix}<{_conv_link(conv)}|{subject}>"
            if atts:
                att_list = ", ".join(a.filename for a in atts[:3])
                extra = f" +{len(atts)-3}" if len(atts) > 3 else ""
                line += f"  📎 {att_list}{extra}"
            links_block.append(line)

        return header + "\n\n" + summary + "\n" + "\n".join(links_block)
    except Exception as e:
        logger.warning("AI summary failed for %s %s: %s", company.name, team_label, e)
        # Plain fallback without AI
        lines = [header, ""]
        for conv, last_in, atts, wait, urgency, reason in items:
            sender_short = (last_in.sender_email or "?").split("@")[0]
            badge = "🚨 *URGENT* — " if urgency == "urgent" else ""
            lines.append(f"{badge}*{last_in.subject[:90]}*")
            lines.append(f"{sender_short} is waiting {wait} for a reply.")
            if urgency == "urgent" and reason:
                lines.append(f"⚡ Why urgent: {reason}")
            if atts:
                lines.append(f"📎 {', '.join(a.filename for a in atts[:3])}")
            lines.append(f"→ <{_conv_link(conv)}|Reply in thread>")
            lines.append("")
        return "\n".join(lines)


def _route_channel(company, team_type):
    """Return the Slack channel (ID preferred, name fallback) for a given team type."""
    if team_type == "load":
        return company.slack_channel_loads_id or company.slack_channel_loads_name
    if team_type == "paperwork":
        return company.slack_channel_paperwork_id or company.slack_channel_paperwork_name
    return None


def _auto_complete_tasks():
    """Mark AlertTasks as done when their conversation now has an outbound reply."""
    from .models import AlertTask
    from django.utils import timezone as tz
    pending = AlertTask.objects.filter(status=AlertTask.PENDING).select_related("conversation")
    done_count = 0
    for task in pending:
        if task.conversation.messages.filter(direction="outbound").exists():
            task.status = AlertTask.DONE
            task.completed_at = tz.now()
            task.save(update_fields=["status", "completed_at"])
            done_count += 1
    return done_count


def _humanize_age(delta):
    total = int(delta.total_seconds())
    hours = total // 3600
    mins = (total % 3600) // 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


IMPORTANT_DOC_KEYWORDS = [
    "rc", "rate-conf", "rateconf", "rate_confirmation", "ratecon",
    "bol", "bill-of-lading", "billoflading", "bill_of_lading",
    "pod", "proof-of-delivery", "proof_of_delivery",
    "coi", "certificate-of-insurance", "cert-of-ins",
    "invoice", "lumper-receipt", "lumper_receipt",
]


def _has_important_attachments(message):
    """
    Strict check: only truly critical freight docs — RC, BOL, POD, COI, invoice,
    lumper receipts. No "every PDF" fallback. If it's not one of these, skip it.
    """
    for att in message.attachments.all():
        fn = (att.filename or "").lower()
        # Filter out generic image dumps / screenshots / marketing images
        if fn.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
            continue
        if any(kw in fn for kw in IMPORTANT_DOC_KEYWORDS):
            return True
    return False


@shared_task(name="notifications.check_stale_conversations")
def check_stale_conversations():
    """
    Every 2 minutes: scan unanswered emails, create AlertTasks, post URGENT items immediately.
    Routine items (like load offers) are queued for the hourly digest.
    """
    from apps.conversations.models import Conversation
    from datetime import timedelta
    from django.utils import timezone as tz
    from collections import defaultdict
    from .ai_agent import decide_and_draft, execute_auto_reply
    from .models import AlertTask
    from apps.classifier.engine import is_noise

    auto_done = _auto_complete_tasks()
    cutoff = tz.now() - timedelta(minutes=10)

    stale = Conversation.objects.filter(
        status="open",
        stale_alerted=False,
        category__in=ALL_IMPORTANT,
        last_message_at__lte=cutoff,
    ).select_related("mailbox__company").prefetch_related("messages")

    urgent_groups = defaultdict(list)   # {(company_id, team): [AlertTask]} — immediate post
    ai_replies    = defaultdict(list)
    to_mark_only  = []
    noise_skipped = 0
    routine_created = 0

    for conv in stale:
        if conv.messages.filter(direction="outbound").exists():
            to_mark_only.append(conv.id)
            continue
        last_in = conv.messages.filter(direction="inbound").order_by("-created_at").first()
        if not last_in:
            continue

        body = last_in.body_text or last_in.snippet or ""
        if is_noise(last_in.sender_email, last_in.subject, body):
            to_mark_only.append(conv.id)
            noise_skipped += 1
            continue

        company = conv.mailbox.company

        # Skip the company entirely if both Slack alerts AND AI auto-reply are off.
        # No point spending API calls or DB writes on a company that won't get any output.
        if not company.slack_alerts_enabled and not company.ai_auto_reply_enabled:
            to_mark_only.append(conv.id)
            continue

        team = "paperwork" if conv.category in PAPER_CATS else "load"

        # AI agent first — routine emails the agent can handle
        if company.ai_auto_reply_enabled:
            decision = decide_and_draft(company, conv)
            if decision["action"] == "AUTO_REPLY":
                msg = execute_auto_reply(conv, decision)
                if msg:
                    ai_replies[(company.id, team)].append((conv, decision))
                    continue

        # Classify urgency
        urgency, reason = _classify_urgency(conv.category, last_in.subject, body, last_in.sender_email)

        task, created = AlertTask.objects.get_or_create(
            conversation=conv,
            defaults={
                "company": company,
                "team":    team,
                "urgency": urgency,
                "title":   last_in.subject[:300],
                "reason":  reason,
            },
        )
        if not created and task.urgency != urgency:
            task.urgency = urgency
            task.reason  = reason
            task.save(update_fields=["urgency", "reason"])

        if urgency == "urgent":
            urgent_groups[(company.id, team)].append(task)
        else:
            routine_created += 1
            # Mark conversation as handled for stale scanning — the hourly digest
            # reads directly from AlertTask, so it'll still be picked up there.
            Conversation.objects.filter(id=conv.id).update(stale_alerted=True)

    if to_mark_only:
        Conversation.objects.filter(id__in=to_mark_only).update(stale_alerted=True)

    urgent_alerted = 0
    ai_handled = 0

    all_keys = set(urgent_groups.keys()) | set(ai_replies.keys())
    for key in all_keys:
        company_id, team = key
        urgent_tasks = urgent_groups.get(key, [])
        ai_items     = ai_replies.get(key, [])
        if not urgent_tasks and not ai_items:
            continue

        company = (urgent_tasks[0].conversation if urgent_tasks else ai_items[0][0]).mailbox.company
        if not company.slack_alerts_enabled:
            continue
        channel = _route_channel(company, team)
        if not channel:
            logger.warning("No %s channel configured for %s", team, company.name)
            continue

        team_label = "Load Ops" if team == "load" else "Paperwork Ops"
        parts = []

        if ai_items:
            parts.append(f"🤖 *{company.name} — {team_label}: AI agent auto-replied to {len(ai_items)} email(s)*")
            for i, (conv, decision) in enumerate(ai_items, 1):
                last_in = conv.messages.filter(direction="inbound").order_by("-created_at").first()
                if last_in:
                    parts.append(
                        f"  {i}. *{last_in.subject}* — {decision['category']}\n"
                        f"     From: {last_in.sender_email}\n"
                        f"     Why AI handled it: {decision['reason']}\n"
                        f"     → <{_conv_link(conv)}|View thread in Dispatch OS>"
                    )
            parts.append("")

        if urgent_tasks:
            summary = _generate_summary(company, team_label, urgent_tasks)
            if summary:
                parts.append(summary)

        if parts:
            message = "\n".join(parts)
            if post_to_slack(channel, message):
                now = tz.now()
                for t in urgent_tasks:
                    t.first_alerted_at = t.first_alerted_at or now
                    t.last_reminded_at = now
                    t.alert_count += 1
                    t.save(update_fields=["first_alerted_at", "last_reminded_at", "alert_count"])
                    Conversation.objects.filter(id=t.conversation_id).update(stale_alerted=True)
                    # Upload attachments only if the email has critical freight docs
                    # (RC, BOL, POD, COI, invoice, lumper receipt) AND it's the first alert
                    if t.alert_count == 1:
                        last_in = t.conversation.messages.filter(direction="inbound").order_by("-created_at").first()
                        if last_in and _has_important_attachments(last_in):
                            upload_conversation_attachments(channel, t.conversation)
                urgent_alerted += len(urgent_tasks)
                ai_handled += len(ai_items)

    logger.info("Sweep: %d urgent, %d AI-replied, %d routine queued, %d noise, %d auto-done",
                urgent_alerted, ai_handled, routine_created, noise_skipped, auto_done)


@shared_task(name="notifications.hourly_task_digest")
def hourly_task_digest():
    """
    Every hour: post a task digest per company/team showing pending + recently-completed tasks.
    Renders each item as a ☐ (pending) / ☑ (done) checkbox-style row with a deep link.
    """
    from .models import AlertTask
    from datetime import timedelta
    from django.utils import timezone as tz
    from collections import defaultdict

    auto_done = _auto_complete_tasks()

    pending = AlertTask.objects.filter(status=AlertTask.PENDING).select_related(
        "company", "conversation__mailbox"
    ).prefetch_related("conversation__messages")

    groups = defaultdict(lambda: {"urgent": [], "routine": []})
    for task in pending:
        groups[(task.company_id, task.team)][task.urgency].append(task)

    recent_cutoff = tz.now() - timedelta(hours=1, minutes=5)
    recent_done = AlertTask.objects.filter(
        status=AlertTask.DONE,
        completed_at__gte=recent_cutoff,
    ).select_related("company")
    done_groups = defaultdict(list)
    for task in recent_done:
        done_groups[(task.company_id, task.team)].append(task)

    all_keys = set(groups.keys()) | set(done_groups.keys())
    posted = 0

    for key in all_keys:
        company_id, team = key
        group = groups.get(key, {"urgent": [], "routine": []})
        done_list = done_groups.get(key, [])
        if not group["urgent"] and not group["routine"] and not done_list:
            continue

        any_task = (group["urgent"] + group["routine"] + done_list)[0]
        company = any_task.company
        if not company.slack_alerts_enabled:
            continue
        channel = _route_channel(company, team)
        if not channel:
            continue

        team_label = "Load Ops" if team == "load" else "Paperwork Ops"

        # Combine urgent + routine into one task board via _generate_summary.
        # Pass AlertTask objects directly so urgency/reason flow into the prompt.
        all_pending = group["urgent"] + group["routine"]

        parts = []
        if all_pending:
            narrative = _generate_summary(company, team_label, all_pending)
            if narrative:
                parts.append(narrative)

        # Completed since last digest — brief one-liner
        if done_list:
            if parts:
                parts.append("")
            parts.append(f"_✅ Completed since last digest: {len(done_list)} item(s)_")
            for t in done_list[:8]:
                parts.append(f"   · ~{t.title[:80]}~")
            if len(done_list) > 8:
                parts.append(f"   _…and {len(done_list)-8} more_")

        message = "\n".join(parts)
        if post_to_slack(channel, message):
            now = tz.now()
            for t in group["urgent"] + group["routine"]:
                was_first = not t.first_alerted_at
                t.last_reminded_at = now
                t.alert_count += 1
                if was_first:
                    t.first_alerted_at = now
                t.save(update_fields=["last_reminded_at", "alert_count", "first_alerted_at"])
                # Upload important attachments on the first time we alert about this task
                if was_first:
                    last_in = t.conversation.messages.filter(direction="inbound").order_by("-created_at").first()
                    if last_in and last_in.attachments.exists():
                        if _has_important_attachments(last_in):
                            upload_conversation_attachments(channel, t.conversation)
            posted += 1
            logger.info("Hourly digest sent to %s #%s (%d urgent, %d routine, %d done)",
                       company.name, channel, len(group["urgent"]), len(group["routine"]), len(done_list))

    logger.info("Hourly digest complete: %d channels, %d auto-done", posted, auto_done)


@shared_task(name="notifications.send_compliance_alert")
def send_compliance_alert(message_id):
    from apps.conversations.models import Message
    from apps.classifier.models import ComplianceScan
    try:
        msg  = Message.objects.select_related("conversation__mailbox__company","sent_by").get(id=message_id)
        scan = ComplianceScan.objects.get(message=msg)
    except Exception:
        return
    co = msg.conversation.mailbox.company
    if not co.slack_alerts_enabled:
        return
    # Route compliance alerts to the company's paperwork-ops channel
    channel = co.slack_channel_paperwork_id or co.slack_channel_paperwork_name
    if not channel:
        return
    sender = msg.sent_by.get_full_name() if msg.sent_by else "Unknown"
    flags  = "\n".join(f"• {f}" for f in scan.flags) if scan.flags else "None"
    text   = f"🚨 *Compliance Flag — {scan.risk_level} RISK* — {co.name}\nSent by: {sender}\nSubject: {msg.subject}\nFlags:\n{flags}\n{scan.recommendation}"
    post_to_slack(channel, text)
