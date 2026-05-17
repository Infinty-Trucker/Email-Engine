from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('conversations', '0006_conversation_is_starred_conversation_read_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='preview_sender',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='conversation',
            name='preview_subject',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='conversation',
            name='preview_snippet',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='conversation',
            name='last_message_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
