from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("conversations", "0004_message_add_cc"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="stale_alerted",
            field=models.BooleanField(default=False),
        ),
    ]
