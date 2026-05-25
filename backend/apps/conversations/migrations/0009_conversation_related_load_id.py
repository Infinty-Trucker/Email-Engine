from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("conversations", "0008_conversation_mc_number_cached"),
    ]

    operations = [
        # Loose link to a TMS load. TMS owns the load record so we store the
        # opaque id as a string rather than FK across services. Indexed so
        # "show every email for load X" stays a single range scan.
        migrations.AddField(
            model_name="conversation",
            name="related_load_id",
            field=models.CharField(max_length=64, blank=True, default="", db_index=True),
        ),
    ]
