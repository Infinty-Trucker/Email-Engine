from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="slack_channel_loads_id",
            field=models.CharField(blank=True, help_text="Slack channel ID for load-ops alerts", max_length=50),
        ),
        migrations.AddField(
            model_name="company",
            name="slack_channel_loads_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="company",
            name="slack_channel_paperwork_id",
            field=models.CharField(blank=True, help_text="Slack channel ID for paperwork-ops alerts", max_length=50),
        ),
        migrations.AddField(
            model_name="company",
            name="slack_channel_paperwork_name",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
