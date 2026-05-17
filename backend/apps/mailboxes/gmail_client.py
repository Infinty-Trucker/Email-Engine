import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2 import service_account
from googleapiclient.discovery import build
from django.conf import settings


def _get_service(mailbox_email):
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=settings.GMAIL_SCOPES,
    ).with_subject(mailbox_email)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def register_watch(mailbox_email, pubsub_topic):
    return _get_service(mailbox_email).users().watch(
        userId="me",
        body={"topicName": pubsub_topic, "labelIds": ["INBOX"], "labelFilterBehavior": "INCLUDE"},
    ).execute()


def stop_watch(mailbox_email):
    _get_service(mailbox_email).users().stop(userId="me").execute()


def list_history(mailbox_email, start_history_id):
    svc = _get_service(mailbox_email)
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


def get_message(mailbox_email, message_id):
    return _get_service(mailbox_email).users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()


def parse_headers(msg):
    h = {x["name"].lower(): x["value"] for x in msg.get("payload", {}).get("headers", [])}
    return {
        "message_id":  h.get("message-id", ""),
        "in_reply_to": h.get("in-reply-to", ""),
        "subject":     h.get("subject", "") or "",
        "from":        h.get("from", ""),
        "to":          h.get("to", ""),
        "date":        h.get("date", ""),
    }


def get_body(msg):
    text, html = "", ""
    def _walk(part):
        nonlocal text, html
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if data:
            decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            if mime == "text/plain": text = decoded
            elif mime == "text/html": html = decoded
        for sub in part.get("parts", []):
            _walk(sub)
    _walk(msg.get("payload", {}))
    return text, html


def send_email(mailbox_email, to, subject, body_text, thread_id=None, in_reply_to=None):
    msg = MIMEMultipart("alternative")
    msg["From"] = mailbox_email
    msg["To"]   = to
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"]  = in_reply_to
    msg.attach(MIMEText(body_text, "plain"))
    raw  = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    return _get_service(mailbox_email).users().messages().send(userId="me", body=body).execute()


def extract_email(from_header):
    if "<" in from_header:
        return from_header.split("<")[1].split(">")[0].strip()
    return from_header.strip()
