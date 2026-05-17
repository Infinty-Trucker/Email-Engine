from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("settings", "0002_mailboxsettings_pubsub_topic"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthcredential",
            name="oauth_app",
            field=models.ForeignKey(
                blank=True,
                help_text="Which OAuth app issued this token. Required for refresh.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="credentials",
                to="settings.oauthapp",
            ),
        ),
    ]
