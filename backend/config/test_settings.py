"""Hermetic settings for the Email-Engine (Dispatch OS) test suite.

Swaps every external dependency (Postgres, Redis/Celery, SMTP, S3) for an
in-process equivalent so `manage.py test` runs with no running services.

Run with:
    python manage.py test --settings=config.test_settings
"""
from config.settings import *  # noqa: F401,F403

# --- Database: in-memory sqlite ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# --- Cache: local memory ---
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# --- Celery: queue to memory, don't execute side-effect tasks inline ---
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# --- Email collected in memory ---
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# --- Fast password hashing ---
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# --- Never touch S3 ---
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEBUG = False
