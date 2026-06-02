"""Tests for apps.classifier: keyword-based fast classification & noise filter.

Run with:
    python manage.py test apps.classifier.tests --settings=config.test_settings
"""
from django.test import SimpleTestCase, TestCase

from apps.classifier.engine import is_noise, _fallback, classify_fast
from apps.classifier.models import Classification, ComplianceScan
from apps.core.test_factories import make_message


class IsNoiseTests(SimpleTestCase):
    def test_promotional_subject_keyword_is_noise(self):
        self.assertTrue(is_noise("sales@vendor.com", "Special offer just for you"))

    def test_unsubscribe_plus_view_in_browser_body_is_noise(self):
        self.assertTrue(
            is_noise("x@y.com", "Update", body="...unsubscribe... view in browser ...")
        )

    def test_normal_load_email_is_not_noise(self):
        self.assertFalse(is_noise("broker@logistics.com", "Rate confirmation for load 123"))

    def test_none_inputs_are_safe(self):
        self.assertFalse(is_noise(None, None, None))


class FallbackClassificationTests(SimpleTestCase):
    def test_load_email_is_high_priority_load(self):
        result = _fallback("Rate confirmation for load #555", from_email="b@x.com")
        self.assertEqual(result["category"], "LOAD")
        self.assertEqual(result["priority"], "HIGH")

    def test_billing_email(self):
        result = _fallback("Invoice payment remittance", from_email="ap@x.com")
        self.assertEqual(result["category"], "BILLING")
        self.assertEqual(result["priority"], "MEDIUM")

    def test_safety_email(self):
        result = _fallback("Accident report and drug test", from_email="s@x.com")
        self.assertEqual(result["category"], "SAFETY")

    def test_noise_email_classified_as_noise(self):
        result = _fallback("Unsubscribe from our newsletter", from_email="promo@x.com")
        self.assertEqual(result["category"], "NOISE")

    def test_unrecognized_email_is_general_low(self):
        result = _fallback("Hello there", from_email="friend@x.com")
        self.assertEqual(result["category"], "GENERAL")
        self.assertEqual(result["priority"], "LOW")

    def test_classification_is_case_insensitive(self):
        result = _fallback("RATE CONFIRMATION", from_email="b@x.com")
        self.assertEqual(result["category"], "LOAD")

    def test_classify_fast_delegates_to_fallback(self):
        self.assertEqual(
            classify_fast("b@x.com", "load offer")["category"], "LOAD"
        )

    def test_summary_is_truncated_to_80_chars(self):
        long_subject = "x" * 200
        result = _fallback(long_subject)
        self.assertLessEqual(len(result["summary"]), 80)


class ClassifierModelTests(TestCase):
    def test_classification_defaults(self):
        msg = make_message()
        c = Classification.objects.create(
            message=msg, category="LOAD", priority="HIGH"
        )
        self.assertEqual(c.confidence, 0.9)

    def test_compliance_scan_defaults(self):
        msg = make_message()
        scan = ComplianceScan.objects.create(message=msg)
        self.assertEqual(scan.risk_level, "LOW")
        self.assertTrue(scan.is_clean)
        self.assertEqual(scan.flags, [])
