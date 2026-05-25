"""One-shot backfill: re-fetch Gmail headers for messages that were ingested
before recipient_email / cc were captured correctly.

Before this fix, the ingest paths hardcoded `recipient_email = our_mailbox`
on every Message (so outbound rows looked like they were sent to ourselves)
and never set `cc` at all. This command:

  1. Finds outbound rows where recipient_email == the conversation's mailbox
     (the visible bug — 70 rows in the seed dataset)
  2. Finds inbound rows missing `cc` (which is every inbound row pre-fix)
  3. For each, calls Gmail `users().messages().get(format="metadata")` to
     pull just the headers, parses `To:` and `Cc:`, and updates the row

Cheap — metadata-format requests are a fraction of full-message cost and
this only runs once per inbox.
"""
from django.core.management.base import BaseCommand
from django.db.models import F
from apps.conversations.models import Message
from apps.mailboxes.tasks import _extract_email
from apps.settings.models import MailboxSettings
from apps.settings.gmail_oauth import get_gmail_service


def _parse_metadata_headers(raw):
    """Pull just the headers we need out of a Gmail metadata-format payload."""
    h = {x["name"].lower(): x["value"]
         for x in raw.get("payload", {}).get("headers", [])}
    return {
        "to": h.get("to", "") or "",
        "cc": h.get("cc", "") or "",
    }


class Command(BaseCommand):
    help = "Backfill recipient_email and cc on messages ingested before the bug fix."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would change without writing.",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Cap rows processed (0 = no cap).",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        limit = opts["limit"]

        # Build the candidate set in one query: anything outbound where
        # recipient == sender (the bug) OR anything with an empty cc.
        # Excluding compose-placeholder messages (gmail_message_id starts
        # with "ai-" or "channel-" or "compose-") since those weren't pulled
        # from Gmail and don't have headers to re-fetch.
        bad_outbound = Message.objects.filter(
            direction="outbound", recipient_email=F("sender_email"),
        ).exclude(gmail_message_id="").exclude(
            gmail_message_id__startswith="ai-",
        ).exclude(
            gmail_message_id__startswith="channel-",
        ).exclude(
            gmail_message_id__startswith="compose-",
        )
        missing_cc_inbound = Message.objects.filter(
            direction="inbound", cc="",
        ).exclude(gmail_message_id="").exclude(
            gmail_message_id__startswith="ai-",
        ).exclude(
            gmail_message_id__startswith="channel-",
        ).exclude(
            gmail_message_id__startswith="compose-",
        )
        # Django blocks .select_related after .union(), so iterate the two
        # queries via a values_list of ids and re-fetch full rows once.
        ids = list(bad_outbound.values_list("id", flat=True))
        ids += list(missing_cc_inbound.values_list("id", flat=True))
        # Dedup while preserving order (a row could match both filters).
        seen = set()
        deduped = [i for i in ids if not (i in seen or seen.add(i))]
        if limit:
            deduped = deduped[:limit]
        candidates = (
            Message.objects
            .filter(id__in=deduped)
            .select_related("conversation__mailbox")
            .order_by("created_at")
        )

        # Cache Gmail services per mailbox so we don't rebuild for every row.
        services = {}
        def _svc_for(mailbox_email):
            if mailbox_email in services:
                return services[mailbox_email]
            try:
                smb = MailboxSettings.objects.select_related(
                    "service_account", "oauth_credential",
                ).get(email_address=mailbox_email, is_active=True)
                services[mailbox_email] = get_gmail_service(smb)
            except MailboxSettings.DoesNotExist:
                services[mailbox_email] = None
            except Exception as e:
                self.stderr.write(f"  ! could not init Gmail for {mailbox_email}: {e}")
                services[mailbox_email] = None
            return services[mailbox_email]

        updated = 0
        skipped_no_service = 0
        skipped_no_headers = 0
        errors = 0
        total = candidates.count()
        self.stdout.write(f"Processing {total} message(s){' (dry-run)' if dry else ''}…")

        for idx, m in enumerate(candidates, 1):
            mailbox_email = m.conversation.mailbox.email_address
            svc = _svc_for(mailbox_email)
            if not svc:
                skipped_no_service += 1
                continue
            try:
                raw = svc.users().messages().get(
                    userId="me", id=m.gmail_message_id, format="metadata",
                    metadataHeaders=["To", "Cc"],
                ).execute()
            except Exception as e:
                errors += 1
                msg = str(e)
                if "404" in msg or "Not Found" in msg:
                    # Trashed / deleted on Gmail's side — nothing to backfill.
                    continue
                self.stderr.write(f"  ! fetch failed for {m.gmail_message_id}: {msg[:120]}")
                continue

            h = _parse_metadata_headers(raw)
            to_header = h["to"]
            cc_header = h["cc"]
            if not to_header and not cc_header:
                skipped_no_headers += 1
                continue

            updates = {}
            if m.direction == "outbound" and to_header and m.recipient_email == m.sender_email:
                primary_to = _extract_email(to_header.split(",")[0])
                if primary_to:
                    updates["recipient_email"] = primary_to
            if cc_header and not m.cc:
                updates["cc"] = cc_header

            if not updates:
                continue

            if dry:
                self.stdout.write(
                    f"  [{idx}/{total}] would update {m.id} ({m.direction}): {updates}"
                )
            else:
                Message.objects.filter(id=m.id).update(**updates)
            updated += 1

            if idx % 25 == 0:
                self.stdout.write(f"  …{idx}/{total} processed, {updated} updated")

        self.stdout.write(self.style.SUCCESS(
            f"Done. updated={updated} skipped_no_service={skipped_no_service} "
            f"skipped_no_headers={skipped_no_headers} errors={errors}"
        ))
