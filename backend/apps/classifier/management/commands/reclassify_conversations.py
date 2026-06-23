"""Re-run the keyword classifier over already-imported conversations.

After a taxonomy change (e.g. adding TRACKING, broadening AUDIT→COMPLIANCE)
existing mail keeps its old category until a new message arrives. This command
re-applies the fast keyword classifier so the new buckets show up immediately
on historical mail — free and instant, no LLM calls.

Usage:
    python manage.py reclassify_conversations                # re-classify all
    python manage.py reclassify_conversations --dry-run       # preview only
    python manage.py reclassify_conversations --category AUDIT # only this bucket
    python manage.py reclassify_conversations --limit 500      # cap the run
"""

from collections import Counter

from django.core.management.base import BaseCommand

from apps.classifier.engine import classify_fast
from apps.classifier.models import Classification
from apps.conversations.models import Conversation, Message


class Command(BaseCommand):
    help = "Re-classify imported conversations with the current keyword rules."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Show what would change without writing.")
        parser.add_argument("--category", default="",
                            help="Only re-classify conversations currently in this category.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Stop after N conversations (0 = no limit).")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        only_cat = (opts["category"] or "").upper()
        limit = opts["limit"]

        qs = Conversation.objects.all().order_by("-last_message_at")
        if only_cat:
            qs = qs.filter(category=only_cat)
        if limit:
            qs = qs[:limit]

        transitions = Counter()
        changed = scanned = skipped = 0

        for conv in qs.iterator():
            scanned += 1
            # Representative message: latest inbound, else latest message.
            msg = (Message.objects.filter(conversation=conv, direction="inbound")
                   .order_by("created_at").last()
                   or Message.objects.filter(conversation=conv)
                   .order_by("created_at").last())
            if not msg:
                skipped += 1
                continue

            result = classify_fast(
                msg.sender_email or "",
                msg.subject or "",
                msg.body_text or msg.snippet or "",
            )
            new_cat, new_pri = result["category"], result["priority"]
            old_cat = conv.category or ""

            if new_cat == old_cat and new_pri == (conv.priority or ""):
                continue

            transitions[f"{old_cat or '∅'} → {new_cat}"] += 1
            changed += 1

            if not dry:
                conv.category = new_cat
                conv.priority = new_pri
                conv.save(update_fields=["category", "priority"])
                Classification.objects.update_or_create(
                    message=msg,
                    defaults={
                        "category": new_cat,
                        "priority": new_pri,
                        "ai_summary": result.get("summary", "")[:300],
                        "confidence": result.get("confidence", 0.7),
                        "model_version": result.get("model", "keyword"),
                    },
                )

        verb = "Would change" if dry else "Changed"
        self.stdout.write(self.style.SUCCESS(
            f"\nScanned {scanned} · {verb} {changed} · skipped {skipped} (no messages)"
        ))
        if transitions:
            self.stdout.write("\nCategory transitions:")
            for label, n in transitions.most_common():
                self.stdout.write(f"  {n:>5}  {label}")
        if dry:
            self.stdout.write(self.style.WARNING("\n(dry run — nothing written)"))
