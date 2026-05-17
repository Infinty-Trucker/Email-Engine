"""Clear rows that persisted the literal string "(no subject)" before the
parser fix landed. The BFF renders "(no subject)" at display time, so empty
DB values produce the same UX while letting later inbound messages with a
real Subject header upgrade the preview.

Idempotent. Pass --dry-run to see counts without writing.
"""
from django.core.management.base import BaseCommand

from apps.conversations.models import Conversation, Message


LITERAL = "(no subject)"


class Command(BaseCommand):
    help = "Clear Conversation.preview_subject and Message.subject where they equal the literal \"(no subject)\"."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts without updating any rows.",
        )

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]

        conv_qs = Conversation.objects.filter(preview_subject=LITERAL)
        msg_qs = Message.objects.filter(subject=LITERAL)

        conv_count = conv_qs.count()
        msg_count = msg_qs.count()

        self.stdout.write(f"Conversations with preview_subject=={LITERAL!r}: {conv_count}")
        self.stdout.write(f"Messages with subject=={LITERAL!r}: {msg_count}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes written."))
            return

        if conv_count:
            conv_qs.update(preview_subject="")
        if msg_count:
            msg_qs.update(subject="")

        self.stdout.write(self.style.SUCCESS(
            f"Cleared {conv_count} conversation previews and {msg_count} messages."
        ))
