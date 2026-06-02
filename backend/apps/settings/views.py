"""
apps/settings/views.py

REST API endpoints for Admin UI credential management.
All endpoints require authentication. Gmail/Slack write ops require admin/manager role.
"""
import json
import logging
from datetime import datetime, timezone
from apps.core.error_utils import parse_error, log_and_respond

from django.utils import timezone as dj_tz
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.response import Response

from .models import SlackSettings, GoogleServiceAccount, MailboxSettings

logger = logging.getLogger(__name__)


def require_admin(request):
    # Superusers bypass the role gate entirely (full cross-tenant admin access).
    if getattr(request.user, "is_superuser", False):
        return None
    if request.user.role not in ("admin", "manager"):
        return Response({"error": "Admin or manager role required"}, status=403)


# ── Slack ─────────────────────────────────────────────────────────────────────

@api_view(["GET"])
def slack_get(request):
    """Return current Slack configuration (token masked)."""
    s = SlackSettings.get()
    return Response({
        "bot_token_set":    s.bot_token_set,
        "bot_token_preview": s.bot_token_preview,
        "channels": {
            "safety":     {"id": s.channel_safety,     "name": s.channel_safety_name},
            "approvals":  {"id": s.channel_approvals,  "name": s.channel_approvals_name},
            "compliance": {"id": s.channel_compliance, "name": s.channel_compliance_name},
            "system":     {"id": s.channel_system,     "name": s.channel_system_name},
        },
        "updated_at": s.updated_at,
    })


@api_view(["POST"])
def slack_save_token(request):
    """Save (or update) the Slack bot token."""
    err = require_admin(request)
    if err: return err
    token = request.data.get("token", "").strip()
    if not token.startswith("xoxb-"):
        return Response({"error": "Invalid token format — must start with xoxb-"}, status=400)
    s = SlackSettings.get()
    s.bot_token = token
    s.save()
    return Response({"ok": True, "preview": s.bot_token_preview})


@api_view(["POST"])
def slack_save_channels(request):
    """Save all Slack channel IDs and names."""
    err = require_admin(request)
    if err: return err
    s = SlackSettings.get()
    channels = request.data.get("channels", {})
    s.channel_safety      = channels.get("safety",     {}).get("id",   s.channel_safety)
    s.channel_safety_name = channels.get("safety",     {}).get("name", s.channel_safety_name)
    s.channel_approvals      = channels.get("approvals",  {}).get("id",   s.channel_approvals)
    s.channel_approvals_name = channels.get("approvals",  {}).get("name", s.channel_approvals_name)
    s.channel_compliance      = channels.get("compliance",{}).get("id",   s.channel_compliance)
    s.channel_compliance_name = channels.get("compliance",{}).get("name", s.channel_compliance_name)
    s.channel_system      = channels.get("system",     {}).get("id",   s.channel_system)
    s.channel_system_name = channels.get("system",     {}).get("name", s.channel_system_name)
    s.save()
    return Response({"ok": True})


@api_view(["POST"])
def slack_test_connection(request):
    """Test the saved Slack bot token via auth.test."""
    s = SlackSettings.get()
    token = s.bot_token
    if not token:
        return Response({"ok": False, "error": "No bot token saved"}, status=400)
    try:
        from slack_sdk import WebClient
        client = WebClient(token=token)
        result = client.auth_test()
        return Response({"ok": True, "team": result.get("team"), "bot": result.get("user"), "team_id": result.get("team_id")})
    except Exception as e:
        return log_and_respond(e, "testing Slack connection", logger)


@api_view(["GET"])
def slack_list_channels(request):
    """
    List all channels available for company assignment.
    Merges:
      1. Auto-discovered channels from Slack API (bot is a member of these)
      2. Admin-registered channel names (may or may not be reachable)
    """
    from .models import SlackChannelRegistry

    by_name = {}

    # Auto-discovered
    s = SlackSettings.get()
    token = s.bot_token
    if token:
        try:
            from slack_sdk import WebClient
            client = WebClient(token=token)
            cursor = None
            while True:
                resp = client.conversations_list(
                    types="public_channel,private_channel",
                    limit=200,
                    cursor=cursor or "",
                    exclude_archived=True,
                )
                for ch in resp.get("channels", []):
                    by_name[ch["name"]] = {
                        "id":         ch["id"],
                        "name":       ch["name"],
                        "is_private": ch.get("is_private", False),
                        "source":     "auto",
                    }
                cursor = resp.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        except Exception as e:
            logger.warning("slack_list_channels auto-discovery failed: %s", e)

    # Admin-registered — override or add
    for reg in SlackChannelRegistry.objects.all():
        existing = by_name.get(reg.name)
        by_name[reg.name] = {
            "id":         existing["id"] if existing and existing.get("id") else reg.channel_id,
            "name":       reg.name,
            "is_private": existing["is_private"] if existing else reg.is_private,
            "source":     "manual" if not existing else "both",
            "description": reg.description,
        }

    channels = sorted(by_name.values(), key=lambda c: c["name"])
    return Response({"ok": True, "channels": channels})


@api_view(["GET", "POST"])
def slack_channels_registry(request):
    """GET: list admin-registered channels. POST: add a new channel."""
    from .models import SlackChannelRegistry
    if request.method == "GET":
        return Response([{
            "id": str(c.id),
            "name": c.name,
            "channel_id": c.channel_id,
            "is_private": c.is_private,
            "description": c.description,
        } for c in SlackChannelRegistry.objects.all()])

    err = require_admin(request)
    if err: return err
    name = request.data.get("name", "").strip().lstrip("#").lower()
    if not name:
        return Response({"error": "name required"}, status=400)
    # Try to auto-resolve the channel ID from Slack
    channel_id = ""
    is_private = bool(request.data.get("is_private", False))
    s = SlackSettings.get()
    if s.bot_token:
        try:
            from slack_sdk import WebClient
            client = WebClient(token=s.bot_token)
            cursor = None
            while True:
                resp = client.conversations_list(
                    types="public_channel,private_channel", limit=200, cursor=cursor or "",
                )
                for ch in resp.get("channels", []):
                    if ch["name"] == name:
                        channel_id = ch["id"]
                        is_private = ch.get("is_private", is_private)
                        break
                if channel_id:
                    break
                cursor = resp.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        except Exception as e:
            logger.info("Could not auto-resolve channel %s: %s", name, e)

    # Try to auto-join public channels so the bot can post
    joined = False
    join_error = ""
    if channel_id and s.bot_token:
        try:
            from slack_sdk import WebClient
            from slack_sdk.errors import SlackApiError
            client = WebClient(token=s.bot_token)
            try:
                client.conversations_join(channel=channel_id)
                joined = True
            except SlackApiError as je:
                err_code = je.response.get("error", "")
                if err_code == "already_in_channel" or err_code == "is_member":
                    joined = True
                elif err_code == "method_not_supported_for_channel_type":
                    # Private channel — can't auto-join
                    join_error = "Private channel: invite the bot manually in Slack."
                else:
                    join_error = err_code
        except Exception as e:
            logger.info("Could not auto-join %s: %s", name, e)

    reg, _ = SlackChannelRegistry.objects.update_or_create(
        name=name,
        defaults={
            "channel_id":  channel_id,
            "is_private":  is_private,
            "description": request.data.get("description", ""),
        },
    )
    return Response({
        "ok":         True,
        "id":         str(reg.id),
        "name":       reg.name,
        "channel_id": reg.channel_id,
        "resolved":   bool(channel_id),
        "joined":     joined,
        "join_error": join_error,
    })


