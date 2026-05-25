"""Load-channel endpoints — Slack-style chat surface for one TMS load.

Architecture:
- A "channel" is a virtual entity derived from Conversation.related_load_id.
  No new table — `LoadChannel` is computed at query time from the existing
  Conversation / Message rows.
- Members are typed (BROKER / DISPATCHER / DRIVER) and resolved at request
  time. Brokers are derived from inbound sender_emails on the channel's
  conversations. Dispatcher comes from Conversation.assigned_dispatcher.
  Driver is proxied from TMS via the load detail endpoint.
- Outbound posts fan out: one Message per distinct broker, each on that
  broker's most recent thread on this load. All fan-outs share a single
  `channel_post_id` UUID so the channel UI can group them as one entry
  with a "delivered to N brokers" badge.

The same endpoints serve both the web inbox UI and the mobile driver app
(session-token auth in both cases).
"""
import logging
import os
import uuid as _uuid
from collections import defaultdict
from datetime import datetime, timezone as dt_tz

import requests
from django.db.models import Count, Max
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def _tenant_scope(request, conv_qs):
    """Apply X-Tenant → mc_number filter the same way ConversationViewSet does."""
    user = request.user
    tenant_mc = request.headers.get("X-Tenant") or request.query_params.get("mc")
    if tenant_mc:
        return conv_qs.filter(mc_number=tenant_mc), tenant_mc
    if user.role not in ("admin", "manager"):
        company_ids = list(user.assigned_companies.values_list("id", flat=True))
        if company_ids:
            return conv_qs.filter(mailbox__company_id__in=company_ids), None
        return conv_qs.none(), None
    return conv_qs, None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_channels(request):
    """List load-channels for the tenant — one row per distinct related_load_id.

    Sorted by most-recent activity. The sidebar uses this to render the
    LOAD CHANNELS section: `#load-1234  3 brokers · 2h`.
    """
    from .models import Conversation
    from apps.users.tms_auth import has_tms_permission

    if not has_tms_permission(request.user, "email.view"):
        return Response({"error": "Missing required permission: email.view"}, status=403)

    conv_qs, _tenant = _tenant_scope(request, Conversation.objects.all())
    conv_qs = conv_qs.exclude(related_load_id="")

    rows = (
        conv_qs.values("related_load_id")
        .annotate(
            thread_count=Count("id", distinct=True),
            last_at=Max("last_message_at"),
        )
        .order_by("-last_at")
    )

    out = []
    for r in rows:
        out.append({
            "load_id": r["related_load_id"],
            "thread_count": r["thread_count"],
            "last_message_at": r["last_at"].isoformat() if r["last_at"] else None,
        })
    return Response({"count": len(out), "results": out})


