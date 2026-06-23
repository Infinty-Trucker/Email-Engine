import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        DISPATCHER = "dispatcher", "Dispatcher"
        ACCOUNTANT = "accountant", "Accountant"
        SAFETY     = "safety",     "Safety Officer"
        MANAGER    = "manager",    "Manager"
        ADMIN      = "admin",      "Admin"

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DISPATCHER)
    assigned_companies = models.ManyToManyField("companies.Company", blank=True, related_name="assigned_users")

    # Which categories each role sees in their inbox. Categories map to the
    # carrier back-office function that owns them; INSURANCE is shared between
    # Accounting (COI billing) and Safety & Compliance (coverage/audits).
    ROLE_CATEGORIES = {
        "dispatcher": ["LOAD", "TRACKING", "DRIVER", "GENERAL"],
        "accountant":  ["BILLING", "CLAIMS", "INSURANCE", "GENERAL"],
        "safety":      ["SAFETY", "COMPLIANCE", "INSURANCE", "GENERAL"],
        "manager":     ["LOAD", "TRACKING", "DRIVER", "BILLING", "CLAIMS", "INSURANCE", "SAFETY", "COMPLIANCE", "GENERAL"],
        "admin":       ["LOAD", "TRACKING", "DRIVER", "BILLING", "CLAIMS", "INSURANCE", "SAFETY", "COMPLIANCE", "GENERAL"],
    }

    def save(self, *args, **kwargs):
        # Superusers always get admin role automatically
        if self.is_superuser and self.role == self.Role.DISPATCHER:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def visible_categories(self):
        return self.ROLE_CATEGORIES.get(self.role, ["GENERAL"])

    @property
    def can_approve(self):
        return self.role in ("safety", "manager", "admin")

    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"
