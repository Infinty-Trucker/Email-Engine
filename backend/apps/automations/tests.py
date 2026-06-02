"""Tests for apps.automations: the MailRule matching engine.

Run with:
    python manage.py test apps.automations.tests --settings=config.test_settings
"""
from django.test import TestCase

from apps.automations.models import MailRule
from apps.automations.dispatcher import _matches, _regex_match, _candidate_rules
from apps.core.test_factories import (
    make_company,
    make_mailbox,
    make_conversation,
    make_message,
    make_attachment,
)


def make_rule(company=None, sender_pattern=r".*@acme\.com", **extra):
    defaults = dict(
        name=extra.pop("name", "rule"),
        company=company,
        sender_pattern=sender_pattern,
        action=MailRule.ACTION_PHOENIX_CAPITAL,
    )
    defaults.update(extra)
    return MailRule.objects.create(**defaults)


class RegexMatchTests(TestCase):
    def test_case_insensitive_match(self):
        self.assertTrue(_regex_match(r"broker@acme\.com", "BROKER@ACME.COM"))

    def test_no_match(self):
        self.assertFalse(_regex_match(r"broker@acme\.com", "someone@other.com"))

    def test_none_value_is_safe(self):
        self.assertFalse(_regex_match(r"x", None))

    def test_invalid_regex_returns_false_not_raises(self):
        # An unbalanced group is invalid; must be swallowed, not raised.
        self.assertFalse(_regex_match(r"([a-z", "anything"))


class MatchesTests(TestCase):
    def test_sender_pattern_gates_match(self):
        rule = make_rule(sender_pattern=r".*@acme\.com")
        msg = make_message(sender_email="broker@acme.com")
        self.assertTrue(_matches(rule, msg))
        msg2 = make_message(sender_email="broker@other.com")
        self.assertFalse(_matches(rule, msg2))

    def test_subject_pattern_must_also_match_when_set(self):
        rule = make_rule(sender_pattern=r".*@acme\.com", subject_pattern=r"invoice")
        ok = make_message(sender_email="a@acme.com", subject="Your invoice is ready")
        self.assertTrue(_matches(rule, ok))
        bad = make_message(sender_email="a@acme.com", subject="Just a load")
        self.assertFalse(_matches(rule, bad))

    def test_empty_subject_pattern_matches_any_subject(self):
        rule = make_rule(sender_pattern=r".*@acme\.com", subject_pattern="")
        msg = make_message(sender_email="a@acme.com", subject="anything at all")
        self.assertTrue(_matches(rule, msg))

    def test_require_attachment_with_none_present_fails(self):
        rule = make_rule(sender_pattern=r".*@acme\.com", require_attachment=True)
        msg = make_message(sender_email="a@acme.com")
        self.assertFalse(_matches(rule, msg))

    def test_require_attachment_satisfied(self):
        rule = make_rule(sender_pattern=r".*@acme\.com", require_attachment=True)
        msg = make_message(sender_email="a@acme.com")
        make_attachment(msg, mime_type="application/pdf")
        self.assertTrue(_matches(rule, msg))

    def test_attachment_mime_prefix_filter(self):
        rule = make_rule(
            sender_pattern=r".*@acme\.com",
            require_attachment=True,
            attachment_mime_prefix="application/pdf",
        )
        msg = make_message(sender_email="a@acme.com")
        make_attachment(msg, mime_type="image/png")
        # Has an attachment, but not the required mime prefix.
        self.assertFalse(_matches(rule, msg))
        make_attachment(msg, mime_type="application/pdf")
        self.assertTrue(_matches(rule, msg))


class CandidateRulesTests(TestCase):
    def setUp(self):
        # A data migration seeds a default global rule; clear all rules so each
        # test controls the candidate set deterministically.
        MailRule.objects.all().delete()

    def test_global_rule_applies_to_any_message(self):
        make_rule(company=None, name="global")
        msg = make_message(conversation=make_conversation(mc_number="MC999"))
        rules = _candidate_rules(msg)
        self.assertEqual(len(rules), 1)

    def test_tenant_rule_only_applies_to_its_mc(self):
        company = make_company(mc_number="MC555")
        make_rule(company=company, name="tenant")
        # Message whose conversation carries a different MC sees no tenant rule.
        other_msg = make_message(conversation=make_conversation(mc_number="MC000"))
        self.assertEqual(len(_candidate_rules(other_msg)), 0)
        # Message with the matching MC sees it.
        match_msg = make_message(conversation=make_conversation(mc_number="MC555"))
        self.assertEqual(len(_candidate_rules(match_msg)), 1)

    def test_disabled_rules_are_excluded(self):
        make_rule(company=None, name="off", enabled=False)
        msg = make_message(conversation=make_conversation(mc_number="MC123"))
        self.assertEqual(len(_candidate_rules(msg)), 0)

    def test_message_without_mc_sees_only_global_rules(self):
        company = make_company(mc_number="MC777")
        make_rule(company=company, name="tenant")
        make_rule(company=None, name="global")
        msg = make_message(conversation=make_conversation(mc_number=""))
        rules = _candidate_rules(msg)
        self.assertEqual([r.name for r in rules], ["global"])


class FindPdfAttachmentTests(TestCase):
    def test_picks_pdf_by_mime_type(self):
        from apps.automations.actions import _find_pdf_attachment

        msg = make_message(sender_email="a@acme.com")
        make_attachment(msg, filename="image.png", mime_type="image/png")
        pdf = make_attachment(msg, filename="schedule.pdf", mime_type="application/pdf")
        self.assertEqual(_find_pdf_attachment(msg), pdf)

    def test_falls_back_to_pdf_filename_when_mime_is_octet_stream(self):
        from apps.automations.actions import _find_pdf_attachment

        msg = make_message(sender_email="a@acme.com")
        att = make_attachment(
            msg, filename="schedule.PDF", mime_type="application/octet-stream"
        )
        self.assertEqual(_find_pdf_attachment(msg), att)

    def test_returns_none_when_no_pdf(self):
        from apps.automations.actions import _find_pdf_attachment

        msg = make_message(sender_email="a@acme.com")
        make_attachment(msg, filename="image.png", mime_type="image/png")
        self.assertIsNone(_find_pdf_attachment(msg))
