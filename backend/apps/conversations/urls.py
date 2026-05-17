from rest_framework.routers import DefaultRouter
from .views import ConversationViewSet

router = DefaultRouter()
router.register("", ConversationViewSet, basename="conversations")
urlpatterns = router.urls

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


urlpatterns += [
    path("attachments/<uuid:att_id>/download/", attachment_download),
    path("attachments/<uuid:att_id>/import-as-load/", import_as_load),
]
