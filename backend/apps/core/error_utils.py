"""
apps/core/error_utils.py

Translates raw Google, Slack, and Django errors into short, actionable
messages suitable for display in the UI.
"""
import json
import logging
import re

logger = logging.getLogger(__name__)


# ── Google / Gmail errors ──────────────────────────────────────────────────────

GOOGLE_ERROR_MAP = {
    # Auth / delegation
    "invalid_grant":          "OAuth token expired or revoked. Click Connect OAuth to re-authorize this mailbox.",
    "unauthorized_client":    "Domain-wide delegation not set up. Go to Google Workspace Admin → Security → Domain-wide Delegation and add the service account Client ID with gmail.modify and gmail.send scopes.",
    "access_denied":          "Access denied. The user may have clicked Deny on the consent screen, or the Gmail address wasn't added as a test user in your OAuth consent screen.",
    "invalid_client":         "Invalid OAuth client credentials. Check your Client ID and Client Secret in Credentials → OAuth App.",
    "redirect_uri_mismatch":  "Redirect URI mismatch. The URI in GCP Console must match exactly what's saved in Dispatch OS — check for trailing slashes and http vs https.",
    "insufficientPermissions":"Gmail API scopes not granted. Ensure gmail.modify and gmail.send scopes are authorized.",
    "forbidden":              "Permission denied by Gmail. Check that domain-wide delegation is configured correctly in Google Workspace Admin.",
    "notFound":               "Gmail resource not found. The message or thread may have been deleted.",
    "quotaExceeded":          "Gmail API quota exceeded. Requests are temporarily rate-limited — Dispatch OS will retry automatically.",
    "rateLimitExceeded":      "Gmail rate limit exceeded. Dispatch OS will retry automatically in a few seconds.",
    "backendError":           "Temporary Gmail API error. Dispatch OS will retry automatically.",
    "serviceNotAvailable":    "Gmail API is temporarily unavailable. This is a Google outage — please try again in a few minutes.",
    "dailyLimitExceeded":     "Gmail API daily quota exceeded. This resets at midnight Pacific time.",
    "domainPolicy":           "Blocked by domain policy. A Google Workspace admin has restricted this API access.",
    "conditionNotMet":        "Gmail watch condition not met. The mailbox may already have a watch registered — try stopping and re-registering the watch.",
    400:                      "Bad request sent to Gmail API — the Pub/Sub topic name may be wrong, or gmail-api-push@system.gserviceaccount.com needs Pub/Sub Publisher role on the topic. Check GCP → Pub/Sub → Topics → Permissions.",
    401:                      "Not authenticated with Gmail. The service account key may be invalid or expired — try re-uploading the JSON key.",
    403:                      "Gmail access forbidden. Either domain-wide delegation is not set up, or the service account doesn't have permission to access this mailbox.",
    404:                      "Gmail mailbox not found. Verify the email address exists and is accessible.",
    429:                      "Gmail API rate limit hit. Dispatch OS will retry automatically.",
    500:                      "Gmail API server error. This is a Google-side issue — Dispatch OS will retry automatically.",
    503:                      "Gmail API temporarily unavailable. Dispatch OS will retry automatically.",
}

# ── Slack errors ───────────────────────────────────────────────────────────────

SLACK_ERROR_MAP = {
    "invalid_auth":           "Invalid Slack token. Re-paste the Bot User OAuth Token from api.slack.com/apps → your app → OAuth & Permissions.",
    "not_authed":             "No Slack token provided. Paste the xoxb- token in the Slack tab and click Save Token.",
    "token_revoked":          "Slack token has been revoked. Re-install the app in your Slack workspace and copy the new token.",
    "not_in_channel":         "The Dispatch OS bot is not in this channel. Open the channel in Slack → channel name → Integrations → Add an App → Dispatch OS.",
    "channel_not_found":      "Slack channel not found. The Channel ID may be wrong — right-click the channel in Slack → View channel details → scroll to the bottom to copy the ID.",
    "is_archived":            "This Slack channel is archived. Unarchive it or choose a different channel.",
    "msg_too_long":           "Message too long for Slack. This is an internal error — contact support.",
    "no_text":                "Empty message sent to Slack. This is an internal error.",
    "rate_limited":           "Slack rate limit hit. Dispatch OS will retry automatically.",
    "missing_scope":          "The Slack bot is missing required permissions. Go to api.slack.com/apps → your app → OAuth & Permissions → add scopes: chat:write, channels:read, groups:read, channels:join → reinstall the app.",
    "account_inactive":       "Slack account is inactive. Check your Slack workspace subscription.",
    "org_login_required":     "Slack requires org-level login. Contact your Slack Enterprise Grid admin.",
    "ekm_access_denied":      "Slack Enterprise Key Management blocked this request. Contact your Slack admin.",
    "fatal_error":            "Slack internal error. This is a Slack-side issue — please try again.",
    "app_rate_limited":       "Slack app rate limit hit. Dispatch OS will retry automatically.",
}

# ── Pub/Sub errors ────────────────────────────────────────────────────────────

PUBSUB_ERROR_MAP = {
    "PERMISSION_DENIED":      "Pub/Sub permission denied. Make sure gmail-api-push@system.gserviceaccount.com has been granted the Pub/Sub Publisher role on your topic.",
    "NOT_FOUND":              "Pub/Sub topic not found. Check the topic path format: projects/{project_id}/topics/{topic_name}",
    "ALREADY_EXISTS":         "A Gmail watch is already registered for this mailbox. Stop the existing watch first, then register again.",
    "RESOURCE_EXHAUSTED":     "Pub/Sub quota exceeded. Check your GCP project quotas.",
    "UNAUTHENTICATED":        "Not authenticated with Pub/Sub. Check the service account JSON key is valid.",
    "INVALID_ARGUMENT":       "Invalid Pub/Sub argument. Check the topic name format: projects/{project_id}/topics/{topic_name}",
}