@api_view(["POST"])
def slack_channel_registry_test(request, channel_id):
    """Send a test message to a registered channel to verify delivery."""
    from .models import SlackChannelRegistry
    err = require_admin(request)
    if err: return err
    try:
        reg = SlackChannelRegistry.objects.get(id=channel_id)
    except SlackChannelRegistry.DoesNotExist:
        return Response({"error": "Not found"}, status=404)

    from apps.notifications.tasks import post_to_slack
    target = reg.channel_id or reg.name
    ok = post_to_slack(target, "✅ Dispatch OS test — if you see this, the channel is wired correctly.")
    if ok:
        return Response({"ok": True, "message": f"Test sent to #{reg.name}"})
    return Response({
        "ok": False,
        "error": f"Could not post to #{reg.name}. "
                 f"{'Bot is not a member — invite it with /invite @<bot-name> in Slack.' if reg.is_private else 'Check server logs for details.'}"
    }, status=400)


@api_view(["DELETE"])
def slack_channel_registry_delete(request, channel_id):
    from .models import SlackChannelRegistry
    err = require_admin(request)
    if err: return err
    SlackChannelRegistry.objects.filter(id=channel_id).delete()
    return Response({"ok": True})


@api_view(["POST"])
def slack_test_channel(request):
    """Send a test message to a specific channel."""
    s = SlackSettings.get()
    token = s.bot_token
    if not token:
        return Response({"ok": False, "error": "No bot token saved"}, status=400)
    key = request.data.get("key")
    channel_map = {
        "safety":     s.channel_safety,
        "approvals":  s.channel_approvals,
        "compliance": s.channel_compliance,
        "system":     s.channel_system,
    }
    channel_id = channel_map.get(key)
    if not channel_id:
        return Response({"ok": False, "error": "Channel ID not configured"}, status=400)
    try:
        from slack_sdk import WebClient
        client = WebClient(token=token)
        client.chat_postMessage(channel=channel_id, text="✅ Test message from Dispatch OS — connection verified.")
        return Response({"ok": True})
    except Exception as e:
        return log_and_respond(e, "sending Slack test message", logger)


# ── Google Service Accounts ───────────────────────────────────────────────────

@api_view(["GET"])
def sa_list(request):
    """List all service accounts."""
    accounts = GoogleServiceAccount.objects.all().order_by("name")
    return Response([{
        "id":            str(a.id),
        "name":          a.name,
        "domain":        a.domain,
        "pubsub_topic":  a.pubsub_topic,
        "has_credentials": a.has_credentials,
        "client_email":  a.client_email,
        "project_id":    a.project_id,
        "is_active":     a.is_active,
        "last_test_at":  a.last_test_at,
        "last_test_ok":  a.last_test_ok,
        "last_test_error": a.last_test_error,
        "mailbox_count": a.mailboxes.count(),
    } for a in accounts])


@api_view(["POST"])
@parser_classes([MultiPartParser, JSONParser])
def sa_create(request):
    """Create a service account entry and optionally upload JSON key."""
    err = require_admin(request)
    if err: return err
    name   = request.data.get("name", "").strip()
    domain = request.data.get("domain", "").strip()
    topic  = request.data.get("pubsub_topic", "").strip()
    if not name or not domain:
        return Response({"error": "name and domain required"}, status=400)
    sa = GoogleServiceAccount.objects.create(name=name, domain=domain, pubsub_topic=topic)
    # Upload JSON file if provided
    json_file = request.FILES.get("json_file")
    if json_file:
        try:
            data = json.loads(json_file.read().decode("utf-8"))
            sa.json_data = data
            sa.save()
        except Exception as e:
            sa.delete()
            return Response({"error": f"Invalid JSON file: {e}"}, status=400)
    return Response({"ok": True, "id": str(sa.id)})


@api_view(["GET", "PATCH", "DELETE"])
def sa_detail(request, sa_id):
    try:
        sa = GoogleServiceAccount.objects.get(id=sa_id)
    except GoogleServiceAccount.DoesNotExist:
        return Response({"error": "Not found"}, status=404)

    if request.method == "GET":
        return Response({
            "id": str(sa.id), "name": sa.name, "domain": sa.domain,
            "pubsub_topic": sa.pubsub_topic, "has_credentials": sa.has_credentials,
            "client_email": sa.client_email, "project_id": sa.project_id,
            "is_active": sa.is_active, "last_test_at": sa.last_test_at,
            "last_test_ok": sa.last_test_ok, "last_test_error": sa.last_test_error,
        })

    if request.method == "PATCH":
        err = require_admin(request)
        if err: return err
        for field in ("name", "domain", "pubsub_topic", "is_active"):
            if field in request.data:
                setattr(sa, field, request.data[field])
        sa.save()
        return Response({"ok": True})

    if request.method == "DELETE":
        err = require_admin(request)
        if err: return err
        sa.delete()
        return Response({"ok": True})


@api_view(["POST"])
@parser_classes([MultiPartParser, JSONParser])
def sa_upload_json(request, sa_id):
    """Upload or replace the service account JSON key file."""
    err = require_admin(request)
    if err: return err
    try:
        sa = GoogleServiceAccount.objects.get(id=sa_id)
    except GoogleServiceAccount.DoesNotExist:
        return Response({"error": "Not found"}, status=404)
    json_file = request.FILES.get("json_file")
    if not json_file:
        # Try JSON body
        data = request.data.get("json_data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return Response({"error": "Invalid JSON"}, status=400)
        if not data:
            return Response({"error": "json_file or json_data required"}, status=400)
        sa.json_data = data
    else:
        try:
            data = json.loads(json_file.read().decode("utf-8"))
            sa.json_data = data
        except Exception as e:
            return Response({"error": f"Invalid JSON file: {e}"}, status=400)
    sa.save()
    return Response({"ok": True, "client_email": sa.client_email, "project_id": sa.project_id})


@api_view(["POST"])
def sa_test(request, sa_id):
    """Test the service account by impersonating a mailbox."""
    try:
        sa = GoogleServiceAccount.objects.get(id=sa_id)
    except GoogleServiceAccount.DoesNotExist:
        return Response({"error": "Not found"}, status=404)
    if not sa.has_credentials:
        return Response({"ok": False, "error": "No credentials uploaded yet"}, status=400)
    test_email = request.data.get("test_email") or MailboxSettings.objects.filter(service_account=sa).values_list("email_address", flat=True).first()
    if not test_email:
        return Response({"ok": False, "error": "Provide a test_email to impersonate"}, status=400)
    try:
        import tempfile, os
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from django.conf import settings as django_settings
        sa_data = sa.json_data
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sa_data, f)
            tmp_path = f.name
        try:
            creds = service_account.Credentials.from_service_account_file(
                tmp_path, scopes=django_settings.GMAIL_SCOPES
            ).with_subject(test_email)
            svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
            profile = svc.users().getProfile(userId="me").execute()
        finally:
            os.unlink(tmp_path)
        sa.last_test_at    = dj_tz.now()
        sa.last_test_ok    = True
        sa.last_test_error = ""
        sa.save(update_fields=["last_test_at", "last_test_ok", "last_test_error"])
        return Response({"ok": True, "email": profile.get("emailAddress"), "messages_total": profile.get("messagesTotal")})
    except Exception as e:
        sa.last_test_at    = dj_tz.now()
        sa.last_test_ok    = False
        from apps.core.error_utils import parse_google_error
        clean = parse_google_error(e)
        sa.last_test_at    = dj_tz.now()
        sa.last_test_ok    = False
        sa.last_test_error = clean
        sa.save(update_fields=["last_test_at", "last_test_ok", "last_test_error"])
        return Response({"ok": False, "error": clean}, status=400)


# ── Mailbox Settings ──────────────────────────────────────────────────────────

