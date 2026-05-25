"""
AI agent that reviews unanswered inbound emails and decides whether it can
safely auto-reply on behalf of the company.

Core principle: the agent is CONSERVATIVE — when in doubt, it hands off to a human.
It never touches anything involving money, disputes, legal commitments, or carrier
onboarding.
"""
import json
import logging
import time
from django.conf import settings

logger = logging.getLogger(__name__)

# Process-wide circuit breaker — when Anthropic returns "out of credits" we
# stop hitting the API for a while instead of failing every single call.
_ai_disabled_until = 0.0
_AI_COOLDOWN_SECONDS = 3600  # back off for 1 hour after a billing error


def _ai_is_in_cooldown():
    return time.time() < _ai_disabled_until


def _trigger_ai_cooldown(reason):
    global _ai_disabled_until
    _ai_disabled_until = time.time() + _AI_COOLDOWN_SECONDS
    logger.error("AI agent disabled for %ds — %s", _AI_COOLDOWN_SECONDS, reason)


SYSTEM_PROMPT = """You are an AI dispatch assistant for a freight company. You review
unanswered inbound emails and decide whether to auto-reply or escalate to a human.

SAFE TO AUTO-REPLY (return action=AUTO_REPLY):
- Simple status confirmations ("received BOL", "load delivered on time", "tracking update")
- Acknowledging receipt of rate confirmations (just confirm, don't agree to anything new)
- Providing non-sensitive public info (MC number, DOT number, dispatch phone)
- Routine check-ins with no financial or contractual impact
- Courtesy responses ("thank you", "confirmed", "noted")

NEVER AUTO-REPLY (return action=HUMAN_NEEDED):
- ANY email involving money, rates, payment, deductions, or billing disputes
- New load offers or rate negotiations
- Damage claims, cargo claims, shortages
- Legal matters, contracts, insurance issues
- Safety incidents, accidents, DOT audits, FMCSA matters
- Carrier onboarding, packet requests, W-9 requests
- Complaints or customer escalations
- Anything with a deadline or time-sensitive decision
- Anything the sender is asking for a decision or opinion on
- Anything unclear — when in doubt, always HUMAN_NEEDED

OUTPUT FORMAT (valid JSON only, no markdown):
{
  "action": "AUTO_REPLY" | "HUMAN_NEEDED",
  "reason": "one-sentence explanation of why",
  "category": "status_update" | "acknowledgment" | "info_request" | "rate_offer" | "dispute" | "billing" | "claim" | "safety" | "other",
  "confidence": 0.0 to 1.0,
  "reply_body": "the email body to send (only if action=AUTO_REPLY, otherwise empty string)",
  "reply_subject": "the subject line (only if action=AUTO_REPLY, usually 'Re: <original>')"
}

Only auto-reply if confidence >= 0.85. Otherwise return HUMAN_NEEDED.
Keep reply_body brief, professional, signed with the company name.
"""


