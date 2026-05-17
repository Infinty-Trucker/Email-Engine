from django.db import migrations, models


def backfill_mc_number(apps, schema_editor):
    """Populate the denormalized mc_number from the mailbox → company chain.
    Cheap one-shot — runs inside the migration so the column has data before
    the composite index goes live."""
    Conversation = apps.get_model("conversations", "Conversation")
    # Single UPDATE with subquery is far cheaper than iterating rows in Python.
    # Use the ORM's update() with F-style subquery instead of raw SQL so the
    # migration stays portable across the sqlite test runner and prod Postgres.
    from django.db.models import Subquery, OuterRef
    Mailbox = apps.get_model("mailboxes", "Mailbox")
    sq = Mailbox.objects.filter(pk=OuterRef("mailbox_id")).values("company__mc_number")[:1]
    Conversation.objects.filter(mc_number="").update(mc_number=Subquery(sq))


def noop_reverse(apps, schema_editor):
    """Reversing the column drop is fine; data loss is acceptable for the rollback."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("conversations", "0007_conversation_preview_fields"),
        # mailboxes app must exist when we reach the data migration; it does
        # (mailboxes is a dependency of conversations.Conversation already
        # via the mailbox FK), so no migration cross-dep needed.
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="mc_number",
            field=models.CharField(blank=True, db_index=True, default="", max_length=32),
        ),
        migrations.RunPython(backfill_mc_number, noop_reverse),
        migrations.AddIndex(
            model_name="conversation",
            index=models.Index(
                fields=["mc_number", "-last_message_at"],
                name="conv_mc_recency_idx",
            ),
        ),
    ]
