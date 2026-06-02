"""Tests for apps.approvals + apps.auditlog + apps.notifications models.

Run with:
    python manage.py test apps.approvals.tests --settings=config.test_settings
"""
from django.test import TestCase

from apps.approvals.models import Approval
from apps.auditlog.models import AuditEvent
from apps.notifications.models import AlertTask
from apps.core.test_factories import make_message, make_conversation, make_company


class ApprovalModelTests(TestCase):
    def test_defaults_to_pending(self):
        msg = make_message()
        approval = Approval.objects.create(
            conversation=msg.conversation, message=msg
        )
        self.assertEqual(approval.status, "pending")
        self.assertIsNone(approval.resolved_at)


class AuditEventModelTests(TestCase):
    def test_details_default_dict(self):
        conv = make_conversation()
        event = AuditEvent.objects.create(conversation=conv, action="send")
        self.assertEqual(event.details, {})


class AlertTaskModelTests(TestCase):
    def test_defaults(self):
        conv = make_conversation()
        task = AlertTask.objects.create(
            conversation=conv, company=conv.mailbox.company, team="load"
        )
        self.assertEqual(task.status, AlertTask.PENDING)
        self.assertEqual(task.urgency, AlertTask.ROUTINE)
        self.assertEqual(task.alert_count, 0)
