"""Tests for apps.mailboxes: Gmail message parsing helpers + Mailbox model.

Run with:
    python manage.py test apps.mailboxes.tests --settings=config.test_settings
"""
import base64

from django.test import SimpleTestCase, TestCase

from apps.mailboxes.gmail_client import parse_headers, get_body, extract_email
from apps.mailboxes.models import Mailbox
from apps.core.test_factories import make_company


def _b64(text):
    # urlsafe base64 without padding — get_body must tolerate missing "=".
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class ExtractEmailTests(SimpleTestCase):
    def test_name_and_angle_brackets(self):
        self.assertEqual(extract_email("Bob Broker <bob@acme.com>"), "bob@acme.com")

    def test_plain_address(self):
        self.assertEqual(extract_email("plain@acme.com"), "plain@acme.com")

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(extract_email("  spaced@acme.com  "), "spaced@acme.com")


class ParseHeadersTests(SimpleTestCase):
    def test_header_names_are_case_insensitive(self):
        msg = {"payload": {"headers": [
            {"name": "From", "value": "a@x.com"},
            {"name": "SUBJECT", "value": "Hi there"},
            {"name": "Message-ID", "value": "<abc@x>"},
        ]}}
        parsed = parse_headers(msg)
        self.assertEqual(parsed["from"], "a@x.com")
        self.assertEqual(parsed["subject"], "Hi there")
        self.assertEqual(parsed["message_id"], "<abc@x>")

    def test_missing_headers_default_to_empty(self):
        parsed = parse_headers({"payload": {"headers": []}})
        self.assertEqual(parsed["subject"], "")
        self.assertEqual(parsed["from"], "")


class GetBodyTests(SimpleTestCase):
    def test_plain_and_html_extracted(self):
        msg = {"payload": {"parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("plain text")}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
        ]}}
        text, html = get_body(msg)
        self.assertEqual(text, "plain text")
        self.assertEqual(html, "<p>html</p>")

    def test_nested_multipart_is_walked(self):
        msg = {"payload": {"parts": [
            {"mimeType": "multipart/alternative", "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("nested body")}},
            ]},
        ]}}
        text, _ = get_body(msg)
        self.assertEqual(text, "nested body")

    def test_empty_payload_returns_empty_strings(self):
        self.assertEqual(get_body({}), ("", ""))


class MailboxModelTests(TestCase):
    def test_defaults(self):
        mailbox = Mailbox.objects.create(
            company=make_company(), email_address="ops@carrier.com"
        )
        self.assertTrue(mailbox.is_active)
        self.assertEqual(mailbox.watch_status, "expired")
