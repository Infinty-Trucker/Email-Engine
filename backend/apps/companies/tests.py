"""Tests for apps.companies: Company model helpers.

Run with:
    python manage.py test apps.companies.tests --settings=config.test_settings
"""
import uuid

from django.test import TestCase

from apps.companies.models import Company


def make_company(name="Acme Trucking", mc_number=None):
    return Company.objects.create(
        name=name, mc_number=mc_number or f"MC{uuid.uuid4().hex[:8]}"
    )


class CompanySlugTests(TestCase):
    def test_slug_lowercases_and_hyphenates(self):
        company = Company(name="Big Rig  Logistics, Inc.")
        self.assertEqual(company.slug, "big-rig-logistics-inc")

    def test_load_ops_channel_defaults_to_slug(self):
        company = make_company(name="Acme Trucking")
        self.assertEqual(company.slack_load_ops_channel, "acme-trucking-load-ops")

    def test_load_ops_channel_uses_explicit_name_when_set(self):
        company = make_company(name="Acme")
        company.slack_channel_loads_name = "custom-loads"
        self.assertEqual(company.slack_load_ops_channel, "custom-loads")

    def test_paperwork_ops_channel_defaults_to_slug(self):
        company = make_company(name="Road Kings")
        self.assertEqual(company.slack_paperwork_ops_channel, "road-kings-paperwork-ops")
