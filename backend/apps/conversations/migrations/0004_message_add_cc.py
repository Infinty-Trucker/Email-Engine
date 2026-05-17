from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0003_add_attachment_model"),
    ]
    operations = [
        migrations.AddField(
            model_name="message",
            name="cc",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
    ]
