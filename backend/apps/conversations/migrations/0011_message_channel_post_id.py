from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("conversations", "0010_conversation_auto_monitor"),
    ]

    operations = [
        # Groups the N outbound Messages that come from one channel-post
        # fan-out (dispatcher / driver posts once in a load channel → we send
        # to every distinct broker on the load, each on their own thread).
        # The channel timeline groups by this id so the UI shows the single
        # post once with a "delivered to N brokers" badge instead of N
        # near-duplicate rows. Indexed for the group-by lookup.
        migrations.AddField(
            model_name="message",
            name="channel_post_id",
            field=models.UUIDField(null=True, blank=True, db_index=True),
        ),
    ]
