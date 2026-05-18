import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('companies', '0004_company_slack_alerts_enabled'),
        ('conversations', '0008_conversation_mc_number_cached'),
    ]

    operations = [
        migrations.CreateModel(
            name='MailRule',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=150)),
                ('description', models.TextField(blank=True, default='')),
                ('sender_pattern', models.CharField(max_length=300)),
                ('subject_pattern', models.CharField(blank=True, default='', max_length=300)),
                ('require_attachment', models.BooleanField(default=False)),
                ('attachment_mime_prefix', models.CharField(blank=True, default='', max_length=100)),
                ('action', models.CharField(
                    choices=[('phoenix_capital_schedule', 'Phoenix Capital factoring schedule')],
                    max_length=64,
                )),
                ('action_config', models.JSONField(blank=True, default=dict)),
                ('enabled', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='mail_rules',
                    to='companies.company',
                )),
            ],
            options={'ordering': ['company__mc_number', 'name']},
        ),
        migrations.AddIndex(
            model_name='mailrule',
            index=models.Index(fields=['enabled'], name='mail_rule_enabled_idx'),
        ),
        migrations.CreateModel(
            name='MailRuleExecution',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(
                    choices=[('success', 'Success'), ('failed', 'Failed'), ('skipped', 'Skipped')],
                    max_length=10,
                )),
                ('response_summary', models.TextField(blank=True, default='')),
                ('error', models.TextField(blank=True, default='')),
                ('attempted_at', models.DateTimeField(auto_now_add=True)),
                ('rule', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='executions',
                    to='automations.mailrule',
                )),
                ('message', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='automation_executions',
                    to='conversations.message',
                )),
            ],
            options={'ordering': ['-attempted_at']},
        ),
        migrations.AddConstraint(
            model_name='mailruleexecution',
            constraint=models.UniqueConstraint(
                fields=('rule', 'message'),
                name='unique_rule_message_execution',
            ),
        ),
    ]
