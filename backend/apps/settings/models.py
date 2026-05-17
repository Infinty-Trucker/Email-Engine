"""
apps/settings/models.py — supports both Service Account AND OAuth 2.0
"""
import uuid, base64, json
from django.db import models
from django.conf import settings as django_settings


def _fernet():
    from cryptography.fernet import Fernet
    import hashlib
    key = hashlib.sha256(django_settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))

def encrypt(value):
    if not value: return ""
    return _fernet().encrypt(value.encode()).decode()

def decrypt(value):
    if not value: return ""
    try: return _fernet().decrypt(value.encode()).decode()
    except: return ""


class SlackSettings(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    _bot_token = models.TextField(blank=True, db_column="bot_token")
    channel_safety = models.CharField(max_length=50, blank=True)
    channel_approvals = models.CharField(max_length=50, blank=True)
    channel_compliance = models.CharField(max_length=50, blank=True)
    channel_system = models.CharField(max_length=50, blank=True)
    channel_safety_name = models.CharField(max_length=100, blank=True)
    channel_approvals_name = models.CharField(max_length=100, blank=True)
    channel_compliance_name = models.CharField(max_length=100, blank=True)
    channel_system_name = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta: verbose_name = "Slack Settings"

    @property
    def bot_token(self): return decrypt(self._bot_token)
    @bot_token.setter
    def bot_token(self, v): self._bot_token = encrypt(v)
    @property
    def bot_token_set(self): return bool(self._bot_token)
    @property
    def bot_token_preview(self):
        t = self.bot_token
        return (t[:12] + "••••••••••••••••••••") if t else ""
    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk="00000000-0000-0000-0000-000000000001")
        return obj


class GoogleServiceAccount(models.Model):
    """Service account JSON key — for Google Workspace domains you OWN."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    domain = models.CharField(max_length=200, help_text="e.g. rwfreight.com")
    _json_data = models.TextField(blank=True, db_column="json_data")
    pubsub_topic = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_error = models.TextField(blank=True)

    @property
    def json_data(self):
        raw = decrypt(self._json_data)
        try: return json.loads(raw) if raw else {}
        except: return {}
    @json_data.setter
    def json_data(self, v): self._json_data = encrypt(json.dumps(v) if isinstance(v, dict) else v)
    @property
    def has_credentials(self):
        # Encrypted blob exists AND it parses to a dict with the required SA fields.
        if not self._json_data:
            return False
        d = self.json_data
        return bool(d) and isinstance(d, dict) and "client_email" in d and "private_key" in d
    @property
    def client_email(self): return self.json_data.get("client_email","")
    @property
    def project_id(self): return self.json_data.get("project_id","")
    def __str__(self): return f"{self.name} ({self.domain})"


class SlackChannelRegistry(models.Model):
    """Admin-managed list of Slack channels available for assignment to companies."""
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True, help_text="Channel name without #, e.g. 'rw-load-ops'")
    channel_id = models.CharField(max_length=50, blank=True, help_text="Auto-resolved when bot can reach it")
    is_private = models.BooleanField(default=False)
    description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"#{self.name}"


class OAuthApp(models.Model):
    """OAuth 2.0 client credentials from GCP Console — configured once."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, default="Dispatch OS Gmail OAuth")
    client_id = models.TextField(blank=True)
    _client_secret = models.TextField(blank=True, db_column="client_secret")
    redirect_uri = models.CharField(max_length=500, blank=True,
        help_text="Must match GCP Console exactly, e.g. http://localhost:8000/api/settings/oauth/callback/")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def client_secret(self): return decrypt(self._client_secret)
    @client_secret.setter
    def client_secret(self, v): self._client_secret = encrypt(v)
    @property
    def has_credentials(self): return bool(self.client_id and self._client_secret)
    @classmethod
    def get_active(cls): return cls.objects.filter(is_active=True).first()
    def __str__(self): return self.name


class OAuthCredential(models.Model):
    """
    Per-mailbox OAuth 2.0 refresh token.
    Used for personal @gmail.com or third-party domain emails.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email_address = models.EmailField(unique=True)
    oauth_app = models.ForeignKey(OAuthApp, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="credentials",
        help_text="Which OAuth app issued this token. Required for refresh.")
    _refresh_token = models.TextField(blank=True, db_column="refresh_token")
    _access_token = models.TextField(blank=True, db_column="access_token")
    token_expiry = models.DateTimeField(null=True, blank=True)
    is_valid = models.BooleanField(default=True)
    last_error = models.TextField(blank=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def refresh_token(self): return decrypt(self._refresh_token)
    @refresh_token.setter
    def refresh_token(self, v): self._refresh_token = encrypt(v)
    @property
    def access_token(self): return decrypt(self._access_token)
    @access_token.setter
    def access_token(self, v): self._access_token = encrypt(v)
    @property
    def has_credentials(self): return bool(self._refresh_token)
    def __str__(self): return f"OAuth: {self.email_address}"


class MailboxSettings(models.Model):
    """One row per MC email. auth_method picks which credential is used."""
    AUTH_SA    = "service_account"
    AUTH_OAUTH = "oauth"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey("companies.Company", on_delete=models.CASCADE, related_name="mailbox_settings")
    email_address = models.EmailField(unique=True)
    display_name = models.CharField(max_length=200, blank=True)
    purpose = models.CharField(max_length=50, blank=True,
        choices=[("dispatch","Dispatch"),("safety","Safety"),("billing","Billing"),("general","General")],
        default="dispatch")
    auth_method = models.CharField(max_length=20,
        choices=[(AUTH_SA,"Service Account (Workspace)"),(AUTH_OAUTH,"OAuth 2.0 (Gmail / any domain)")],
        default=AUTH_OAUTH)
    service_account = models.ForeignKey(GoogleServiceAccount, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="mailboxes")
    oauth_credential = models.OneToOneField(OAuthCredential, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="mailbox")
    watch_status = models.CharField(max_length=20, default="inactive",
        choices=[("active","Active"),("inactive","Inactive"),("error","Error"),("expired","Expired")])
    last_history_id = models.CharField(max_length=50, blank=True)
    watch_expiry = models.DateTimeField(null=True, blank=True)
    watch_error = models.TextField(blank=True)
    pubsub_topic = models.CharField(max_length=300, blank=True,
        help_text="Per-mailbox Pub/Sub topic override. Falls back to SA topic or GOOGLE_PUBSUB_TOPIC env var.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["company__name", "email_address"]

    @property
    def is_authorized(self):
        if self.auth_method == self.AUTH_SA:
            return bool(self.service_account and self.service_account.has_credentials)
        return bool(self.oauth_credential and self.oauth_credential.has_credentials)

    def __str__(self): return f"{self.email_address} ({self.company.name})"
