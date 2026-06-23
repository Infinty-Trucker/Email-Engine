"""Rename the legacy AUDIT category to the broadened COMPLIANCE bucket.

COMPLIANCE now covers FMCSA/DOT audits *and* the rest of regulatory ops
(IFTA, permits, registration, UCR, 2290, ELD/HOS, Clearinghouse). Existing
rows tagged AUDIT are all valid COMPLIANCE, so this is a straight relabel on
both the Conversation denormalized column and the Classification rows.

RunPython (not RunSQL) so the sqlite test suite doesn't choke on vendor SQL.
"""

from django.db import migrations


def audit_to_compliance(apps, schema_editor):
    Conversation = apps.get_model("conversations", "Conversation")
    Classification = apps.get_model("classifier", "Classification")
    Conversation.objects.filter(category="AUDIT").update(category="COMPLIANCE")
    Classification.objects.filter(category="AUDIT").update(category="COMPLIANCE")


def compliance_to_audit(apps, schema_editor):
    # Best-effort reverse — lossy, since new COMPLIANCE rows may not be audits.
    Conversation = apps.get_model("conversations", "Conversation")
    Classification = apps.get_model("classifier", "Classification")
    Conversation.objects.filter(category="COMPLIANCE").update(category="AUDIT")
    Classification.objects.filter(category="COMPLIANCE").update(category="AUDIT")


class Migration(migrations.Migration):

    dependencies = [
        ("conversations", "0011_message_channel_post_id"),
        ("classifier", "0003_classification_subcategory"),
    ]

    operations = [
        migrations.RunPython(audit_to_compliance, compliance_to_audit),
    ]
