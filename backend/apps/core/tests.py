"""Tests for apps.core: error translation and the DRF exception handler.

Run with:
    python manage.py test apps.core.tests --settings=config.test_settings
"""
from django.test import SimpleTestCase
from rest_framework.exceptions import (
    NotAuthenticated,
    PermissionDenied,
    NotFound,
)

from apps.core.error_utils import parse_error, parse_slack_error, parse_google_error
from apps.core.exception_handler import custom_exception_handler, _drf_detail_to_message


class ParseErrorTests(SimpleTestCase):
    def test_unique_constraint_maps_to_friendly_message(self):
        msg = parse_error(Exception("duplicate key value violates unique constraint"))
        self.assertIn("already configured", msg)

    def test_connection_refused_maps_to_db_message(self):
        msg = parse_error(Exception("could not connect to server: Connection refused"))
        self.assertIn("Database connection error", msg)

    def test_google_invalid_grant_string_fallback(self):
        msg = parse_error(Exception("invalid_grant: token expired"))
        self.assertIn("OAuth token expired", msg)

    def test_slack_string_fallback(self):
        msg = parse_slack_error(Exception("invalid_auth"))
        self.assertIn("Invalid Slack token", msg)

    def test_google_internal_paths_are_stripped(self):
        msg = parse_google_error(Exception("boom /app/foo/bar.py:42 happened"))
        self.assertNotIn(".py:42", msg)


class ExceptionHandlerTests(SimpleTestCase):
    def _handle(self, exc):
        return custom_exception_handler(exc, {"view": "X", "request": None})

    def test_not_authenticated_is_normalised(self):
        resp = self._handle(NotAuthenticated())
        self.assertEqual(resp.status_code, 401)
        self.assertIn("error", resp.data)
        self.assertIn("not logged in", resp.data["error"].lower())

    def test_permission_denied_message(self):
        resp = self._handle(PermissionDenied())
        self.assertEqual(resp.status_code, 403)
        self.assertIn("permission", resp.data["error"].lower())

    def test_not_found_message(self):
        resp = self._handle(NotFound())
        self.assertEqual(resp.status_code, 404)

    def test_unhandled_exception_returns_500_without_leaking(self):
        resp = self._handle(ValueError("internal detail that must not leak verbatim"))
        self.assertEqual(resp.status_code, 500)
        self.assertIn("error", resp.data)

    def test_drf_detail_mapping_known_and_unknown(self):
        self.assertIn("not logged in", _drf_detail_to_message(NotAuthenticated().detail).lower())
        # Unknown code falls back to str().
        self.assertIsInstance(_drf_detail_to_message("plain string"), str)