@api_view(["GET"])
def mailbox_list(request):
    # Admin endpoint: returns mailboxes across every MC so the email admin
    # can manage them all from one screen. The selected MC in the consolidated
    # UI header does not scope this list. Defense-in-depth: TMS-authenticated
    # requests still need email.mailbox.manage.
    tenant_mc = (request.headers.get("X-Tenant") or "").strip()
    if tenant_mc:
        from apps.users.tms_auth import has_tms_permission
        if not has_tms_permission(request.user, "email.mailbox.manage"):
            return Response(
                {"error": "Missing required permission: email.mailbox.manage"},
                status=403,
            )
    mbs = MailboxSettings.objects.select_related(
        "company", "service_account", "oauth_credential"
    ).all()
    return Response([{
        "id":              str(m.id),
        "email_address":   m.email_address,
        "display_name":    m.display_name,
        "purpose":         m.purpose,
        "auth_method":     m.auth_method or "oauth",  # never return null
        "is_authorized":   m.is_authorized,              # True if has valid creds for its auth type
        "sa_authorized":   bool(m.auth_method == "service_account" and m.service_account and m.service_account.has_credentials),
        "oauth_authorized": bool(m.auth_method != "service_account" and m.oauth_credential and m.oauth_credential.has_credentials),
        "company_id":      str(m.company_id),
        "company_name":    m.company.name,
        "company_mc":      m.company.mc_number,
        "company_color":   m.company.color,
        "service_account_id":   str(m.service_account_id) if m.service_account_id else None,
        "service_account_name": m.service_account.name if m.service_account else None,
        "oauth_connected": bool(m.oauth_credential and m.oauth_credential.has_credentials),
        "oauth_valid":     bool(m.oauth_credential and m.oauth_credential.is_valid),
        "watch_status":    m.watch_status,
        "last_history_id": m.last_history_id,
        "watch_expiry":    m.watch_expiry,
        "watch_error":     m.watch_error,
        "pubsub_topic":    m.pubsub_topic,
        "is_active":       m.is_active,
    } for m in mbs])


@api_view(["POST"])
def mailbox_create(request):
    err = require_admin(request)
    if err: return err
    from apps.companies.models import Company
    company_id = request.data.get("company_id", "").strip()
    if not company_id:
        return Response({"error": "company_id is required. Select a company from the dropdown."}, status=400)
    try:
        company = Company.objects.get(id=company_id)
    except Company.DoesNotExist:
        available = list(Company.objects.values_list("name", "mc_number"))
        if available:
            names = ", ".join(f"{n} ({mc})" for n, mc in available[:5])
            return Response({"error": f"Company not found. Available companies: {names}. Make sure you created your companies in Admin → Companies first."}, status=400)
        return Response({"error": "No companies exist yet. Go to Admin → Companies and create your MC companies first, then add mailboxes."}, status=400)
    except Exception:
        return Response({"error": "Invalid company ID format. Please select a company from the dropdown."}, status=400)
    email = request.data.get("email_address", "").strip().lower()
    if not email:
        return Response({"error": "email_address required"}, status=400)
    existing = MailboxSettings.objects.select_related("company").filter(email_address=email).first()
    if existing:
        return Response({
            "error": f"Mailbox {email} already exists under {existing.company.name} ({existing.company.mc_number}). Edit the existing mailbox instead of recreating it.",
            "existing_id": str(existing.id),
            "existing_company_id": str(existing.company_id),
            "existing_company_mc": existing.company.mc_number,
        }, status=409)
    sa_id = request.data.get("service_account_id")
    sa = GoogleServiceAccount.objects.filter(id=sa_id).first() if sa_id else None
    auth_method = request.data.get("auth_method", "oauth")
    if auth_method not in ("oauth", "service_account"):
        auth_method = "oauth"
    mb = MailboxSettings.objects.create(
        company=company,
        email_address=email,
        display_name=request.data.get("display_name", ""),
        purpose=request.data.get("purpose", "dispatch"),
        auth_method=auth_method,
        service_account=sa,
        pubsub_topic=request.data.get("pubsub_topic", ""),
        is_active=True,
    )
    return Response({"ok": True, "id": str(mb.id)})


@api_view(["PATCH", "DELETE"])
def mailbox_detail(request, mb_id):
    try:
        mb = MailboxSettings.objects.select_related("company","service_account").get(id=mb_id)
    except MailboxSettings.DoesNotExist:
        return Response({"error": "Not found"}, status=404)
    err = require_admin(request)
    if err: return err
    if request.method == "DELETE":
        mb.delete()
        return Response({"ok": True})
    for field in ("display_name", "purpose", "is_active", "pubsub_topic"):
        if field in request.data:
            setattr(mb, field, request.data[field])
    if "auth_method" in request.data and request.data["auth_method"] in ("oauth", "service_account"):
        mb.auth_method = request.data["auth_method"]
    if "service_account_id" in request.data:
        sa = GoogleServiceAccount.objects.filter(id=request.data["service_account_id"]).first()
        mb.service_account = sa
    mb.save()
    return Response({"ok": True})


@api_view(["POST"])
def mailbox_register_watch(request, mb_id):
    """Register or renew Gmail push watch for this mailbox (OAuth or Service Account)."""
    err = require_admin(request)
    if err: return err
    try:
        mb = MailboxSettings.objects.select_related(
            "service_account", "oauth_credential"
        ).get(id=mb_id)
    except MailboxSettings.DoesNotExist:
        return Response({"error": "Not found"}, status=404)

    if not mb.is_authorized:
        return Response({"error": "Mailbox not connected. Connect OAuth or upload SA key first."}, status=400)

    # Get Pub/Sub topic — mailbox override > SA topic > global env var
    topic = mb.pubsub_topic.strip() if mb.pubsub_topic else ""
    if not topic and mb.service_account and mb.service_account.pubsub_topic:
        topic = mb.service_account.pubsub_topic
    if not topic:
        from django.conf import settings as ds
        topic = getattr(ds, "GOOGLE_PUBSUB_TOPIC", "")

    if not topic:
        return Response({
            "error": "Pub/Sub topic not configured. Set GOOGLE_PUBSUB_TOPIC in .env "
                     "or add it to the Service Account (format: projects/YOUR-PROJECT/topics/gmail-dispatch-push)"
        }, status=400)

    try:
        from apps.settings.gmail_oauth import get_gmail_service
        svc = get_gmail_service(mb)
        result = svc.users().watch(
            userId="me",
            body={"topicName": topic, "labelIds": ["INBOX"], "labelFilterBehavior": "INCLUDE"}
        ).execute()

        expiry = datetime.fromtimestamp(int(result["expiration"]) / 1000, tz=timezone.utc)
        mb.watch_status    = "active"
        mb.watch_expiry    = expiry
        mb.last_history_id = result.get("historyId", "")
        mb.watch_error     = ""
        mb.save()
        return Response({"ok": True, "expiry": expiry.isoformat(), "history_id": mb.last_history_id,
                         "topic": topic, "auth_method": mb.auth_method})
    except Exception as e:
        from apps.core.error_utils import parse_error
        clean = parse_error(e, "registering Gmail watch")
        mb.watch_status = "error"
        mb.watch_error  = clean
        mb.save(update_fields=["watch_status", "watch_error"])
        return Response({"ok": False, "error": clean}, status=400)


@api_view(["POST"])
def mailbox_stop_watch(request, mb_id):
    err = require_admin(request)
    if err: return err
    try:
        mb = MailboxSettings.objects.select_related("service_account").get(id=mb_id)
    except MailboxSettings.DoesNotExist:
        return Response({"error": "Not found"}, status=404)
    try:
        import tempfile, os, json as _json
        from google.oauth2 import service_account as sa_lib
        from googleapiclient.discovery import build
        from django.conf import settings as ds
        sa_data = mb.service_account.json_data
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump(sa_data, f)
            tmp = f.name
        try:
            creds = sa_lib.Credentials.from_service_account_file(tmp, scopes=ds.GMAIL_SCOPES).with_subject(mb.email_address)
            svc   = build("gmail", "v1", credentials=creds, cache_discovery=False)
            svc.users().stop(userId="me").execute()
        finally:
            os.unlink(tmp)
    except Exception:
        pass
    mb.watch_status = "inactive"
    mb.save(update_fields=["watch_status"])
    return Response({"ok": True})



# ── OAuth App Config ──────────────────────────────────────────────────────────

@api_view(["GET"])
def oauth_app_get_legacy(request):
    from .models import OAuthApp
    app = OAuthApp.get_active()
    if not app:
        return Response({"configured": False})
    return Response({
        "configured":    True,
        "name":          app.name,
        "client_id":     app.client_id,
        "client_secret_set": bool(app._client_secret),
        "redirect_uri":  app.redirect_uri,
        "has_credentials": app.has_credentials,
    })


