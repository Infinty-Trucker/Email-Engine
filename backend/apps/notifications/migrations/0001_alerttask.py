import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("companies", "0003_company_ai_auto_reply_enabled"),
        ("conversations", "0005_conversation_stale_alerted"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlertTask",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("team", models.CharField(help_text="load or paperwork", max_length=20)),
                ("urgency", models.CharField(choices=[("urgent", "Urgent"), ("routine", "Routine")], default="routine", max_length=20)),
                ("title", models.CharField(blank=True, max_length=300)),
                ("reason", models.CharField(blank=True, help_text="Why this was marked urgent (if applicable)", max_length=500)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("done", "Done"), ("dismissed", "Dismissed")], default="pending", max_length=20)),
                ("first_alerted_at", models.DateTimeField(blank=True, null=True)),
                ("last_reminded_at", models.DateTimeField(blank=True, null=True)),
                ("alert_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="alert_tasks", to="companies.company")),
                ("conversation", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="alert_task", to="conversations.conversation")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["status", "urgency"], name="notif_alert_status_a4b4e2_idx"),
                    models.Index(fields=["company", "status"], name="notif_alert_company_c9d1f3_idx"),
                ],
            },
        ),
    ]
