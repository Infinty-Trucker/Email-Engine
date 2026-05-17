from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("settings", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="mailboxsettings",
            name="pubsub_topic",
            field=models.CharField(
                blank=True,
                help_text="Per-mailbox Pub/Sub topic override. Falls back to SA topic or GOOGLE_PUBSUB_TOPIC env var.",
                max_length=300,
            ),
        ),
    ]