@api_view(["POST"])
def oauth_app_save(request):
    """Create or update an OAuth app. Pass id to update existing, omit to create new."""
    err = require_admin(request)
    if err: return err
    from .models import OAuthApp
    app_id = request.data.get("id", "").strip()
    if app_id:
        try:
            app = OAuthApp.objects.get(id=app_id)
        except OAuthApp.DoesNotExist:
            return Response({"error": "OAuth app not found"}, status=404)
    else:
        app = OAuthApp()

    app.name         = request.data.get("name", app.name or "Dispatch OS OAuth").strip()
    app.client_id    = request.data.get("client_id", app.client_id or "").strip()
    app.redirect_uri = request.data.get("redirect_uri", app.redirect_uri or "").strip()
    app.is_active    = request.data.get("is_active", True)
    secret = request.data.get("client_secret", "").strip()
    if secret:
        app.client_secret = secret
    app.save()
    return Response({"ok": True, "id": str(app.id), "name": app.name})


@api_view(["GET"])
def oauth_app_list(request):
    """List all OAuth apps."""
    from .models import OAuthApp
    apps = OAuthApp.objects.all().order_by("created_at")
    return Response([{
        "id":           str(a.id),
        "name":         a.name,
        "client_id":    a.client_id,
        "redirect_uri": a.redirect_uri,
        "is_active":    a.is_active,
        "has_credentials": a.has_credentials,
    } for a in apps])


@api_view(["DELETE"])
def oauth_app_delete(request, app_id):
    """Delete an OAuth app."""
    err = require_admin(request)
    if err: return err
    from .models import OAuthApp
    try:
        OAuthApp.objects.get(id=app_id).delete()
        return Response({"ok": True})
    except OAuthApp.DoesNotExist:
        return Response({"error": "Not found"}, status=404)


# ── OAuth Flow ────────────────────────────────────────────────────────────────

@api_view(["POST"])
def oauth_begin(request):
    """Start OAuth flow for a mailbox. Returns the Google consent URL."""
    err = require_admin(request)
    if err: return err
    from .models import OAuthApp, MailboxSettings
    from .gmail_oauth import build_oauth_auth_url
    email  = request.data.get("email_address", "").strip().lower()
    app_id = request.data.get("oauth_app_id", "").strip()
    if not email:
        return Response({"error": "email_address required"}, status=400)
    # Use specified app or fall back to first active
    if app_id:
        try:
            oauth_app = OAuthApp.objects.get(id=app_id, is_active=True)
        except OAuthApp.DoesNotExist:
            return Response({"error": "OAuth app not found"}, status=404)
    else:
        oauth_app = OAuthApp.get_active()
    if not oauth_app or not oauth_app.has_credentials:
        return Response({"error": "No OAuth app configured. Add one in Admin → Credentials → Gmail → OAuth Apps"}, status=400)
    try:
        # Encode both email and app ID in state so callback uses the correct app
        state = json.dumps({"email": email, "app_id": str(oauth_app.id)})
        url = build_oauth_auth_url(email, oauth_app, state=state)
        return Response({"auth_url": url, "email": email, "oauth_app_id": str(oauth_app.id)})
    except Exception as e:
        return Response({"error": str(e)}, status=400)


@csrf_exempt
def oauth_callback(request):
    """
    Google redirects here after the user grants consent.
    Exchanges the code for tokens and saves them.
    Always returns an HTML page that closes the popup and messages the opener.
    """
    import os
    from .models import OAuthApp, OAuthCredential, MailboxSettings
    from .gmail_oauth import exchange_oauth_code
    from django.utils import timezone as dj_tz
    from django.http import HttpResponse

    # Ensure insecure transport is set (ngrok forwards HTTP internally)
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    def html_response(msg_type, payload_key, payload_val):
        """Return HTML that posts a message to the opener and closes itself."""
        val_escaped = str(payload_val).replace("'", "\'").replace('"', '\"')
        return HttpResponse(f"""<!DOCTYPE html><html><body>
<p>{'Connected successfully! You can close this window.' if msg_type == 'oauth_success' else 'Error: ' + val_escaped}</p>
<script>
  try {{
    if (window.opener) {{
      window.opener.postMessage({{type:'{msg_type}',{payload_key}:'{val_escaped}'}}, '*');
    }}
  }} catch(e) {{}}
  setTimeout(function() {{ window.close(); }}, 1500);
</script></body></html>""", content_type="text/html")

    code  = request.GET.get("code", "").strip()
    raw_state = request.GET.get("state", "").strip()
    error = request.GET.get("error", "")

    # Parse state — can be JSON {"email":"...","app_id":"..."} or plain email (legacy)
    oauth_app_id = None
    try:
        state_data = json.loads(raw_state)
        email = state_data.get("email", "")
        oauth_app_id = state_data.get("app_id", "")
    except (json.JSONDecodeError, TypeError):
        email = raw_state

    if error:
        error_map = {
            "access_denied": "Access denied — you clicked 'Deny' on the consent screen. Try again and click 'Allow'.",
            "invalid_client": "Invalid OAuth client — the Client ID or Secret is wrong. Check Admin → Credentials → OAuth Apps.",
            "redirect_uri_mismatch": "Redirect URI mismatch — add the correct redirect URI in Google Cloud Console → Credentials → your OAuth app → Authorized redirect URIs.",
            "invalid_scope": "Invalid scope — the Gmail API scopes are not enabled. Enable Gmail API in Google Cloud Console.",
            "server_error": "Google returned a server error. Try again in a few minutes.",
        }
        human_error = error_map.get(error, f"Google OAuth error: {error}")
        error_desc = request.GET.get("error_description", "")
        if error_desc:
            human_error += f" ({error_desc})"
        return html_response("oauth_error", "error", human_error)
    if not code:
        return html_response("oauth_error", "error", "No authorization code received from Google.")

    # Use the same OAuth app that started the flow
    if oauth_app_id:
        try:
            oauth_app = OAuthApp.objects.get(id=oauth_app_id, is_active=True)
        except OAuthApp.DoesNotExist:
            oauth_app = OAuthApp.get_active()
    else:
        oauth_app = OAuthApp.get_active()
    if not oauth_app or not oauth_app.has_credentials:
        return html_response("oauth_error", "error", "OAuth app not configured in Dispatch OS. Add Client ID and Secret first.")

    try:
        tokens = exchange_oauth_code(code, oauth_app)
        confirmed_email = tokens.get("email") or email
        if not confirmed_email:
            return html_response("oauth_error", "error", "Could not determine Gmail address from token.")

        cred, _ = OAuthCredential.objects.get_or_create(email_address=confirmed_email)
        cred.oauth_app      = oauth_app  # remember which app issued this token
        cred.refresh_token  = tokens["refresh_token"]
        cred.access_token   = tokens.get("access_token", "")
        cred.token_expiry   = tokens.get("expiry")
        cred.is_valid       = True
        cred.last_error     = ""
        cred.authorized_at  = dj_tz.now()
        cred.save()

        # Auto-link to matching MailboxSettings
        linked = 0
        for mb in MailboxSettings.objects.filter(email_address=confirmed_email):
            mb.oauth_credential = cred
            mb.auth_method      = "oauth"
            mb.save(update_fields=["oauth_credential", "auth_method"])
            linked += 1

        logger.info("OAuth success for %s (linked %d mailbox(es))", confirmed_email, linked)
        return html_response("oauth_success", "email", confirmed_email)

    except Exception as e:
        logger.exception("OAuth callback failed for state=%s", email)
        return html_response("oauth_error", "error", str(e))


@api_view(["GET"])
def oauth_credentials_list(request):
    """List all OAuth credentials and their status."""
    from .models import OAuthCredential
    creds = OAuthCredential.objects.all().order_by("email_address")
    return Response([{
        "id":            str(c.id),
        "email_address": c.email_address,
        "has_credentials": c.has_credentials,
        "is_valid":      c.is_valid,
        "last_error":    c.last_error,
        "authorized_at": c.authorized_at,
    } for c in creds])