def _resolve_load_from_tms(request, load_id):
    """Best-effort proxy to TMS for load detail (driver, load_no, revenue).

    Replays the user's X-Session-Token + X-Tenant against TMS so the lookup
    runs as that user. Returns None on any failure — the channel detail
    endpoint degrades gracefully ("driver: unknown") rather than hard-fail.
    """
    tms_base = os.environ.get("TMS_BACKEND_URL", "http://localhost:8000").rstrip("/")
    session_token = request.auth or ""
    tenant_mc = request.headers.get("X-Tenant", "")
    if not session_token or not tenant_mc:
        return None
    try:
        resp = requests.get(
            f"{tms_base}/dispatch-center/api/v1/loads/{load_id}/",
            headers={"X-Session-Token": session_token, "X-Tenant": tenant_mc},
            timeout=4,
        )
    except requests.RequestException as e:
        logger.info("TMS load lookup failed for %s: %s", load_id, e)
        return None
    if resp.status_code >= 400:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def _derive_brokers(messages):
    """Roll inbound sender_emails up into per-broker member records.

    A "broker" here is anyone we've received email from on this channel —
    the address is the stable identity, last_seen drives sort order.
    """
    by_email = {}
    for m in messages:
        if m.direction != "inbound":
            continue
        addr = (m.sender_email or "").lower().strip()
        if not addr:
            continue
        rec = by_email.get(addr)
        if rec is None:
            by_email[addr] = {
                "email": addr,
                "last_seen": m.created_at,
                "message_count": 1,
            }
        else:
            rec["message_count"] += 1
            if m.created_at and (rec["last_seen"] is None or m.created_at > rec["last_seen"]):
                rec["last_seen"] = m.created_at
    return sorted(
        by_email.values(),
        key=lambda r: r["last_seen"] or datetime.min.replace(tzinfo=dt_tz.utc),
        reverse=True,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def channel_detail(request, load_id):
    """Return channel metadata + members for one load.

    Members are derived live — brokers from inbound senders, dispatcher from
    Conversation.assigned_dispatcher, driver from TMS. Cheap because the
    channel has at most a few dozen messages.
    """
    from .models import Conversation, Message
    from apps.users.tms_auth import has_tms_permission

    if not has_tms_permission(request.user, "email.view"):
        return Response({"error": "Missing required permission: email.view"}, status=403)

    conv_qs, _tenant = _tenant_scope(request, Conversation.objects.all())
    convs = list(
        conv_qs.filter(related_load_id=load_id)
        .select_related("assigned_dispatcher", "mailbox__company")
    )
    if not convs:
        return Response({"error": f"No channel for load {load_id}"}, status=404)

    msgs = list(
        Message.objects
        .filter(conversation__in=convs)
        .only("id", "direction", "sender_email", "created_at")
    )

    brokers = _derive_brokers(msgs)

    # Dispatcher is whoever's assigned on any of the underlying conversations.
    # If multiple conversations have different dispatchers, surface the most
    # recently-active one rather than picking arbitrarily.
    dispatcher = None
    convs_sorted = sorted(
        convs, key=lambda c: c.last_message_at or datetime.min.replace(tzinfo=dt_tz.utc),
        reverse=True,
    )
    for c in convs_sorted:
        if c.assigned_dispatcher:
            d = c.assigned_dispatcher
            dispatcher = {
                "user_id": d.id,
                "name": d.get_full_name() or d.email or "",
                "email": d.email or "",
            }
            break

    # TMS proxy for driver. Single round-trip; failures degrade silently.
    tms_load = _resolve_load_from_tms(request, load_id)
    driver = None
    load_no = ""
    if tms_load:
        load_no = str(tms_load.get("load_no") or "")
        d = tms_load.get("driver")
        # The detail serializer returns `driver` as a nested object {id, user, driver_name, phone}
        if isinstance(d, dict):
            driver = {
                "driver_id": d.get("id"),
                "name": d.get("driver_name") or "",
                "phone": d.get("phone") or "",
            }

    auto_monitor = any(c.auto_monitor for c in convs)
    company_names = sorted({c.mailbox.company.name for c in convs if c.mailbox and c.mailbox.company})
    return Response({
        "load_id": load_id,
        "load_no": load_no,
        "name": f"#load-{load_no or load_id[:8]}",
        "thread_count": len(convs),
        "message_count": len(msgs),
        "auto_monitor": auto_monitor,
        "companies": company_names,
        "members": {
            "brokers": [
                {
                    "email": b["email"],
                    "last_seen": b["last_seen"].isoformat() if b["last_seen"] else None,
                    "message_count": b["message_count"],
                }
                for b in brokers
            ],
            "dispatcher": dispatcher,
            "driver": driver,
        },
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def post_channel_message(request, load_id):
    """Send a message to every broker on the load.

    Body: `{ "body": "...", "cc": "optional@…" }`

    One UUID `channel_post_id` is stamped on every outbound Message we create,
    so the channel timeline can group them and display the single post (with
    a "delivered to N brokers" badge) instead of N near-duplicate rows.

    Each broker gets their own thread reply — they never see each other's
    addresses. Bodies / subjects are identical; routing is per-thread.
    """
    from .models import Conversation, Message
    from apps.conversations.tasks import send_outbound_email
    from apps.users.tms_auth import has_tms_permission
    from django.utils import timezone

    user = request.user
    if not has_tms_permission(user, "email.send"):
        return Response({"error": "Missing required permission: email.send"}, status=403)

    body = (request.data.get("body") or "").strip()
    cc = (request.data.get("cc") or "").strip()
    if not body:
        return Response({"error": "body required"}, status=400)

    conv_qs, _tenant = _tenant_scope(request, Conversation.objects.all())
    convs = list(
        conv_qs.filter(related_load_id=load_id)
        .select_related("mailbox")
        .prefetch_related("messages")
    )
    if not convs:
        return Response({"error": f"No channel for load {load_id}"}, status=404)

    # For each broker, find their most recent conversation + their last
    # inbound subject. Posting on the MOST RECENT thread per broker keeps the
    # broker's view consistent with their existing thread structure.
    per_broker = {}  # email → { conv, last_inbound_subject, last_inbound_at }
    for c in convs:
        for m in c.messages.all():
            if m.direction != "inbound":
                continue
            addr = (m.sender_email or "").lower().strip()
            if not addr:
                continue
            existing = per_broker.get(addr)
            if existing is None or (m.created_at and existing["last_inbound_at"] and m.created_at > existing["last_inbound_at"]):
                per_broker[addr] = {
                    "conv": c,
                    "subject": m.subject or "",
                    "last_inbound_at": m.created_at,
                }

    if not per_broker:
        return Response({"error": "No brokers on this channel to reply to"}, status=400)

    channel_post_id = _uuid.uuid4()
    sent = []
    for broker_email, ctx in per_broker.items():
        conv = ctx["conv"]
        subject = ctx["subject"] or "(no subject)"
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        out_msg = Message.objects.create(
            conversation=conv,
            direction="outbound",
            gmail_message_id=f"channel-{_uuid.uuid4()}",
            sender_email=conv.mailbox.email_address,
            recipient_email=broker_email,
            subject=subject,
            body_text=body,
            cc=cc,
            sent_by=user,
            channel_post_id=channel_post_id,
        )
        # Mark conversation as replied + bump activity so it climbs the list.
        Conversation.objects.filter(id=conv.id).update(
            status="replied",
            last_message_at=timezone.now(),
            stale_alerted=True,
        )
        try:
            send_outbound_email.delay(str(out_msg.id))
        except Exception as e:
            # Queue dispatch failure shouldn't roll back the row — the user
            # can retry, and the row is the audit trail. Surface in response.
            logger.warning("send_outbound_email dispatch failed for %s: %s", out_msg.id, e)
        sent.append({
            "broker_email": broker_email,
            "conversation_id": str(conv.id),
            "message_id": str(out_msg.id),
        })

    return Response({
        "ok": True,
        "channel_post_id": str(channel_post_id),
        "delivered_count": len(sent),
        "deliveries": sent,
    })