def decide_and_draft(company, conversation):
    """
    Ask Claude to decide if this conversation can be auto-replied to.
    Returns dict with action, reason, category, confidence, reply_body, reply_subject.
    If Claude is unavailable or fails, returns HUMAN_NEEDED (safe default).
    """
    if not settings.ANTHROPIC_API_KEY:
        return {"action": "HUMAN_NEEDED", "reason": "AI disabled (no API key)",
                "category": "other", "confidence": 0.0, "reply_body": "", "reply_subject": ""}

    if _ai_is_in_cooldown():
        return {"action": "HUMAN_NEEDED", "reason": "AI in cooldown (recent billing/rate-limit error)",
                "category": "other", "confidence": 0.0, "reply_body": "", "reply_subject": ""}

    # Get the last inbound message and any prior context from the thread
    last_in = conversation.messages.filter(direction="inbound").order_by("-created_at").first()
    if not last_in:
        return {"action": "HUMAN_NEEDED", "reason": "No inbound message",
                "category": "other", "confidence": 0.0, "reply_body": "", "reply_subject": ""}

    thread_context = []
    for m in conversation.messages.order_by("created_at")[:10]:
        role = "FROM_BROKER" if m.direction == "inbound" else "FROM_DISPATCHER"
        body = (m.body_text or m.snippet or "")[:600]
        thread_context.append(f"[{role}] {m.sender_email}\nSubject: {m.subject}\n{body}")

    user_prompt = f"""Company: {company.name} (MC {company.mc_number})
Dispatcher email: {conversation.mailbox.email_address}

EMAIL THREAD (oldest to newest):
{chr(10).join(thread_context)}

Decide whether to auto-reply. Respond with JSON only."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        result = json.loads(raw)

        # Validate and normalize
        action = result.get("action", "HUMAN_NEEDED")
        if action not in ("AUTO_REPLY", "HUMAN_NEEDED"):
            action = "HUMAN_NEEDED"
        confidence = float(result.get("confidence", 0))
        if action == "AUTO_REPLY" and confidence < 0.85:
            action = "HUMAN_NEEDED"
            result["reason"] = f"Confidence {confidence:.2f} below 0.85 threshold"

        return {
            "action": action,
            "reason": result.get("reason", ""),
            "category": result.get("category", "other"),
            "confidence": confidence,
            "reply_body": result.get("reply_body", "") if action == "AUTO_REPLY" else "",
            "reply_subject": result.get("reply_subject", f"Re: {last_in.subject}") if action == "AUTO_REPLY" else "",
        }
    except Exception as e:
        err_str = str(e)
        # Trigger circuit breaker on billing/quota/rate-limit errors so we don't
        # hammer the API with hundreds of failing requests.
        if any(s in err_str for s in (
            "credit balance is too low",
            "insufficient_quota",
            "rate_limit",
            "rate limit",
            "billing",
            "quota",
        )):
            _trigger_ai_cooldown(err_str[:200])
        logger.warning("AI agent decision failed for conv %s: %s", conversation.id, e)
        return {"action": "HUMAN_NEEDED", "reason": f"AI error: {e}",
                "category": "other", "confidence": 0.0, "reply_body": "", "reply_subject": ""}


FOLLOWUP_SYSTEM_PROMPT = """You decide whether a freight dispatcher should send a
follow-up to a broker who has gone silent after the dispatcher's last email.

Output VALID MINIFIED JSON ONLY — no prose, no markdown fences:
{"needs_followup": true, "reason": "...", "confidence": 0.9, "draft_subject": "...", "draft_body": "..."}

Decide NEEDS_FOLLOWUP = true when:
- The dispatcher asked the broker a question and the broker hasn't answered
- The dispatcher is waiting on a confirmation, document, payment, or booking
- The thread is about an active load and silence risks the dispatch

Decide NEEDS_FOLLOWUP = false when:
- The dispatcher's last message closed the loop ("thanks", "confirmed", "noted")
- The broker may legitimately need more time (e.g. dispatcher just asked for a complex quote)
- The thread is informational with no pending action
- The dispatcher's last message was already a follow-up (we've nudged enough)
- Anything ambiguous — when in doubt, false

Draft rules (when needs_followup is true):
- One short paragraph, professional, no greeting fluff
- Reference the original ask in one sentence ("Following up on the rate request for…")
- Ask for the same thing again, give them an easy out ("If timing changed, let us know")
- Keep under 60 words
- Subject = "Re: <original subject>" or "Follow-up: <topic>"
- Never invent facts not in the thread

