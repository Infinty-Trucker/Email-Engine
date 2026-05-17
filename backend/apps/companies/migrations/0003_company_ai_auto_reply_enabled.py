from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0002_add_slack_channels"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="ai_auto_reply_enabled",
            field=models.BooleanField(
                default=False,
                help_text="If true, the AI agent will auto-reply to routine emails that don't need human decisions.",
            ),
        ),
    ]
