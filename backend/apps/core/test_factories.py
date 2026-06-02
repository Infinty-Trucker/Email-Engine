"""Shared object factories for the Email-Engine test suite."""
import itertools
import uuid

from apps.companies.models import Company
from apps.mailboxes.models import Mailbox
from apps.conversations.models import Conversation, Message, Attachment

_counter = itertools.count(1)


def _n():
    return next(_counter)


def make_company(name=None, mc_number=None, **extra):
    i = _n()
    return Company.objects.create(
        name=name or f"Company-{i}",
        mc_number=mc_number or f"MC{i:06d}",
        **extra,
    )


def make_mailbox(company=None, email_address=None, **extra):
    i = _n()
    company = company or make_company()
    return Mailbox.objects.create(
        company=company,
        email_address=email_address or f"box{i}@example.com",
        **extra,
    )


def make_conversation(mailbox=None, mc_number="", **extra):
    i = _n()
    mailbox = mailbox or make_mailbox()
    return Conversation.objects.create(
        mailbox=mailbox,
        gmail_thread_id=f"thread-{i}",
        mc_number=mc_number,
        **extra,
    )


def make_message(conversation=None, sender_email="broker@acme.com",
                 subject="Load 123", direction="inbound", **extra):
    i = _n()
    conversation = conversation or make_conversation()
    return Message.objects.create(
        conversation=conversation,
        direction=direction,
        gmail_message_id=f"gmsg-{i}-{uuid.uuid4().hex[:6]}",
        sender_email=sender_email,
        recipient_email=extra.pop("recipient_email", "dispatch@us.com"),
        subject=subject,
        **extra,
    )


def make_attachment(message, filename="doc.pdf", mime_type="application/pdf", **extra):
    return Attachment.objects.create(
        message=message, filename=filename, mime_type=mime_type, **extra
    )
