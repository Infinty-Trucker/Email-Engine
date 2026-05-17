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

    ROLE_CATEGORIES = {
        "dispatcher": ["LOAD", "DRIVER", "GENERAL"],
        "accountant":  ["BILLING", "CLAIMS", "INSURANCE", "GENERAL"],
        "safety":      ["SAFETY", "AUDIT", "GENERAL"],
        "manager":     ["LOAD", "DRIVER", "BILLING", "CLAIMS", "INSURANCE", "SAFETY", "AUDIT", "GENERAL"],
        "admin":       ["LOAD", "DRIVER", "BILLING", "CLAIMS", "INSURANCE", "SAFETY", "AUDIT", "GENERAL"],
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
