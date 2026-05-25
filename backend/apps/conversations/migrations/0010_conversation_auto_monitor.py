from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("conversations", "0009_conversation_related_load_id"),
    ]

    operations = [
        # Per-thread opt-in for AI follow-up alerts. The beat task scans only
        # rows with auto_monitor=True so we don't burn tokens on the entire
        # inbox by default. Indexed because the monitor task filters by
        # (auto_monitor, last_message_at).
        migrations.AddField(
            model_name="conversation",
            name="auto_monitor",
            field=models.BooleanField(default=False, db_index=True),
        ),
        # Throttle marker for the follow-up Slack alert. Set to now() whenever
        # the beat task posts a draft so we don't re-spam Slack every 2 min
        # for the same stale outbound message.
        migrations.AddField(
            model_name="conversation",
            name="last_followup_alert_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
