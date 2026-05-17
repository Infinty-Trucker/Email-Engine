import re
import shlex
import uuid
from datetime import date
from django.db.models import F, OuterRef, Q, Subquery
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from apps.core.error_utils import parse_error
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Conversation, Message
from .serializers import ConversationListSerializer, ConversationSerializer


# Gmail-style operators recognised in the ?q= search string. Anything else is
# treated as a free-text term and OR'd across subject/sender/recipient/cc/
# snippet/body_text/attachment-filename.
_SEARCH_OPERATORS = {
    "from", "to", "cc", "subject", "has", "is", "label", "category",
    "before", "after",
}
_OP_TOKEN_RE = re.compile(r"^(-?)([a-zA-Z]+):(.+)$")


def _parse_iso_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _apply_search(qs, raw_q):
    """Apply Gmail-like search semantics to a Conversation queryset.

    Supported operators (prefix any with `-` to negate):
        from:        sender email contains
        to:          recipient OR cc contains
        cc:          cc contains
        subject:     subject contains
        has:attachment
        is:unread | is:read | is:starred | is:unstarred
        is:open | is:closed | is:replied | is:pending
        label:NAME   (alias: category:NAME) — matches Conversation.category
        before:YYYY-MM-DD / after:YYYY-MM-DD on last_message_at

    Free terms (no `op:`) match across the message body, subject, addresses,
    cc, snippet, and attachment filename. Quote phrases with double quotes
    to keep spaces (`subject:"load offer"`).
    """
    if not raw_q or not raw_q.strip():
        return qs

    try:
        tokens = shlex.split(raw_q)
    except ValueError:
        # Unbalanced quotes — fall back to a naive split so the user still
        # gets results instead of a 500.
        tokens = raw_q.split()

    free_terms = []
    op_q = Q()
    needs_distinct = False

    for tok in tokens:
        m = _OP_TOKEN_RE.match(tok)
        if not m:
            free_terms.append(tok)
            continue
        neg, op, val = m.groups()
        op = op.lower()
        if op not in _SEARCH_OPERATORS or not val:
            free_terms.append(tok)
            continue

        sub = None
        if op == "from":
            sub = Q(messages__sender_email__icontains=val)
            needs_distinct = True
        elif op == "to":
            sub = Q(messages__recipient_email__icontains=val) | Q(messages__cc__icontains=val)
            needs_distinct = True
        elif op == "cc":
            sub = Q(messages__cc__icontains=val)
            needs_distinct = True
        elif op == "subject":
            sub = Q(messages__subject__icontains=val)
            needs_distinct = True
        elif op == "has":
            if val.lower() in ("attachment", "attachments"):
                sub = Q(messages__attachments__isnull=False)
                needs_distinct = True
        elif op == "is":
            v = val.lower()
            if v == "unread":
                sub = Q(read_at__isnull=True) | Q(last_message_at__gt=F("read_at"))
            elif v == "read":
                sub = Q(read_at__isnull=False, last_message_at__lte=F("read_at"))
            elif v == "starred":
                sub = Q(is_starred=True)
            elif v in ("unstarred", "notstarred"):
                sub = Q(is_starred=False)
            elif v in ("open", "closed", "replied"):
                sub = Q(status=v)
            elif v in ("pending", "pending_approval"):
                sub = Q(status="pending_approval")
        elif op in ("label", "category"):
            sub = Q(category__iexact=val)
        elif op == "before":
            d = _parse_iso_date(val)
            if d:
                sub = Q(last_message_at__lt=d)
        elif op == "after":
            d = _parse_iso_date(val)
            if d:
                sub = Q(last_message_at__gte=d)

        if sub is None:
            # Unknown sub-value (e.g. `has:foo`) — degrade to free text so the
            # user still gets a hit instead of an empty list.
            free_terms.append(tok)
            continue
        if neg == "-":
            sub = ~sub
        op_q &= sub

    qs = qs.filter(op_q)

    for term in free_terms:
        qs = qs.filter(
            Q(messages__subject__icontains=term)
            | Q(messages__sender_email__icontains=term)
            | Q(messages__recipient_email__icontains=term)
            | Q(messages__cc__icontains=term)
            | Q(messages__snippet__icontains=term)
            | Q(messages__body_text__icontains=term)
            | Q(messages__attachments__filename__icontains=term)
        )
        needs_distinct = True

    if needs_distinct:
        qs = qs.distinct()
    return qs


class ConversationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ConversationSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None  # return all conversations, frontend handles display

    def get_serializer_class(self):
        # List uses the slim serializer (one Prefetched preview row per
        # conversation, no message bodies). Retrieve and the @action endpoints
        # keep the full serializer so the thread view still renders bodies +
        # attachments + classification.
        if self.action == "list":
            return ConversationListSerializer
        return ConversationSerializer

    def get_queryset(self):
        from apps.users.tms_auth import has_tms_permission
        user = self.request.user
        # Defense-in-depth: TMS-authenticated requests must hold email.view
        # (or be a Django superuser). Standalone DOS sessions return True
        # from the helper and fall through to the existing M2M gate.
        if not has_tms_permission(user, "email.view"):
            return Conversation.objects.none()

        qs = Conversation.objects.select_related("mailbox__company")

        # List path serves entirely from denormalized columns on Conversation
        # (preview_sender / preview_subject / preview_snippet) — no Prefetch,
        # no per-row Python walk. Detail / action paths still need the full
        # message chain.
        if self.action != "list":
            qs = qs.prefetch_related("messages")
        else:
            # Belt-and-suspenders fallback for rows that pre-date the
            # denormalization (preview_* columns still empty until the
            # backfill_conversation_preview command runs). Correlated subquery
            # against the first message keeps the list endpoint at O(1)
            # queries instead of re-introducing a Prefetch — the serializer
            # prefers the denormalized columns and only reads these when they
            # are blank.
            first_msg = Message.objects.filter(
                conversation=OuterRef("pk"),
            ).order_by("created_at")
            qs = qs.annotate(
                _fallback_sender=Subquery(first_msg.values("sender_email")[:1]),
                _fallback_subject=Subquery(first_msg.values("subject")[:1]),
                _fallback_snippet=Subquery(first_msg.values("snippet")[:1]),
            )

        # Tenant scoping. X-Tenant from the consolidated UI is the canonical
        # tenant authorization signal: TMS-Backend (the IDP) has already
        # confirmed the user is acting on MC=<X-Tenant>, so DOS scopes purely
        # by Conversation.mc_number (denormalized at ingest from
        # mailbox.company.mc_number) and ignores the legacy assigned_companies
        # M2M. Falls back to ?mc= for direct testing. Without X-Tenant
        # (standalone DOS login), keep the assigned_companies M2M as the gate.
        # Hitting the denormalized column lets the composite
        # (mc_number, last_message_at DESC) index serve the canonical inbox
        # query in a single range scan — no JOIN needed at filter time.
        tenant_mc = (
            self.request.headers.get("X-Tenant")
            or self.request.query_params.get("mc")
        )
        if tenant_mc:
            qs = qs.filter(mc_number=tenant_mc)
        elif user.role not in ("admin", "manager"):
            company_ids = user.assigned_companies.values_list("id", flat=True)
            if company_ids:
                qs = qs.filter(mailbox__company_id__in=company_ids)

        # Category filter based on role
        if user.visible_categories and user.role not in ("admin", "manager"):
            qs = qs.filter(category__in=user.visible_categories + [""])

        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        company = self.request.query_params.get("company")
        if company:
            qs = qs.filter(mailbox__company_id=company)

        raw_q = self.request.query_params.get("q") or self.request.query_params.get("search")
        qs = _apply_search(qs, raw_q)

        qs = qs.order_by("-last_message_at")
        # Hard cap to prevent runaway list responses crashing the browser.
        # Only applies to list — retrieve and detail-actions need to be able to
        # call .filter(pk=...) on the queryset, which raises TypeError on a
        # sliced queryset (DRF's get_object_or_404 catches that and turns it
        # into a 404, so detail fetches were silently 404ing for every thread).
        if self.action == "list":
            try:
                limit = min(int(self.request.query_params.get("limit", 200)), 500)
            except (TypeError, ValueError):
                limit = 200
            qs = qs[:limit]
        return qs

    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        from apps.users.tms_auth import has_tms_permission
        if not has_tms_permission(request.user, "email.send"):
            return Response({"error": "Missing required permission: email.send"}, status=403)
        conv = self.get_object()
        body        = request.data.get("body", "").strip()
        body_html   = request.data.get("body_html", "").strip()
        instruction = request.data.get("instruction", "")
        if not body:
            return Response({"error": "body required"}, status=400)

        category = conv.category or ""
        needs_approval = (
            category in ("SAFETY", "AUDIT", "CLAIMS")
            and not request.user.can_approve
        )

        cc = request.data.get("cc", "").strip()
        msg = Message.objects.create(
            conversation=conv,
            direction="outbound",
            gmail_message_id=f"pending-{uuid.uuid4()}",
            sender_email=conv.mailbox.email_address,
            recipient_email=conv.messages.filter(direction="inbound").last().sender_email if conv.messages.filter(direction="inbound").exists() else "",
            subject=f"Re: {conv.messages.first().subject if conv.messages.exists() else ''}",
            body_text=body,
            body_html=body_html,
            cc=cc,
            sent_by=request.user,
        )

        # Save uploaded attachments
        from .models import Attachment
        for f in request.FILES.getlist("attachments"):
            Attachment.objects.create(
                message=msg,
                filename=f.name,
                mime_type=f.content_type or "application/octet-stream",
                size=f.size,
                file=f,
                downloaded=True,
            )

        if needs_approval:
            from apps.approvals.models import Approval
            approval = Approval.objects.create(
                conversation=conv, message=msg, requested_by=request.user
            )
            conv.status = "pending_approval"
            conv.save(update_fields=["status"])
            try:
                from apps.notifications.tasks import send_approval_request
                send_approval_request.delay(str(approval.id))
            except Exception:
                pass
            return Response({"ok": True, "status": "pending_approval", "approval_id": str(approval.id)})

        # Auto-send
        from apps.conversations.tasks import send_outbound_email
        send_outbound_email.delay(str(msg.id))
        conv.status = "replied"
        conv.last_message_at = timezone.now()
        conv.save(update_fields=["status", "last_message_at"])
        return Response({"ok": True, "status": "sent", "message_id": str(msg.id)})

    @action(detail=True, methods=["post"])
    def draft(self, request, pk=None):
        conv        = self.get_object()
        instruction = request.data.get("instruction", "")
        last_msg    = conv.messages.filter(direction="inbound").last()
        if not last_msg:
            return Response({"error": "No inbound message to reply to"}, status=400)
        try:
            from apps.classifier.engine import generate_draft
            body = generate_draft(
                from_email=last_msg.sender_email,
                subject=last_msg.subject,
                snippet=last_msg.snippet,
                company_name=conv.mailbox.company.name,
                mc_number=conv.mailbox.company.mc_number,
                instruction=instruction,
            )
            return Response({"draft": body})
        except Exception as e:
            return Response({"error": parse_error(e, "generating draft reply")}, status=500)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        conv = self.get_object()
        conv.status = "closed"
        conv.save(update_fields=["status"])
        return Response({"ok": True})

    @action(detail=False, methods=["post"])
    def compose(self, request):
        """Send a brand new email (not a reply) from a configured mailbox."""
        from apps.settings.models import MailboxSettings
        from apps.users.tms_auth import has_tms_permission
        if not has_tms_permission(request.user, "email.send"):
            return Response({"error": "Missing required permission: email.send"}, status=403)
        to      = request.data.get("to", "").strip()
        cc      = request.data.get("cc", "").strip()
        subject = request.data.get("subject", "").strip()
        body    = request.data.get("body", "").strip()
        mailbox_id = request.data.get("mailbox_id", "").strip()

        if not to:      return Response({"error": "Recipient (to) is required"}, status=400)
        if not subject: return Response({"error": "Subject is required"}, status=400)
        if not body:    return Response({"error": "Body is required"}, status=400)

        # Determine which mailboxes the user is allowed to send from.
        # X-Tenant from the consolidated UI is authoritative: TMS confirms the
        # user is acting on MC=<X-Tenant>, so any active mailbox for that
        # company is fair game. Falls back to assigned_companies for the
        # standalone DOS login (no X-Tenant header).
        tenant_mc = (request.headers.get("X-Tenant") or "").strip()
        is_admin = request.user.role in ("admin", "manager")
        allowed_qs = MailboxSettings.objects.filter(is_active=True).select_related(
            "service_account", "oauth_credential", "company"
        )
        if tenant_mc:
            allowed_qs = allowed_qs.filter(company__mc_number=tenant_mc)
        elif not is_admin:
            allowed_company_ids = list(request.user.assigned_companies.values_list("id", flat=True))
            allowed_qs = allowed_qs.filter(company_id__in=allowed_company_ids)

        try:
            if mailbox_id:
                mb_settings = allowed_qs.get(id=mailbox_id)
            else:
                # No explicit mailbox — pick the first one the user can use
                mb_settings = next((m for m in allowed_qs if m.is_authorized), None)
            if not mb_settings:
                if tenant_mc:
                    err = (
                        f"No connected mailbox configured for MC {tenant_mc}. "
                        "Ask your admin to set one up under Admin → Credentials → Mailboxes."
                    )
                elif is_admin:
                    err = "No connected mailbox available."
                else:
                    err = (
                        "You are not assigned to any company with a connected mailbox. "
                        "Ask your admin to assign you to a company."
                    )
                return Response({"error": err}, status=400)
            if not mb_settings.is_authorized:
                return Response({"error": f"Mailbox {mb_settings.email_address} is not authorized — reconnect it in Admin → Credentials."}, status=400)
        except MailboxSettings.DoesNotExist:
            return Response({"error": "You don't have permission to send from that mailbox."}, status=403)

        # Get or create legacy mailbox
        from apps.mailboxes.tasks import _get_or_create_legacy_mailbox
        legacy_mb = _get_or_create_legacy_mailbox(mb_settings)

        # Create a new conversation thread
        import uuid as _uuid
        conv = Conversation.objects.create(
            mailbox=legacy_mb,
            gmail_thread_id=f"compose-{_uuid.uuid4()}",
            status="replied",
            last_message_at=timezone.now(),
        )
        msg = Message.objects.create(
            conversation=conv,
            direction="outbound",
            gmail_message_id=f"pending-{_uuid.uuid4()}",
            sender_email=mb_settings.email_address,
            recipient_email=to,
            subject=subject,
            body_text=body,
            body_html=request.data.get("body_html", "").strip(),
            cc=cc,
            sent_by=request.user,
        )

        # Save uploaded attachments
        from .models import Attachment
        for f in request.FILES.getlist("attachments"):
            Attachment.objects.create(
                message=msg,
                filename=f.name,
                mime_type=f.content_type or "application/octet-stream",
                size=f.size,
                file=f,
                downloaded=True,
            )

        # Send async
        from apps.conversations.tasks import send_outbound_email
        send_outbound_email.delay(str(msg.id))
        return Response({"ok": True, "message_id": str(msg.id), "conversation_id": str(conv.id)})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        conv = self.get_object()
        conv.read_at = timezone.now()
        conv.save(update_fields=["read_at"])
        return Response({"ok": True, "read_at": conv.read_at})

    @action(detail=True, methods=["post"])
    def unread(self, request, pk=None):
        conv = self.get_object()
        conv.read_at = None
        conv.save(update_fields=["read_at"])
        return Response({"ok": True})

    @action(detail=True, methods=["post"])
    def star(self, request, pk=None):
        conv = self.get_object()
        conv.is_starred = True
        conv.save(update_fields=["is_starred"])
        return Response({"ok": True, "is_starred": True})

    @action(detail=True, methods=["post"])
    def unstar(self, request, pk=None):
        conv = self.get_object()
        conv.is_starred = False
        conv.save(update_fields=["is_starred"])
        return Response({"ok": True, "is_starred": False})

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        conv    = self.get_object()
        user_id = request.data.get("user_id")
        from apps.users.models import User
        try:
            user = User.objects.get(id=user_id)
            conv.assigned_dispatcher = user
            conv.save(update_fields=["assigned_dispatcher"])
            return Response({"ok": True})
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)
