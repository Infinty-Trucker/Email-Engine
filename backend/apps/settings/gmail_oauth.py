"""
apps/settings/gmail_oauth.py

Gmail client that works for BOTH auth methods:
  - Service Account  → Google Workspace domains you control
  - OAuth 2.0        → Personal Gmail or any other domain

Usage:
    svc = get_gmail_service(mailbox)   # auto-picks the right method
    svc.users().messages().list(userId="me").execute()
"""
import json
import logging
import tempfile
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def get_gmail_service(mailbox_settings):
    """Return an authenticated Gmail API service for this mailbox."""
    if mailbox_settings.auth_method == "service_account":
        return _service_account_service(mailbox_settings)
    else:
        return _oauth_service(mailbox_settings)


def _service_account_service(mailbox_settings):
    """Build Gmail service using service account + domain-wide delegation."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    sa = mailbox_settings.service_account
    if not sa:
        raise ValueError(
            f"Mailbox {mailbox_settings.email_address} is set to use a Service Account "
            "but no Service Account is linked. Edit the mailbox in Admin → Credentials → "
            "Mailboxes and pick a Service Account from the dropdown."
        )
    sa_data = sa.json_data
    if not sa_data or not isinstance(sa_data, dict):
        raise ValueError(
            f"Service Account '{sa.name}' has no JSON key uploaded. "
            "Go to Admin → Credentials → Service Accounts → '{sa.name}' → Upload JSON Key. "
            "Download the key from Google Cloud Console → IAM → Service Accounts → Keys."
        )
    required = {"client_email", "token_uri", "private_key"}
    missing = required - set(sa_data.keys())
    if missing:
        raise ValueError(
            f"Service Account '{sa.name}' JSON is malformed (missing: {', '.join(sorted(missing))}). "
            "Re-download the JSON key from Google Cloud Console and re-upload it."
        )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sa_data, f)
        tmp = f.name
    try:
        creds = service_account.Credentials.from_service_account_file(
            tmp, scopes=SCOPES
        ).with_subject(mailbox_settings.email_address)
        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    finally:
        os.unlink(tmp)


def _oauth_service(mailbox_settings):
    """Build Gmail service using stored OAuth 2.0 refresh token."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from apps.settings.models import OAuthApp

    cred = mailbox_settings.oauth_credential
    if not cred or not cred.has_credentials:
        raise ValueError(
            f"No OAuth credentials for {mailbox_settings.email_address}. "
            "The mailbox owner needs to connect their account via the Admin UI."
        )
    # Use the exact OAuth app that issued this token. Falling back to
    # get_active() would use a different app's client_id/secret and Google
    # would reject the refresh with `unauthorized_client`.
    oauth_app = cred.oauth_app or OAuthApp.get_active()
    if not oauth_app or not oauth_app.has_credentials:
        raise ValueError("OAuth app not configured. Add Client ID and Client Secret in Admin UI → Gmail → OAuth App.")

    google_creds = Credentials(
        token=cred.access_token or None,
        refresh_token=cred.refresh_token,
        client_id=oauth_app.client_id,
        client_secret=oauth_app.client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )

    # Refresh if expired or missing
    if not google_creds.valid:
        try:
            google_creds.refresh(Request())
            # Save updated tokens
            cred.access_token = google_creds.token
            if google_creds.expiry:
                cred.token_expiry = google_creds.expiry.replace(tzinfo=timezone.utc) if google_creds.expiry.tzinfo is None else google_creds.expiry
            cred.is_valid = True
            cred.last_error = ""
            cred.save()
        except Exception as e:
            cred.is_valid = False
            cred.last_error = str(e)
            cred.save(update_fields=["is_valid", "last_error"])
            raise ValueError(f"OAuth token refresh failed for {mailbox_settings.email_address}: {e}")

    return build("gmail", "v1", credentials=google_creds, cache_discovery=False)


def build_oauth_auth_url(email_address, oauth_app, state=""):
    """Generate the Google OAuth consent URL for this email address."""
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id":     oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
                "redirect_uris": [oauth_app.redirect_uri],
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=oauth_app.redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",           # force refresh_token every time
        login_hint=email_address,   # pre-fill the email
        state=state,
    )
    return auth_url


def exchange_oauth_code(code, oauth_app):
    """Exchange an auth code for access + refresh tokens. Returns token dict."""
    import os
    from google_auth_oauthlib.flow import Flow

    # Allow OAuth over HTTP when running behind ngrok or a reverse proxy
    # that terminates SSL (ngrok forwards HTTPS as HTTP internally)
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id":     oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
                "redirect_uris": [oauth_app.redirect_uri],
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=oauth_app.redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "access_token":  creds.token,
        "refresh_token": creds.refresh_token,
        "expiry":        creds.expiry,
        "email":         _get_email_from_token(creds.token),
    }


def _get_email_from_token(access_token):
    """Get the Gmail address for the token we just received."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        creds = Credentials(token=access_token)
        svc   = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return svc.users().getProfile(userId="me").execute().get("emailAddress", "")
    except Exception:
        return ""


def register_watch(mailbox_settings, pubsub_topic):
    """Register Gmail push watch. Returns {historyId, expiration}."""
    svc = get_gmail_service(mailbox_settings)
    return svc.users().watch(
        userId="me",
        body={"topicName": pubsub_topic, "labelIds": ["INBOX"], "labelFilterBehavior": "INCLUDE"},
    ).execute()


def stop_watch(mailbox_settings):
    """Stop Gmail push watch."""
    try:
        svc = get_gmail_service(mailbox_settings)
        svc.users().stop(userId="me").execute()
    except Exception:
        pass


def get_message(mailbox_settings, message_id):
    svc = get_gmail_service(mailbox_settings)
    return svc.users().messages().get(userId="me", id=message_id, format="full").execute()


def list_history(mailbox_settings, start_history_id):
    svc = get_gmail_service(mailbox_settings)
    results, page_token = [], None
    while True:
        kwargs = {"userId": "me", "startHistoryId": start_history_id, "historyTypes": ["messageAdded"]}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = svc.users().history().list(**kwargs).execute()
        results.extend(resp.get("history", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results