Confidence rules:
- >= 0.85 when both signals (silence + actionable open question) are clear
- 0.6-0.85 when one signal is fuzzy
- < 0.6 — return needs_followup=false instead
"""


def decide_followup(conversation):
    """Decide whether a stale outbound thread needs a follow-up + draft one.

    Used by the per-thread auto-monitor beat task. Different shape from
    `decide_and_draft` (which handles the inverse: broker→us silence). Returns
    a dict the beat task can post to Slack for human approval.

    Failure modes return needs_followup=False so the beat task simply skips
    the thread (no false positives, no Slack spam).
    """
    fail_default = {
        "needs_followup": False,
        "reason": "",
        "confidence": 0.0,
        "draft_subject": "",
        "draft_body": "",
        "model": "",
    }

    if not settings.ANTHROPIC_API_KEY:
        return {**fail_default, "reason": "AI disabled (no API key)"}
    if _ai_is_in_cooldown():
        return {**fail_default, "reason": "AI in cooldown"}

    msgs = list(conversation.messages.order_by("created_at"))
    if not msgs:
        return {**fail_default, "reason": "no messages"}
    last_msg = msgs[-1]
    if last_msg.direction != "outbound":
        # Caller should have filtered; bail safely if not.
        return {**fail_default, "reason": "last message is not outbound"}

    # Compact transcript — keep token cost predictable. We only need enough
    # context for the model to judge "did the broker actually answer?" so the
    # last 8 messages capped at 500 chars each is plenty.
    transcript = []
    for m in msgs[-8:]:
        role = "DISPATCHER" if m.direction == "outbound" else "BROKER"
        body = (m.body_text or m.snippet or "")[:500]
        transcript.append(f"[{role}] {m.sender_email}\nSubject: {m.subject}\n{body}")

    from django.utils import timezone as tz
    silent_hours = max(0, int((tz.now() - last_msg.created_at).total_seconds() / 3600))

    user_prompt = (
        f"Carrier company: {conversation.mailbox.company.name} "
        f"(MC {conversation.mailbox.company.mc_number})\n"
        f"Dispatcher mailbox: {conversation.mailbox.email_address}\n"
        f"Broker has been silent for {silent_hours}h since the dispatcher's last reply.\n\n"
        f"THREAD (oldest → newest):\n" + "\n---\n".join(transcript)
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=400,
            system=[{
                "type": "text",
                "text": FOLLOWUP_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)

        needs = bool(result.get("needs_followup"))
        confidence = float(result.get("confidence", 0.0))
        if needs and confidence < 0.6:
            # Self-policed threshold matches what the prompt instructs the
            # model to do — belt-and-suspenders for a confused response.
            needs = False
            result["reason"] = f"Confidence {confidence:.2f} below 0.6 threshold"

        return {
            "needs_followup": needs,
            "reason": str(result.get("reason", ""))[:500],
            "confidence": confidence,
            "draft_subject": (str(result.get("draft_subject", "")) or f"Re: {last_msg.subject}")[:300] if needs else "",
            "draft_body": str(result.get("draft_body", ""))[:2000] if needs else "",
            "model": settings.ANTHROPIC_MODEL,
        }
    except Exception as e:
        err_str = str(e)
        if any(s in err_str for s in (
            "credit balance is too low", "insufficient_quota",
            "rate_limit", "rate limit", "billing", "quota",
        )):
            _trigger_ai_cooldown(err_str[:200])
        logger.warning("decide_followup failed for conv %s: %s", conversation.id, e)
        return {**fail_default, "reason": f"AI error: {e}"}


def execute_auto_reply(conversation, decision, user=None):
    """
    Create an outbound Message for the AI's reply and queue it for sending via Gmail.
    Returns the created Message, or None on failure.
    """
    from apps.conversations.models import Message
    from apps.conversations.tasks import send_outbound_email
    import uuid

    last_in = conversation.messages.filter(direction="inbound").order_by("-created_at").first()
    if not last_in:
        return None

    msg = Message.objects.create(
        conversation=conversation,
        direction="outbound",
        gmail_message_id=f"ai-{uuid.uuid4()}",
        sender_email=conversation.mailbox.email_address,
        recipient_email=last_in.sender_email,
        subject=decision["reply_subject"] or f"Re: {last_in.subject}",
        body_text=decision["reply_body"],
        sent_by=user,
    )
    send_outbound_email.delay(str(msg.id))

    # Mark conversation as replied
    from django.utils import timezone as tz
    conversation.status = "replied"
    conversation.last_message_at = tz.now()
    conversation.stale_alerted = True
    conversation.save(update_fields=["status", "last_message_at", "stale_alerted"])

    logger.info("AI agent replied to conv %s: %s", conversation.id, decision["category"])
    return msg