@api_view(["DELETE"])
def oauth_credential_delete(request, cred_id):
    err = require_admin(request)
    if err: return err
    from .models import OAuthCredential
    try:
        OAuthCredential.objects.get(id=cred_id).delete()
        return Response({"ok": True})
    except OAuthCredential.DoesNotExist:
        return Response({"error": "Not found"}, status=404)


# ── Mailbox: test connection ──────────────────────────────────────────────────

@api_view(["POST"])
def mailbox_test_connection(request, mb_id):
    """
    Test that we can actually authenticate with Gmail for this mailbox.
    Calls users.getProfile — returns email address and message count.
    """
    try:
        mb = MailboxSettings.objects.select_related("service_account", "oauth_credential", "company").get(id=mb_id)
    except MailboxSettings.DoesNotExist:
        return Response({"error": "Mailbox not found"}, status=404)

    if not mb.is_authorized:
        if mb.auth_method == "oauth":
            return Response({"ok": False, "error": "Not connected. Click Connect OAuth to authorize this mailbox."}, status=400)
        else:
            return Response({"ok": False, "error": "No service account key uploaded."}, status=400)

    try:
        from apps.settings.gmail_oauth import get_gmail_service
        from apps.core.error_utils import parse_error
        svc     = get_gmail_service(mb)
        profile = svc.users().getProfile(userId="me").execute()
        email   = profile.get("emailAddress", mb.email_address)
        total   = profile.get("messagesTotal", 0)
        threads = profile.get("threadsTotal", 0)
        return Response({
            "ok":             True,
            "email":          email,
            "messages_total": total,
            "threads_total":  threads,
            "auth_method":    mb.auth_method,
        })
    except Exception as e:
        from apps.core.error_utils import parse_error
        return Response({"ok": False, "error": parse_error(e, "connecting to Gmail")}, status=400)


# ── Mailbox: manual email sync ────────────────────────────────────────────────

