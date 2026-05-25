from rest_framework.routers import DefaultRouter
from .views import ConversationViewSet

router = DefaultRouter()
router.register("", ConversationViewSet, basename="conversations")
# NOTE: explicit `path(...)` entries are prepended below so they win over the
# router's `<pk>/` detail route. Without that, `/api/conversations/carriers/`
# would be matched as a UUID pk lookup, never reaching `carriers_list`.

from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.http import FileResponse, Http404


@api_view(["GET"])
def attachment_download(request, att_id):
    """Stream an attachment directly from Gmail — no local storage."""
    from .models import Attachment
    import base64
    try:
        att = Attachment.objects.select_related(
            "message__conversation__mailbox"
        ).get(id=att_id)
    except (Attachment.DoesNotExist, Exception):
        raise Http404

    if not att.gmail_attachment_id or not att.message:
        raise Http404

    try:
        from apps.settings.models import MailboxSettings
        from apps.settings.gmail_oauth import get_gmail_service

        mailbox_email = att.message.conversation.mailbox.email_address
        mb_settings = MailboxSettings.objects.select_related(
            "service_account", "oauth_credential"
        ).filter(email_address=mailbox_email, is_active=True).first()

        if not mb_settings:
            return Response({"error": f"Mailbox {mailbox_email} not configured in MailboxSettings"}, status=404)

        # Watch status / OAuth credential checks — fail fast with a clear
        # message instead of letting get_gmail_service throw a vague error.
        if mb_settings.watch_status == "error":
            return Response(
                {"error": f"Mailbox {mailbox_email} watch is in error state — reconnect OAuth in Admin → Credentials. Detail: {getattr(mb_settings, 'watch_error', '') or 'unknown'}"},
                status=502,
            )
        cred = mb_settings.oauth_credential
        if cred and not cred.is_valid:
            return Response(
                {"error": f"OAuth credential for {mailbox_email} is invalid — reconnect in Admin → Credentials"},
                status=502,
            )

        svc = get_gmail_service(mb_settings)
        att_data = svc.users().messages().attachments().get(
            userId="me",
            messageId=att.message.gmail_message_id,
            id=att.gmail_attachment_id,
        ).execute()

        file_bytes = base64.urlsafe_b64decode(att_data.get("data", "") + "==")
        if not file_bytes:
            return Response(
                {"error": f"Gmail returned empty body for messageId={att.message.gmail_message_id} attachmentId={att.gmail_attachment_id}"},
                status=502,
            )

        from django.http import HttpResponse
        mime = (att.mime_type or "application/octet-stream").lower()
        # Inline disposition for browser-previewable types (PDF, images, plain text)
        # so iframe / <img> can render them without forcing a download.
        # Caller can still force download via ?download=1 query param.
        force_download = request.GET.get("download") == "1"
        previewable = (
            mime == "application/pdf"
            or mime.startswith("image/")
            or mime.startswith("text/")
        )
        disposition = "attachment" if (force_download or not previewable) else "inline"
        response = HttpResponse(file_bytes, content_type=att.mime_type or "application/octet-stream")
        response["Content-Disposition"] = f'{disposition}; filename="{att.filename}"'
        response["Content-Length"] = len(file_bytes)
        # Allow iframe embedding from same origin only
        response["X-Content-Type-Options"] = "nosniff"
        return response

    except Exception as e:
        msg = str(e)
        if "invalid_grant" in msg or "revoked" in msg or "unauthorized_client" in msg:
            return Response(
                {"error": f"Gmail OAuth dead for this mailbox — reconnect it. Detail: {msg[:300]}"},
                status=502,
            )
        # Gmail HttpError comes back like "<HttpError 404 when requesting ...>"
        if "HttpError 404" in msg:
            return Response(
                {"error": f"Gmail says message/attachment not found (likely deleted or trashed). messageId={getattr(att.message, 'gmail_message_id', '?')} attachmentId={att.gmail_attachment_id}"},
                status=404,
            )
        return Response(
            {"error": f"Could not fetch attachment: {type(e).__name__}: {msg[:500]}"},
            status=500,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_as_load(request, att_id):
    """Forward a Gmail PDF attachment to the TMS rate-confirmation parser.

    The dispatcher's X-Session-Token is replayed to TMS, so the eventual load
    is created on their behalf. X-Tenant is the mailbox's company.mc_number.
    Returns the cache key the TMS Add-Load wizard polls to pick up the parsed
    result.
    """
    from .models import Attachment
    import base64, os, uuid as _uuid
    import requests

    try:
        att = Attachment.objects.select_related(
            "message__conversation__mailbox__company"
        ).get(id=att_id)
    except Attachment.DoesNotExist:
        return Response({"error": f"Attachment {att_id} not found"}, status=404)

    # Some Gmail messages report PDFs as application/octet-stream (or empty
    # mime_type) but the filename still ends in .pdf. Trust either signal,
    # matching the UI's import-button visibility logic.
    mime = (att.mime_type or "").lower()
    looks_like_pdf = (
        mime == "application/pdf"
        or mime == "application/x-pdf"
        or (att.filename or "").lower().endswith(".pdf")
    )
    if not looks_like_pdf:
        return Response(
            {"error": f"Attachment is {att.mime_type or 'unknown'}, expected application/pdf"},
            status=400,
        )

    if not att.message:
        return Response(
            {"error": "Attachment is not linked to a message"}, status=404
        )

    company = att.message.conversation.mailbox.company
    mc_number = company.mc_number
    if not mc_number:
        return Response({"error": "Mailbox company has no MC number set"}, status=400)

    # Permission: X-Tenant (from the consolidated UI / TMS IDP) is the
    # authoritative tenant signal. If it's present, it must match the
    # mailbox's company; otherwise fall back to the legacy assigned_companies
    # M2M for the standalone DOS login.
    user = request.user
    tenant_mc = (request.headers.get("X-Tenant") or "").strip()
    if tenant_mc:
        if tenant_mc != mc_number:
            return Response({"error": "Forbidden for this company"}, status=403)
        # Reading attachments + sending them off as loads is a view-side
        # action — gated by email.view in the BFF, mirrored here.
        from apps.users.tms_auth import has_tms_permission
        if not has_tms_permission(user, "email.view"):
            return Response({"error": "Missing required permission: email.view"}, status=403)
    elif user.role not in ("admin", "manager"):
        if not user.assigned_companies.filter(id=company.id).exists():
            return Response({"error": "Forbidden for this company"}, status=403)

    if not att.gmail_attachment_id:
        return Response(
            {"error": "Attachment has no gmail_attachment_id — cannot fetch from Gmail"},
            status=404,
        )

    # Pull the binary from Gmail (mirrors attachment_download)
    try:
        from apps.settings.models import MailboxSettings
        from apps.settings.gmail_oauth import get_gmail_service

        mailbox_email = att.message.conversation.mailbox.email_address
        mb_settings = MailboxSettings.objects.select_related(
            "service_account", "oauth_credential"
        ).filter(email_address=mailbox_email, is_active=True).first()
        if not mb_settings:
            return Response({"error": "Mailbox not configured"}, status=404)

        svc = get_gmail_service(mb_settings)
        att_data = svc.users().messages().attachments().get(
            userId="me",
            messageId=att.message.gmail_message_id,
            id=att.gmail_attachment_id,
        ).execute()
        file_bytes = base64.urlsafe_b64decode(att_data.get("data", "") + "==")
    except Exception as e:
        return Response({"error": f"Could not fetch attachment from Gmail: {e}"}, status=502)

    # Forward to TMS parser. The wizard polls /common/api/v1/parsed-data/<key>/.
    tms_base = os.environ.get("TMS_BACKEND_URL", "http://localhost:8000").rstrip("/")
    parse_url = f"{tms_base}/dispatch-center/api/v1/loads/parse-rate-confirmation-into-load-info/"
    key = str(_uuid.uuid4())
    session_token = request.auth  # set by TMSSessionTokenAuthentication

    # Email context — gives the TMS parser fallback signal for broker contact
    # info that often only lives in the email envelope, not the PDF body.
    msg = att.message
    sender = msg.sender_email or ""
    # `From: "Nick Rooney" <nick.rooney@allenlund.com>` — split the display
    # name out of the raw header if it's there.
    from_name = ""
    from_email = sender
    if "<" in sender and ">" in sender:
        from_name = sender.split("<", 1)[0].strip().strip('"')
        from_email = sender.split("<", 1)[1].rsplit(">", 1)[0].strip()
    body_excerpt = (msg.body_text or msg.snippet or "")[:2000]

    try:
        tms_resp = requests.post(
            parse_url,
            headers={
                "X-Session-Token": session_token or "",
                "X-Tenant": mc_number,
            },
            files=[("files", (att.filename, file_bytes, "application/pdf"))],
            data={
                "key": key,
                "email_subject":    msg.subject or "",
                "email_from_name":  from_name,
                "email_from_email": from_email,
                "email_body":       body_excerpt,
            },
            timeout=15,
        )
    except requests.RequestException as e:
        return Response({"error": f"TMS parser unreachable: {e}"}, status=502)

    if tms_resp.status_code >= 400:
        return Response(
            {"error": f"TMS parser returned {tms_resp.status_code}", "body": tms_resp.text[:500]},
            status=502,
        )

    return Response({
        "key": key,
        "mc_number": mc_number,
        "company_name": company.name,
        "filename": att.filename,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def carriers_list(request):
    """List the external email domains the tenant has corresponded with.

    Used by the inbox sidebar to group threads by carrier/broker. Domains
    come from the denormalized `preview_sender` column on Conversation
    (always the external party — set from the first inbound message), so
    this is a single GROUP BY on an indexed-friendly column.
    """
    from .models import Conversation
    from apps.users.tms_auth import has_tms_permission
    from django.db.models import Count, Max
    from collections import defaultdict

    user = request.user
    if not has_tms_permission(user, "email.view"):
        return Response({"error": "Missing required permission: email.view"}, status=403)

    qs = Conversation.objects.all()

    # Tenant scope — mirrors ConversationViewSet.get_queryset
    tenant_mc = request.headers.get("X-Tenant") or request.query_params.get("mc")
    if tenant_mc:
        qs = qs.filter(mc_number=tenant_mc)
    elif user.role not in ("admin", "manager"):
        company_ids = list(user.assigned_companies.values_list("id", flat=True))
        if company_ids:
            qs = qs.filter(mailbox__company_id__in=company_ids)
        else:
            return Response({"results": []})

    # Pull just the columns we need. Domain extraction is done in Python
    # because Postgres' SUBSTRING(FROM POSITION) doesn't play nicely with
    # the Django ORM and the per-tenant row count is bounded (<= 500-ish).
    rows = qs.exclude(preview_sender="").values_list(
        "preview_sender", "last_message_at", "preview_subject"
    )

    groups = defaultdict(lambda: {
        "domain": "",
        "count": 0,
        "last_message_at": None,
        "sample_sender": "",
        "sample_subject": "",
    })
    for sender, last_at, subject in rows:
        addr = (sender or "").lower().strip()
        if "@" not in addr:
            continue
        domain = addr.rsplit("@", 1)[1]
        if not domain:
            continue
        g = groups[domain]
        g["domain"] = domain
        g["count"] += 1
        if last_at and (g["last_message_at"] is None or last_at > g["last_message_at"]):
            g["last_message_at"] = last_at
            g["sample_sender"] = sender
            g["sample_subject"] = subject or ""

    out = sorted(
        groups.values(),
        key=lambda g: g["last_message_at"] or 0,
        reverse=True,
    )
    return Response({"results": out})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def carrier_messages(request):
    """Flat chronological message feed for one carrier (sender domain).

    Used by the Slack-style "carrier channel" view — a single timeline of every
    message we've exchanged with anyone at `@<domain>`, across every thread.
    Tenant-scoped via X-Tenant the same way the conversations list is.

    Filtered by Message.sender_email's domain for inbound + Message
    .recipient_email's domain for outbound, so outgoing replies appear in the
    same channel even if the broker never wrote back.
    """
    from .models import Conversation, Message
    from .serializers import AttachmentSerializer
    from apps.users.tms_auth import has_tms_permission
    from django.db.models import Q

    user = request.user
    if not has_tms_permission(user, "email.view"):
        return Response({"error": "Missing required permission: email.view"}, status=403)

    domain = (request.query_params.get("carrier") or "").strip().lstrip("@").lower()
    load = (request.query_params.get("load") or "").strip()
    if not domain and not load:
        return Response({"error": "carrier or load query param required"}, status=400)
    try:
        limit = min(int(request.query_params.get("limit", 200)), 500)
    except (TypeError, ValueError):
        limit = 200

    # Tenant scope mirrors ConversationViewSet — X-Tenant from the IDP wins,
    # M2M assigned_companies is the standalone-DOS fallback.
    tenant_mc = request.headers.get("X-Tenant") or request.query_params.get("mc")
    conv_qs = Conversation.objects.all()
    if tenant_mc:
        conv_qs = conv_qs.filter(mc_number=tenant_mc)
    elif user.role not in ("admin", "manager"):
        company_ids = list(user.assigned_companies.values_list("id", flat=True))
        if company_ids:
            conv_qs = conv_qs.filter(mailbox__company_id__in=company_ids)
        else:
            return Response({"results": []})

    # Apply the load filter on Conversation first — this scopes the message
    # set to one channel ("every email tied to load #1234") and is what the
    # LOAD CHANNELS view uses. Carriers slice by domain on Message side below.
    if load:
        conv_qs = conv_qs.filter(related_load_id=load)

    msgs_qs = (
        Message.objects
        .filter(conversation__in=conv_qs)
        .select_related("conversation")
        .prefetch_related("attachments")
    )
    if domain:
        # Match either inbound from the domain OR outbound to the domain so
        # both sides of the exchange land in the channel. iendswith works on
        # the full address ("@phoenix.com") so we don't catch
        # phoenix.com.spammer.io.
        needle = f"@{domain}"
        msgs_qs = msgs_qs.filter(
            Q(direction="inbound", sender_email__iendswith=needle) |
            Q(direction="outbound", recipient_email__iendswith=needle)
        )
    msgs = msgs_qs.order_by("-created_at")[:limit]

    out = []
    for m in msgs:
        conv = m.conversation
        out.append({
            "id": str(m.id),
            "conversation_id": str(conv.id),
            "conversation_subject": conv.preview_subject or m.subject or "",
            "related_load_id": conv.related_load_id or "",
            "direction": m.direction,
            "sender_email": m.sender_email or "",
            "recipient_email": m.recipient_email or "",
            "cc": m.cc or "",
            "subject": m.subject or "",
            "snippet": m.snippet or "",
            "body_text": (m.body_text or "")[:2000],
            "channel_post_id": str(m.channel_post_id) if m.channel_post_id else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "attachments": AttachmentSerializer(m.attachments.all(), many=True).data,
        })
    # Reverse to oldest-first so the UI can append-render like a chat log.
    out.reverse()
    return Response({"count": len(out), "carrier": domain, "load": load, "results": out})


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def auto_monitor(request, conv_id):
    """Toggle the per-thread auto-monitor flag.

    POST enables; DELETE disables. When enabled, the
    `check_monitored_followups` beat task watches the thread for outbound
    silence and posts an AI-drafted follow-up to Slack for human approval.
    """
    from .models import Conversation
    from apps.users.tms_auth import has_tms_permission

    user = request.user
    if not has_tms_permission(user, "email.view"):
        return Response({"error": "Missing required permission: email.view"}, status=403)

    try:
        conv = Conversation.objects.select_related("mailbox__company").get(id=conv_id)
    except Conversation.DoesNotExist:
        return Response({"error": "Conversation not found"}, status=404)

    tenant_mc = (request.headers.get("X-Tenant") or "").strip()
    if tenant_mc and tenant_mc != (conv.mc_number or ""):
        return Response({"error": "Forbidden for this tenant"}, status=403)

    enabled = request.method == "POST"
    update_fields = ["auto_monitor", "updated_at"]
    conv.auto_monitor = enabled
    # Clear the throttle on disable so a future re-enable starts fresh.
    if not enabled:
        conv.last_followup_alert_at = None
        update_fields.append("last_followup_alert_at")
    conv.save(update_fields=update_fields)
    return Response({"ok": True, "auto_monitor": enabled})


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def link_load(request, conv_id):
    """Attach (POST { load_id }) or detach (DELETE) a TMS load from a thread.

    Stored as opaque string on Conversation.related_load_id — TMS owns the
    load record. Inbox UI uses this to surface "this thread is for load #123"
    and to drive the per-load conversation view.
    """
    from .models import Conversation
    from apps.users.tms_auth import has_tms_permission

    user = request.user
    if not has_tms_permission(user, "email.view"):
        return Response({"error": "Missing required permission: email.view"}, status=403)

    try:
        conv = Conversation.objects.select_related("mailbox__company").get(id=conv_id)
    except Conversation.DoesNotExist:
        return Response({"error": "Conversation not found"}, status=404)

    # Tenant gate — same X-Tenant -> mc_number check used by the viewset.
    tenant_mc = (request.headers.get("X-Tenant") or "").strip()
    if tenant_mc and tenant_mc != (conv.mc_number or ""):
        return Response({"error": "Forbidden for this tenant"}, status=403)

    if request.method == "DELETE":
        if conv.related_load_id:
            conv.related_load_id = ""
            conv.save(update_fields=["related_load_id", "updated_at"])
        return Response({"ok": True, "related_load_id": ""})

    load_id = str(request.data.get("load_id") or "").strip()
    if not load_id:
        return Response({"error": "load_id required"}, status=400)
    if len(load_id) > 64:
        return Response({"error": "load_id too long (max 64 chars)"}, status=400)

    conv.related_load_id = load_id
    conv.save(update_fields=["related_load_id", "updated_at"])
    return Response({"ok": True, "related_load_id": load_id})


from . import load_channels as _load_channels

urlpatterns = [
    path("attachments/<uuid:att_id>/download/", attachment_download),
    path("attachments/<uuid:att_id>/import-as-load/", import_as_load),
    path("carriers/", carriers_list),
    path("messages/", carrier_messages),
    # Load-channel endpoints — Slack-style chat surface keyed on the
    # TMS load id. Mounted under /api/conversations/ because that's the
    # existing tenant-scoped namespace; the BFF wraps them as
    # /api/email/load-channels/...
    path("load-channels/", _load_channels.list_channels),
    path("load-channels/<str:load_id>/", _load_channels.channel_detail),
    path("load-channels/<str:load_id>/messages/", _load_channels.post_channel_message),
    path("<uuid:conv_id>/link-load/", link_load),
    path("<uuid:conv_id>/auto-monitor/", auto_monitor),
] + router.urls
