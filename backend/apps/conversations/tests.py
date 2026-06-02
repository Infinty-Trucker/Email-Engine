"""Tests for apps.conversations: Attachment size formatting and models.

Run with:
    python manage.py test apps.conversations.tests --settings=config.test_settings
"""
from django.test import TestCase

from apps.conversations.models import Attachment
from apps.core.test_factories import make_message, make_conversation


class AttachmentSizeDisplayTests(TestCase):
    def _att(self, size):
        return Attachment(filename="f", size=size)

    def test_bytes(self):
        self.assertEqual(self._att(512).size_display, "512 B")

    def test_kilobytes_boundary(self):
        self.assertEqual(self._att(1024).size_display, "1 KB")

    def test_just_below_a_megabyte_is_kb(self):
        self.assertEqual(self._att(1024 * 1024 - 1).size_display, "1023 KB")

    def test_megabytes_one_decimal(self):
        self.assertEqual(self._att(int(2.5 * 1024 * 1024)).size_display, "2.5 MB")

    def test_zero_bytes(self):
        self.assertEqual(self._att(0).size_display, "0 B")


class ConversationModelTests(TestCase):
    def test_conversation_defaults_to_open(self):
        conv = make_conversation()
        self.assertEqual(conv.status, "open")

    def test_message_belongs_to_conversation(self):
        conv = make_conversation()
        msg = make_message(conversation=conv, subject="Hi")
        self.assertEqual(msg.conversation_id, conv.id)
        self.assertEqual(msg.direction, "inbound")
        self.assertIn(msg, conv.messages.all())