@api_view(["POST"])
def mailbox_sync(request, mb_id):
    """
    Synchronous email pull — processes emails INLINE (no Celery).
    Returns a step-by-step log of exactly what happened so the user
    can see errors immediately rather than waiting for a silent background task.
    """
    try:
        mb = MailboxSettings.objects.select_related(
            "service_account", "oauth_credential", "company"
        ).get(id=mb_id)
    except MailboxSettings.DoesNotExist:
        return Response({"error": "Mailbox not found"}, status=404)

    if not mb.is_authorized:
        auth_hint = ("Click Connect OAuth to authorize this mailbox first."
                     if mb.auth_method == "oauth"
                     else "Upload a service account JSON key first.")
        return Response({"error": f"Mailbox not connected. {auth_hint}"}, status=400)

    limit = min(int(request.data.get("limit", 50)), 200)  # default 50, max 200
    logs  = []  # Step-by-step log returned to the UI

    def log(msg, level="info"):
        logs.append({"level": level, "msg": msg})

    try:
        from apps.settings.gmail_oauth import get_gmail_service
        from apps.core.error_utils import parse_error
        from apps.conversations.models import Conversation, Message
        from apps.mailboxes.tasks import _get_or_create_legacy_mailbox, _parse_headers, _extract_email, _extract_body, _extract_attachments
        from django.utils import timezone as tz

        # Step 1: connect
        log(f"Connecting to Gmail as {mb.email_address} via {mb.auth_method}…")
        try:
            svc = get_gmail_service(mb)
            profile = svc.users().getProfile(userId="me").execute()
            total_msgs = profile.get("messagesTotal", 0)
            log(f"✓ Connected — {total_msgs:,} total messages in mailbox", "success")
        except Exception as e:
            err = parse_error(e, "connecting to Gmail")
            log(f"✗ Connection failed: {err}", "error")
            return Response({"ok": False, "logs": logs, "error": err}, status=400)

        # Step 2: list inbox messages — newest first, paginate if needed
        log(f"Fetching up to {limit} most recent inbox messages…")
        try:
            messages = []
            page_token = None
            while len(messages) < limit:
                kwargs = {
                    "userId": "me",
                    "labelIds": ["INBOX"],
                    "maxResults": min(limit - len(messages), 100),  # Gmail API max is 100
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                result = svc.users().messages().list(**kwargs).execute()
                messages.extend(result.get("messages", []))
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
            log(f"✓ Found {len(messages)} messages in inbox (newest first)")
        except Exception as e:
            err = parse_error(e, "listing inbox messages")
            log(f"✗ Failed to list messages: {err}", "error")
            return Response({"ok": False, "logs": logs, "error": err}, status=400)

        if not messages:
            log("Inbox is empty — no emails to import", "warn")
            return Response({"ok": True, "logs": logs, "imported": 0, "skipped": 0})

        # Step 3: find threads that have at least one new message
        existing_ids = set(
            Message.objects.filter(
                gmail_message_id__in=[m["id"] for m in messages]
            ).values_list("gmail_message_id", flat=True)
        )
        new_thread_ids = list({m["threadId"] for m in messages if m["id"] not in existing_ids})
        already = len(messages) - len([m for m in messages if m["id"] not in existing_ids])
        if already:
            log(f"Skipping {already} already-imported messages")
        log(f"Found {len(new_thread_ids)} thread(s) with new messages — fetching full conversations…")

        if not new_thread_ids:
            log("All messages already imported — inbox is up to date", "success")
            return Response({"ok": True, "logs": logs, "imported": 0, "skipped": already})

        # Step 4: get/create legacy Mailbox bridge for Conversation FK
        try:
            legacy_mb = _get_or_create_legacy_mailbox(mb)
        except Exception as e:
            err = parse_error(e, "creating mailbox record")
            log(f"✗ Internal setup failed: {err}", "error")
            return Response({"ok": False, "logs": logs, "error": err}, status=500)

        # Step 5: fetch each full thread and import all messages in it
        imported = 0
        errors   = 0
        from email.utils import parsedate_to_datetime
        import datetime as _dt
        from apps.mailboxes.tasks import _clean_body_text
        from apps.conversations.models import Attachment
        from apps.classifier.tasks import classify_message

        for t_idx, t_id in enumerate(new_thread_ids):
            try:
                thread = svc.users().threads().get(userId="me", id=t_id, format="full").execute()
            except Exception as e:
                log(f"✗ Could not fetch thread {t_id}: {parse_error(e,'')}", "error")
                errors += 1
                continue

            thread_msgs = thread.get("messages", [])
            log(f"Thread {t_idx+1}/{len(new_thread_ids)}: {len(thread_msgs)} message(s)")

            for i, raw in enumerate(thread_msgs):
                msg_id = raw.get("id", "")
                if not msg_id or Message.objects.filter(gmail_message_id=msg_id).exists():
                    continue
                try:
                    headers    = _parse_headers(raw)
                    from_email = _extract_email(headers["from"])
                    subject    = headers["subject"]
                    snippet    = raw.get("snippet", "")

                    # Determine direction — outbound if sent by this mailbox
                    direction = "outbound" if from_email.lower() == mb.email_address.lower() else "inbound"

                    # Use real Gmail send time
                    try:
                        _h = {x["name"].lower(): x["value"] for x in raw.get("payload",{}).get("headers",[])}
                        sent_at = parsedate_to_datetime(_h["date"]) if _h.get("date") else None
                        if sent_at and sent_at.tzinfo is None:
                            sent_at = sent_at.replace(tzinfo=_dt.timezone.utc)
                        if not sent_at:
                            _ms = raw.get("internalDate")
                            sent_at = _dt.datetime.fromtimestamp(int(_ms)/1000, tz=_dt.timezone.utc) if _ms else tz.now()
                    except Exception:
                        sent_at = tz.now()

                    mc_number_cached = ""
                    try:
                        mc_number_cached = legacy_mb.company.mc_number or ""
                    except Exception:
                        pass

                    conv, created = Conversation.objects.get_or_create(
                        gmail_thread_id=t_id,
                        mailbox=legacy_mb,
                        defaults={
                            "status": "open",
                            "last_message_at": sent_at,
                            "mc_number": mc_number_cached,
                        },
                    )
                    if not created and (not conv.last_message_at or sent_at > conv.last_message_at):
                        Conversation.objects.filter(id=conv.id).update(last_message_at=sent_at)
                    if not conv.mc_number and mc_number_cached:
                        Conversation.objects.filter(id=conv.id).update(mc_number=mc_number_cached)
                        conv.mc_number = mc_number_cached

                    payload       = raw.get("payload", {})
                    body_text_raw, body_html = _extract_body(payload)
                    body_text     = _clean_body_text(body_text_raw)
                    att_meta      = _extract_attachments(payload, msg_id)

                    # On outbound, recipient is the actual To: header (the
                    # broker we wrote to), not our own mailbox. cc captures
                    # the Cc: header so the UI can show real Cc lists. v1
                    # collapses multi-To to the primary address.
                    to_header = headers.get("to", "") or ""
                    cc_header = headers.get("cc", "") or ""
                    if direction == "outbound":
                        primary_to = _extract_email(to_header.split(",")[0]) if to_header else mb.email_address
                    else:
                        primary_to = mb.email_address
                    msg_obj = Message.objects.create(
                        conversation     = conv,
                        direction        = direction,
                        gmail_message_id = msg_id,
                        sender_email     = from_email,
                        recipient_email  = primary_to,
                        cc               = cc_header,
                        subject          = subject,
                        snippet          = snippet,
                        body_text        = body_text or snippet,
                        body_html        = body_html,
                        raw_message_id   = headers["message_id"],
                        in_reply_to      = headers["in_reply_to"],
                    )

                    att_count = 0
                    for att in att_meta:
                        try:
                            if not Attachment.objects.filter(message=msg_obj, filename=att["filename"]).exists():
                                Attachment.objects.create(
                                    message=msg_obj, filename=att["filename"],
                                    mime_type=att["mime_type"], size=att["size"],
                                    gmail_attachment_id=att["attachment_id"], downloaded=False,
                                )
                                att_count += 1
                        except Exception as att_err:
                            logger.warning("Attachment save error: %s", att_err)

                    att_info = f" + {att_count} att" if att_count else ""
                    imported += 1
                    dir_label = "→ sent" if direction == "outbound" else "← recv"
                    log(f"  ✓ {dir_label} {subject[:50]} — {from_email}{att_info}", "success")

                    # Fill the denormalized inbox preview from the first inbound
                    # message we see for this thread. Without this the CARRIERS
                    # sidebar (which groups by preview_sender's domain) sees an
                    # empty column for every sync-ingested row.
                    if direction == "inbound":
                        preview_updates = {}
                        if not conv.preview_sender and from_email:
                            preview_updates["preview_sender"] = from_email
                        if conv.preview_subject in (None, "", "(no subject)") and subject:
                            preview_updates["preview_subject"] = subject
                        if not conv.preview_snippet and snippet:
                            preview_updates["preview_snippet"] = snippet
                        if preview_updates:
                            Conversation.objects.filter(id=conv.id).update(**preview_updates)
                            for k, v in preview_updates.items():
                                setattr(conv, k, v)

                    if direction == "inbound":
                        try:
                            from apps.classifier.engine import classify_fast
                            result = classify_fast(from_email, subject, body_text)
                            conv.category = result["category"]
                            conv.priority = result["priority"]
                            conv.save(update_fields=["category", "priority", "updated_at"])
                            from apps.classifier.models import Classification
                            Classification.objects.update_or_create(
                                message=msg_obj,
                                defaults={"category": result["category"], "priority": result["priority"],
                                          "ai_summary": result["summary"], "confidence": result["confidence"],
                                          "model_version": result.get("model", "keyword")},
                            )
                            # Dispatch AI refinement async — keyword above gives an instant
                            # baseline; the worker overwrites with Haiku's answer when it
                            # lands. NOISE rows are skipped to save tokens (the engine
                            # short-circuits them too, but cheaper to never enqueue).
                            if result.get("category") != "NOISE":
                                try:
                                    classify_message.delay(str(msg_obj.id))
                                except Exception as cls_err:
                                    logger.warning("AI classify dispatch failed: %s", cls_err)
                        except Exception:
                            pass

                except Exception as e:
                    errors += 1
                    log(f"  ✗ Failed msg {msg_id}: {parse_error(e,'')}", "error")
                    if errors >= 10:
                        log("Stopping after 10 errors", "warn")
                        break

        # Step 6: update history ID
        try:
            latest = svc.users().getProfile(userId="me").execute().get("historyId", "")
            if latest:
                mb.last_history_id = latest
                mb.save(update_fields=["last_history_id", "updated_at"])
        except Exception:
            pass

        summary = f"Done — imported {imported} emails"
        if errors:
            summary += f", {errors} failed"
        if already:
            summary += f", {already} already existed"
        log(summary, "success" if errors == 0 else "warn")

        return Response({
            "ok":       True,
            "logs":     logs,
            "imported": imported,
            "skipped":  already,
            "errors":   errors,
        })

    except Exception as e:
        from apps.core.error_utils import parse_error
        err = parse_error(e, "sync")
        log(f"✗ Unexpected error: {err}", "error")
        return Response({"ok": False, "logs": logs, "error": err}, status=500)


# ── System health (updated) ───────────────────────────────────────────────────

@api_view(["GET"])
def system_health(request):
    from .models import OAuthCredential
    slack = SlackSettings.get()
    oauth_creds = OAuthCredential.objects.filter(is_valid=True).count()
    return Response({
        "slack": {
            "configured":         slack.bot_token_set,
            "channels_configured": sum([
                bool(slack.channel_safety), bool(slack.channel_approvals),
                bool(slack.channel_compliance), bool(slack.channel_system),
            ]),
        },
        "google": {
            "service_accounts": GoogleServiceAccount.objects.filter(is_active=True).count(),
            "mailboxes_total":  MailboxSettings.objects.filter(is_active=True).count(),
            "oauth_connected":  oauth_creds,
            "watches_active":   MailboxSettings.objects.filter(watch_status="active").count(),
            "watches_error":    MailboxSettings.objects.filter(watch_status="error").count(),
        },
    })


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTICS — full health check for ALL integrations with fix instructions
# ══════════════════════════════════════════════════════════════════════════════

FIXES = {
    # Gmail / Google
    "no_sa_key":        "Upload the service account JSON key: Admin → Credentials → Gmail → Service Accounts → Upload Key",
    "no_sa_domain":     "Enter the Google Workspace domain (e.g. yourcompany.com) for this service account",
    "no_pubsub_topic":  "Set the Pub/Sub topic: Admin → Credentials → Gmail → Service Accounts → Edit → fill in Pub/Sub Topic (format: projects/YOUR-PROJECT-ID/topics/gmail-dispatch-push)",
    "delegation":       "Enable domain-wide delegation: GCP → IAM → Service Accounts → click account → Edit → Enable G Suite Domain-Wide Delegation. Then add scopes in Google Workspace Admin → Security → API Controls → Domain-Wide Delegation → Add: https://www.googleapis.com/auth/gmail.modify, https://www.googleapis.com/auth/gmail.send",
    "no_oauth_cred":    "Connect this mailbox: Admin → Credentials → Mailboxes → click CONNECT OAUTH → sign in with the Gmail account → Allow",
    "oauth_expired":    "OAuth token expired or revoked. Click CONNECT OAUTH again to re-authorize",
    "no_oauth_app":     "Configure OAuth App first: Admin → Credentials → Gmail → OAuth App → paste Client ID and Client Secret from GCP Console → Save",
    "no_watch":         "Register Gmail push watch: Admin → Credentials → Mailboxes → click REGISTER WATCH. Also ensure your Pub/Sub subscription endpoint is publicly accessible.",
    "watch_expired":    "Watch has expired. Click RENEW WATCH in Admin → Credentials → Mailboxes",
    # Slack
    "no_slack_token":   "Add Slack bot token: Admin → Credentials → Slack → paste the xoxb- token from api.slack.com/apps → your app → OAuth & Permissions → Bot User OAuth Token",
    "slack_token_bad":  "Invalid Slack token. Re-paste the xoxb- Bot User OAuth Token from api.slack.com/apps → your app → OAuth & Permissions",
    "no_channel":       "Set channel ID: Admin → Credentials → Slack → enter the Channel ID (right-click the channel in Slack → View channel details → scroll to bottom) and channel name",
    "bot_not_in_channel": "Add the Dispatch OS bot to this channel: open the channel in Slack → click the channel name → Integrations → Add an App → Dispatch OS",
    # General
    "no_companies":     "Create your MC companies first: Admin → Companies → Add Company with name and MC number",
    "no_mailboxes":     "Add at least one mailbox: Admin → Credentials → Mailboxes → Add Mailbox",
    "worker_down":      "Start the Celery worker: run 'docker compose up worker -d' in your terminal",
}


def _check_gmail_sa(sa, mailboxes_for_sa):
    """Diagnose a single service account and its mailboxes."""
    issues = []
    if not sa.has_credentials:
        issues.append({"level": "error", "msg": f"No JSON key uploaded for '{sa.name}'", "fix": FIXES["no_sa_key"]})
        return issues

    if not sa.pubsub_topic:
        issues.append({"level": "warn", "msg": f"No Pub/Sub topic set for '{sa.name}' — push notifications won't work", "fix": FIXES["no_pubsub_topic"]})

    # Try a live connection test
    try:
        import tempfile, os as _os, json as _json
        from google.oauth2 import service_account as sa_lib
        from googleapiclient.discovery import build
        from django.conf import settings as ds
        from apps.core.error_utils import parse_google_error

        sa_data = sa.json_data
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump(sa_data, f); tmp = f.name
        try:
            test_email = mailboxes_for_sa[0].email_address if mailboxes_for_sa else None
            if not test_email:
                issues.append({"level": "warn", "msg": f"Service account '{sa.name}' has no mailboxes linked — can't verify delegation", "fix": FIXES["no_mailboxes"]})
                return issues
            creds = sa_lib.Credentials.from_service_account_file(tmp, scopes=ds.GMAIL_SCOPES).with_subject(test_email)
            svc   = build("gmail", "v1", credentials=creds, cache_discovery=False)
            profile = svc.users().getProfile(userId="me").execute()
            issues.append({"level": "ok", "msg": f"Service account '{sa.name}' → {test_email}: connected ({profile.get('messagesTotal',0):,} messages)"})
        finally:
            _os.unlink(tmp)
    except Exception as e:
        from apps.core.error_utils import parse_google_error
        msg = parse_google_error(e)
        fix = FIXES["delegation"] if "unauthorized_client" in str(e) or "forbidden" in msg.lower() else FIXES["no_sa_key"]
        issues.append({"level": "error", "msg": f"Service account '{sa.name}' connection failed: {msg}", "fix": fix})

    return issues


def _check_mailbox(mb):
    """Diagnose a single mailbox."""
    issues = []
    email = mb.email_address

    if mb.auth_method == "oauth":
        if not mb.oauth_credential or not mb.oauth_credential.has_credentials:
            issues.append({"level": "error", "msg": f"{email}: not connected via OAuth", "fix": FIXES["no_oauth_cred"]})
            return issues
        if mb.oauth_credential and not mb.oauth_credential.is_valid:
            issues.append({"level": "error", "msg": f"{email}: OAuth token is invalid or expired", "fix": FIXES["oauth_expired"]})
            return issues
        # Live test
        try:
            from apps.settings.gmail_oauth import get_gmail_service
            from apps.core.error_utils import parse_google_error
            svc = get_gmail_service(mb)
            profile = svc.users().getProfile(userId="me").execute()
            issues.append({"level": "ok", "msg": f"{email}: OAuth connected ({profile.get('messagesTotal',0):,} messages, {profile.get('threadsTotal',0):,} threads)"})
        except Exception as e:
            from apps.core.error_utils import parse_google_error
            msg = parse_google_error(e)
            fix = FIXES["oauth_expired"] if "invalid_grant" in str(e) else FIXES["no_oauth_cred"]
            issues.append({"level": "error", "msg": f"{email}: OAuth connection failed — {msg}", "fix": fix})
            return issues
    else:
        if not mb.service_account or not mb.service_account.has_credentials:
            issues.append({"level": "error", "msg": f"{email}: no service account linked", "fix": FIXES["no_sa_key"]})
            return issues

    # Check watch status
    if mb.watch_status == "active":
        import datetime
        if mb.watch_expiry:
            days_left = (mb.watch_expiry - datetime.datetime.now(datetime.timezone.utc)).days
            if days_left <= 2:
                issues.append({"level": "warn", "msg": f"{email}: Gmail watch expires in {days_left} day(s)", "fix": FIXES["watch_expired"]})
            else:
                issues.append({"level": "ok", "msg": f"{email}: Gmail watch active — expires {mb.watch_expiry.strftime('%b %d')}"})
        else:
            issues.append({"level": "ok", "msg": f"{email}: Gmail watch active"})
    elif mb.watch_status == "expired":
        issues.append({"level": "warn", "msg": f"{email}: Gmail watch expired — new emails won't arrive automatically", "fix": FIXES["watch_expired"]})
    elif mb.watch_status == "error":
        issues.append({"level": "error", "msg": f"{email}: Gmail watch error — {mb.watch_error or 'unknown error'}", "fix": FIXES["no_watch"]})
    else:
        issues.append({"level": "warn", "msg": f"{email}: No Gmail watch registered — emails won't arrive automatically", "fix": FIXES["no_watch"]})

    return issues


def _check_slack():
    """Diagnose Slack configuration."""
    issues = []
    s = SlackSettings.get()

    if not s.bot_token_set:
        issues.append({"level": "error", "msg": "No Slack bot token configured — all Slack alerts disabled", "fix": FIXES["no_slack_token"]})
        return issues

    # Test token
    try:
        from slack_sdk import WebClient
        from apps.core.error_utils import parse_slack_error
        client = WebClient(token=s.bot_token)
        r = client.auth_test()
        issues.append({"level": "ok", "msg": f"Slack connected: workspace '{r.get('team')}', bot @{r.get('user')}"})
    except Exception as e:
        from apps.core.error_utils import parse_slack_error
        msg = parse_slack_error(e)
        issues.append({"level": "error", "msg": f"Slack token invalid: {msg}", "fix": FIXES["slack_token_bad"]})
        return issues

    # Test each channel
    ch_defs = [
        ("safety",     s.channel_safety,     s.channel_safety_name,     "Safety Alerts"),
        ("approvals",  s.channel_approvals,  s.channel_approvals_name,  "Approvals"),
        ("compliance", s.channel_compliance, s.channel_compliance_name, "Compliance Alerts"),
        ("system",     s.channel_system,     s.channel_system_name,     "System Alerts"),
    ]
    try:
        from slack_sdk import WebClient
        client = WebClient(token=s.bot_token)
        for key, ch_id, ch_name, label in ch_defs:
            if not ch_id:
                issues.append({"level": "warn", "msg": f"Slack #{label} channel not configured — alerts for this type won't be sent", "fix": FIXES["no_channel"]})
                continue
            try:
                # Try to get channel info to verify bot is in it
                ch_info = client.conversations_info(channel=ch_id)
                name = ch_name or ch_info.get("channel", {}).get("name", ch_id)
                is_member = ch_info.get("channel", {}).get("is_member", False)
                if not is_member:
                    issues.append({"level": "warn", "msg": f"Slack bot is not in #{name} — add it to receive {label}", "fix": FIXES["bot_not_in_channel"]})
                else:
                    issues.append({"level": "ok", "msg": f"#{name}: bot is a member ✓"})
            except Exception as ce:
                from apps.core.error_utils import parse_slack_error
                cmsg = parse_slack_error(ce)
                fix = FIXES["bot_not_in_channel"] if "not_in_channel" in str(ce) else FIXES["no_channel"]
                issues.append({"level": "error", "msg": f"Slack #{label} channel error: {cmsg}", "fix": fix})
    except Exception:
        pass

    return issues


@api_view(["GET"])
def full_diagnostics(request):
    """
    Comprehensive health check for all integrations.
    Returns categorised issues with specific fix instructions for every problem.
    """
    from .models import GoogleServiceAccount, OAuthApp, OAuthCredential

    result = {
        "summary": {"ok": 0, "warn": 0, "error": 0},
        "sections": []
    }

    def add_section(title, icon, issues):
        ok = sum(1 for i in issues if i["level"] == "ok")
        warn = sum(1 for i in issues if i["level"] == "warn")
        err = sum(1 for i in issues if i["level"] == "error")
        status = "error" if err else ("warn" if warn else "ok")
        result["summary"]["ok"]    += ok
        result["summary"]["warn"]  += warn
        result["summary"]["error"] += err
        result["sections"].append({"title": title, "icon": icon, "status": status,
                                   "ok": ok, "warn": warn, "error": err, "issues": issues})

    # ── General ──────────────────────────────────────────────────────────────
    from apps.companies.models import Company
    gen_issues = []
    co_count = Company.objects.count()
    if co_count == 0:
        gen_issues.append({"level": "error", "msg": "No companies configured — create your MC companies first", "fix": FIXES["no_companies"]})
    else:
        gen_issues.append({"level": "ok", "msg": f"{co_count} company/companies configured"})

    mb_count = MailboxSettings.objects.filter(is_active=True).count()
    if mb_count == 0:
        gen_issues.append({"level": "warn", "msg": "No mailboxes configured — add at least one mailbox to receive emails", "fix": FIXES["no_mailboxes"]})
    else:
        gen_issues.append({"level": "ok", "msg": f"{mb_count} mailbox(es) configured"})

    # Check Celery worker
    try:
        from config.celery import app as celery_app
        inspect = celery_app.control.inspect(timeout=2.0)
        active = inspect.active()
        if active:
            gen_issues.append({"level": "ok", "msg": f"Celery worker running ({len(active)} worker(s))"})
        else:
            gen_issues.append({"level": "error", "msg": "Celery worker not responding — email classification and push notifications disabled", "fix": FIXES["worker_down"]})
    except Exception:
        gen_issues.append({"level": "warn", "msg": "Could not check Celery worker status"})

    # Check Pub/Sub topic
    from django.conf import settings as ds
    pubsub_topic = getattr(ds, "GOOGLE_PUBSUB_TOPIC", "")
    if pubsub_topic:
        gen_issues.append({"level": "ok", "msg": f"Pub/Sub topic configured: {pubsub_topic}"})
        # Check if any mailbox has an active watch
        active_watches = MailboxSettings.objects.filter(watch_status="active").count()
        if active_watches:
            gen_issues.append({"level": "ok", "msg": f"{active_watches} mailbox(es) have active Gmail watch — new emails arrive automatically"})
        else:
            gen_issues.append({"level": "warn", "msg": "No active Gmail watches — new emails won't arrive automatically",
                "fix": "Go to Admin → Credentials → Mailboxes → click REGISTER WATCH next to each connected mailbox. "
                       "Also make sure your Pub/Sub push subscription endpoint in GCP is set to: "
                       "https://YOUR-NGROK-URL/webhooks/google/gmail/push"})
    else:
        gen_issues.append({"level": "warn", "msg": "GOOGLE_PUBSUB_TOPIC not set in .env — Gmail watch/push notifications won't work",
            "fix": "Add to .env: GOOGLE_PUBSUB_TOPIC=projects/YOUR-PROJECT-ID/topics/gmail-dispatch-push  |  Then in GCP: Pub/Sub → Subscriptions → Create → Push → endpoint: https://YOUR-URL/webhooks/google/gmail/push"})

    add_section("System", "⚙️", gen_issues)

    # ── Service Accounts (Workspace) ─────────────────────────────────────────
    sa_issues = []
    accounts = list(GoogleServiceAccount.objects.filter(is_active=True).prefetch_related("mailboxes"))
    if not accounts:
        sa_issues.append({"level": "info", "msg": "No service accounts configured (only needed for Google Workspace domains you own)"})
    else:
        for sa in accounts:
            sa_issues.extend(_check_gmail_sa(sa, list(sa.mailboxes.filter(is_active=True))))
    add_section("Gmail — Service Accounts (Workspace)", "🏢", sa_issues)

    # ── OAuth App ─────────────────────────────────────────────────────────────
    oauth_issues = []
    oauth_app = OAuthApp.get_active()
    if not oauth_app or not oauth_app.has_credentials:
        oauth_issues.append({"level": "warn", "msg": "OAuth app not configured — personal Gmail accounts cannot be connected", "fix": FIXES["no_oauth_app"]})
    else:
        oauth_issues.append({"level": "ok", "msg": f"OAuth app configured: {oauth_app.client_id[:30]}…"})
        oauth_issues.append({"level": "ok", "msg": f"Redirect URI: {oauth_app.redirect_uri}"})

    add_section("Gmail — OAuth 2.0 App (Personal Gmail)", "🔑", oauth_issues)

    # ── Mailboxes ─────────────────────────────────────────────────────────────
    mb_issues = []
    mailboxes = list(MailboxSettings.objects.filter(is_active=True).select_related(
        "company", "service_account", "oauth_credential"
    ))
    if not mailboxes:
        mb_issues.append({"level": "warn", "msg": "No mailboxes configured", "fix": FIXES["no_mailboxes"]})
    else:
        for mb in mailboxes:
            mb_issues.extend(_check_mailbox(mb))
    add_section("Mailboxes", "📬", mb_issues)

    # ── Slack ─────────────────────────────────────────────────────────────────
    add_section("Slack", "💬", _check_slack())

    # Overall status
    result["overall"] = "error" if result["summary"]["error"] > 0 else ("warn" if result["summary"]["warn"] > 0 else "ok")
    return Response(result)


@api_view(["POST"])
def slack_send_test(request):
    """Send a test message to ALL configured Slack channels at once."""
    s = SlackSettings.get()
    if not s.bot_token_set:
        return Response({"ok": False, "error": "No bot token. Save it in the Slack tab first.", "fix": FIXES["no_slack_token"]}, status=400)
    results = {}
    channels = {
        "safety":     (s.channel_safety,    s.channel_safety_name),
        "approvals":  (s.channel_approvals, s.channel_approvals_name),
        "compliance": (s.channel_compliance,s.channel_compliance_name),
        "system":     (s.channel_system,    s.channel_system_name),
    }
    try:
        from slack_sdk import WebClient
        from apps.core.error_utils import parse_slack_error
        client = WebClient(token=s.bot_token)
        for key, (ch_id, ch_name) in channels.items():
            if not ch_id:
                results[key] = {"ok": False, "error": "Channel ID not set", "fix": FIXES["no_channel"]}
                continue
            try:
                client.chat_postMessage(
                    channel=ch_id,
                    text=f"✅ *Dispatch OS* — test message for *{ch_name or key}* channel. Configuration verified."
                )
                results[key] = {"ok": True, "channel": ch_name or ch_id}
            except Exception as e:
                msg = parse_slack_error(e)
                fix = FIXES["bot_not_in_channel"] if "not_in_channel" in str(e) else FIXES["no_channel"]
                results[key] = {"ok": False, "error": msg, "fix": fix}
    except Exception as e:
        from apps.core.error_utils import parse_slack_error
        return Response({"ok": False, "error": parse_slack_error(e), "fix": FIXES["slack_token_bad"]}, status=400)

    all_ok = all(v["ok"] for v in results.values() if "error" not in v or v.get("ok"))
    return Response({"ok": all_ok, "channels": results})
