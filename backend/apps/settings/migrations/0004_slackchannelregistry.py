import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("settings", "0003_oauthcredential_oauth_app"),
    ]

    operations = [
        migrations.CreateModel(
            name="SlackChannelRegistry",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(help_text="Channel name without #, e.g. 'rw-load-ops'", max_length=100, unique=True)),
                ("channel_id", models.CharField(blank=True, help_text="Auto-resolved when bot can reach it", max_length=50)),
                ("is_private", models.BooleanField(default=False)),
                ("description", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
    ]
