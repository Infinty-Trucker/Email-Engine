from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR.parent / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key")
DEBUG       = env("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

# Refuse to boot in production with insecure defaults
if not DEBUG:
    if SECRET_KEY in ("dev-insecure-key", "change-this-to-any-long-random-string-in-production", ""):
        raise RuntimeError(
            "SECRET_KEY must be set to a strong random value in production. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
        )
    if "*" in ALLOWED_HOSTS:
        raise RuntimeError(
            "ALLOWED_HOSTS cannot contain '*' in production. "
            "Set ALLOWED_HOSTS to a comma-separated list of your actual domains."
        )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "django_celery_beat",
    "django_celery_results",
    # Local apps — order matters: users first (custom AUTH_USER_MODEL)
    "apps.core",
    "apps.users",
    "apps.companies",
    "apps.settings",
    "apps.mailboxes",
    "apps.conversations",
    "apps.classifier",
    "apps.notifications",
    "apps.approvals",
    "apps.auditlog",
    "apps.automations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF    = "config.urls"
AUTH_USER_MODEL = "users.User"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://dispatch:dispatch_secret@db:5432/dispatch_os")
}

REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")
CELERY_BROKER_URL        = REDIS_URL
CELERY_RESULT_BACKEND    = "django-db"
CELERY_ACCEPT_CONTENT    = ["json"]
CELERY_TASK_SERIALIZER   = "json"
CELERY_TIMEZONE          = "America/Chicago"
CELERY_BEAT_SCHEDULER    = "django_celery_beat.schedulers:DatabaseScheduler"
# Route outbound email sends to a high-priority queue so they don't get stuck
# behind thousands of ingest tasks
CELERY_TASK_ROUTES       = {
    "conversations.send_outbound_email": {"queue": "send"},
    "conversations.compliance_audit_scan": {"queue": "send"},
    "notifications.check_stale_conversations": {"queue": "send"},
    "notifications.hourly_task_digest":        {"queue": "send"},
}
CELERY_BEAT_SCHEDULE     = {
    "check-stale-conversations": {
        "task": "notifications.check_stale_conversations",
        "schedule": 120.0,  # every 2 minutes
    },
}

# CORS — wide-open for local dev; restricted to whitelisted domains in production.
CORS_ALLOW_CREDENTIALS = True
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.users.tms_auth.TMSSessionTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES":     ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER":              "apps.core.exception_handler.custom_exception_handler",
}

STATIC_URL   = "/static/"
STATIC_ROOT  = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE     = "America/Chicago"
USE_TZ        = True

FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3000")

GOOGLE_SERVICE_ACCOUNT_FILE = env("GOOGLE_SERVICE_ACCOUNT_FILE", default="secrets/service_account.json")
GOOGLE_PUBSUB_TOPIC         = env("GOOGLE_PUBSUB_TOPIC",         default="")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/gmail.send"]

SLACK_BOT_TOKEN              = env("SLACK_BOT_TOKEN",              default="")
SLACK_CHANNEL_SAFETY_ALERTS  = env("SLACK_CHANNEL_SAFETY_ALERTS",  default="")
SLACK_CHANNEL_APPROVALS      = env("SLACK_CHANNEL_APPROVALS",      default="")
SLACK_CHANNEL_COMPLIANCE     = env("SLACK_CHANNEL_COMPLIANCE",     default="")
SLACK_CHANNEL_SYSTEM         = env("SLACK_CHANNEL_SYSTEM",         default="")

ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
ANTHROPIC_MODEL   = "claude-sonnet-4-20250514"

AWS_ACCESS_KEY_ID       = env("AWS_ACCESS_KEY_ID",       default="")
AWS_SECRET_ACCESS_KEY   = env("AWS_SECRET_ACCESS_KEY",   default="")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="dispatch-os-attachments")
AWS_S3_REGION_NAME      = env("AWS_S3_REGION_NAME",      default="us-east-1")

SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE    = "Lax"
CSRF_COOKIE_HTTPONLY    = False   # JS must read csrftoken cookie

# CSRF trusted origins — extend with env var in production
_default_trusted = [
    "http://localhost:3000", "http://localhost:8000",
    "https://*.ngrok-free.app", "https://*.ngrok-free.dev",
    "https://*.ngrok.io", "https://*.ngrok.app",
]
CSRF_TRUSTED_ORIGINS = _default_trusted + env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Production hardening — only enabled when DEBUG is off and explicitly requested.
# Set USE_HTTPS=True in .env once you're behind HTTPS (nginx terminating TLS, ngrok, etc.).
USE_HTTPS = env("USE_HTTPS", default=False, cast=bool)
if not DEBUG and USE_HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE   = True
    CSRF_COOKIE_SECURE      = True
    SECURE_HSTS_SECONDS     = 31536000   # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD            = True
    SECURE_CONTENT_TYPE_NOSNIFF    = True
    SECURE_REFERRER_POLICY         = "same-origin"
    X_FRAME_OPTIONS                = "DENY"

# Logging — JSON-style structured output to stdout in production
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} [{levelname}] {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "celery": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps":  {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Database connection pooling — keep connections open for 60s instead of
# opening a new one per request (significant perf win for celery workers).
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True


# ── OAuth over HTTP (ngrok / local dev) ───────────────────────────────────────
# ngrok terminates HTTPS externally but forwards HTTP internally.
# This allows google_auth_oauthlib to work without a real SSL cert.
import os as _os
_os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

# ── Media / Attachments ───────────────────────────────────────────────────────
import os as _os
MEDIA_ROOT = _os.path.join(BASE_DIR, "media")
MEDIA_URL  = "/media/"
