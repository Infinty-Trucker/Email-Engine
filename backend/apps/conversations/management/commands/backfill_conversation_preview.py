"""Populate preview_sender / preview_subject / preview_snippet on existing
conversations so the lean inbox list endpoint serves real data on day one
instead of waiting for new inbound mail to upgrade rows.

Idempotent: skip rows that already have a preview_subject. Pass --force to
recompute every row.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.conversations.models import Conversation


class Command(BaseCommand):
    help = "Backfill Conversation.preview_* fields from the first inbound message."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompute the preview even for rows that already have one.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Conversations per transaction (default 500).",
        )

    def handle(self, *args, **opts):
        force = opts["force"]
        batch_size = opts["batch_size"]

        qs = Conversation.objects.all()
        if not force:
            # A row needs backfill if any preview column is empty. preview_subject
            # alone isn't enough — early bugs left some rows with sender filled
            # but subject blank.
            qs = qs.filter(preview_subject="") | qs.filter(preview_sender="")
            qs = qs.distinct()

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to backfill."))
            return

        self.stdout.write(f"Backfilling {total} conversations…")

        updated = 0
        skipped = 0
        ids = list(qs.values_list("id", flat=True))
        for offset in range(0, len(ids), batch_size):
            chunk = ids[offset:offset + batch_size]
            with transaction.atomic():
                for conv in Conversation.objects.filter(id__in=chunk).prefetch_related("messages"):
                    inbound = [m for m in conv.messages.all() if m.direction == "inbound"]
                    if not inbound:
                        skipped += 1
                        continue
                    inbound.sort(key=lambda m: m.created_at)
                    sender = next((m.sender_email for m in inbound if m.sender_email), "")
                    subject = next((m.subject for m in inbound if m.subject), "")
                    snippet = next((m.snippet for m in inbound if m.snippet), "")
                    Conversation.objects.filter(id=conv.id).update(
                        preview_sender=sender,
                        preview_subject=subject,
                        preview_snippet=snippet,
                    )
                    updated += 1
            self.stdout.write(f"  …{offset + len(chunk)} / {total}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Updated {updated}, skipped {skipped} (no inbound messages)."
        ))
