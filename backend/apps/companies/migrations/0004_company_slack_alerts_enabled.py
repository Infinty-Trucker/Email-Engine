from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0003_company_ai_auto_reply_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="slack_alerts_enabled",
            field=models.BooleanField(
                default=False,
                help_text="If true, Dispatch OS will post urgent and hourly digest alerts to this company's Slack channels.",
            ),
        ),
    ]
