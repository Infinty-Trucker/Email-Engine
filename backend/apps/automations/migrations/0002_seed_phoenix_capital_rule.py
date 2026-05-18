"""Seed the global Phoenix Capital factoring rule.

Creates one company-less (global) rule that matches every inbound message
from ``mailrelay@phoenixcapitalgroup.com`` whose subject looks like
``Schedule #XYZ`` and that has a PDF attachment. The dispatcher resolves
the tenant from the mailbox the message landed in.

If a row with the same name already exists (e.g. re-running migrations on
a populated db) we leave it alone.
"""

from django.db import migrations


PHX_RULE = {
    "name": "Phoenix Capital schedule auto-import",
    "description": (
        "Inbound emails from mailrelay@phoenixcapitalgroup.com with "
        "subject 'Schedule #NNN' and a PDF attachment are auto-forwarded "
        "to TMS-Backend so the factoring schedule is parsed and applied "
        "to each load's invoice."
    ),
    "sender_pattern": r"^mailrelay@phoenixcapitalgroup\.com$",
    "subject_pattern": r"^\s*Schedule\s*#\s*\d+\s*$",
    "require_attachment": True,
    "attachment_mime_prefix": "application/pdf",
    "action": "phoenix_capital_schedule",
    "action_config": {},
    "enabled": True,
    "company": None,
}


def seed_phoenix_rule(apps, schema_editor):
    MailRule = apps.get_model("automations", "MailRule")
    if not MailRule.objects.filter(name=PHX_RULE["name"]).exists():
        MailRule.objects.create(**PHX_RULE)


def unseed_phoenix_rule(apps, schema_editor):
    MailRule = apps.get_model("automations", "MailRule")
    MailRule.objects.filter(name=PHX_RULE["name"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_phoenix_rule, unseed_phoenix_rule),
    ]