def parse_google_error(exc) -> str:
    """Extract a human-readable message from a Google API exception."""
    raw = str(exc)

    # googleapiclient.errors.HttpError
    try:
        from googleapiclient.errors import HttpError
        if isinstance(exc, HttpError):
            status = exc.resp.status
            try:
                content = json.loads(exc.content.decode("utf-8"))
                reason  = content.get("error", {}).get("errors", [{}])[0].get("reason", "")
                message = content.get("error", {}).get("message", "")
                # Check reason map first
                if reason in GOOGLE_ERROR_MAP:
                    return GOOGLE_ERROR_MAP[reason]
                # Check status map
                if status in GOOGLE_ERROR_MAP:
                    return GOOGLE_ERROR_MAP[status]
                # Always include raw message to help debugging
                if message:
                    if reason:
                        return f"Gmail API error ({reason}): {message}"
                    return f"Gmail API error: {message}"
            except Exception:
                pass
            return GOOGLE_ERROR_MAP.get(status, f"Gmail API error (HTTP {status}). Check your credentials and try again.")
    except ImportError:
        pass

    # google.auth exceptions
    if "invalid_grant" in raw:
        return GOOGLE_ERROR_MAP["invalid_grant"]
    if "unauthorized_client" in raw:
        return GOOGLE_ERROR_MAP["unauthorized_client"]
    if "access_denied" in raw:
        return GOOGLE_ERROR_MAP["access_denied"]
    if "invalid_client" in raw:
        return GOOGLE_ERROR_MAP["invalid_client"]
    if "redirect_uri_mismatch" in raw:
        return GOOGLE_ERROR_MAP["redirect_uri_mismatch"]

    # Pub/Sub gRPC errors
    for code, msg in PUBSUB_ERROR_MAP.items():
        if code in raw:
            return msg

    # Service account file errors
    if "No such file or directory" in raw:
        return "Service account JSON file not found. Upload the key file in Credentials → Gmail → Service Accounts → Upload Key."
    if "Could not deserialize key data" in raw or "Invalid key" in raw:
        return "Invalid service account JSON key. Re-download the key from GCP Console → IAM → Service Accounts → Keys."
    if "subject must be a valid email" in raw.lower():
        return "Invalid mailbox email address for impersonation. Check the email address is correct."

    # Generic fallback — strip internal paths from the message
    clean = re.sub(r'/[^\s]+\.py:\d+', '', raw)
    clean = re.sub(r'\s+', ' ', clean).strip()
    if len(clean) > 300:
        clean = clean[:297] + "..."
    return clean or "An unexpected Google API error occurred."


def parse_slack_error(exc) -> str:
    """Extract a human-readable message from a Slack SDK exception."""
    raw = str(exc)

    # SlackApiError has .response with error code
    try:
        from slack_sdk.errors import SlackApiError
        if isinstance(exc, SlackApiError):
            code = exc.response.get("error", "")
            if code in SLACK_ERROR_MAP:
                return SLACK_ERROR_MAP[code]
            return f"Slack error: {code}. Check your token and channel settings."
    except ImportError:
        pass

    # String matching fallback
    for code, msg in SLACK_ERROR_MAP.items():
        if code in raw:
            return msg

    clean = re.sub(r'\s+', ' ', raw).strip()
    return clean[:300] if clean else "An unexpected Slack error occurred."


def parse_error(exc, context: str = "") -> str:
    """
    Universal error parser. Detects error type and returns a clean message.
    context: short string like "sending email" or "registering watch"
    """
    try:
        from googleapiclient.errors import HttpError
        if isinstance(exc, HttpError):
            msg = parse_google_error(exc)
            return f"Failed {context}: {msg}" if context else msg
    except ImportError:
        pass

    try:
        from google.auth.exceptions import GoogleAuthError, TransportError
        if isinstance(exc, (GoogleAuthError, TransportError)):
            msg = parse_google_error(exc)
            return f"Authentication error {context}: {msg}" if context else msg
    except ImportError:
        pass

    try:
        from slack_sdk.errors import SlackApiError
        if isinstance(exc, SlackApiError):
            msg = parse_slack_error(exc)
            return f"Slack error {context}: {msg}" if context else msg
    except ImportError:
        pass

    raw = str(exc)
    if any(x in raw for x in ["invalid_grant", "unauthorized_client", "redirect_uri_mismatch"]):
        return parse_google_error(exc)

    # Django / DB errors
    if "unique constraint" in raw.lower() or "already exists" in raw.lower():
        return "This email address is already configured. Each mailbox can only be added once."
    if "connection refused" in raw.lower() or "could not connect" in raw.lower():
        return "Database connection error. Check that the database service is running."

    # Network errors
    if "timeout" in raw.lower():
        return f"Request timed out{' while ' + context if context else ''}. Check your internet connection and try again."
    if "connection reset" in raw.lower() or "connection aborted" in raw.lower():
        return "Network connection lost. Check your internet connection and try again."

    # Clean up and return
    clean = re.sub(r'\s+', ' ', raw).strip()
    if len(clean) > 300:
        clean = clean[:297] + "..."
    return (f"Error {context}: " if context else "") + (clean or "An unexpected error occurred.")


def log_and_respond(exc, context: str, logger_instance=None, status=400):
    """Helper for views: log the real error, return clean message to client."""
    from rest_framework.response import Response
    _logger = logger_instance or logger
    _logger.error("%s failed: %s", context, exc, exc_info=True)
    msg = parse_error(exc, context)
    return Response({"error": msg}, status=status)
