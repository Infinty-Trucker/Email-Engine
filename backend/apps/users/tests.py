"""Tests for apps.users: User model role logic and TMS session-token auth.

Run with:
    python manage.py test apps.users.tests --settings=config.test_settings
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework import exceptions

from apps.users import tms_auth
from apps.users.tms_auth import (
    TMSSessionTokenAuthentication,
    has_tms_permission,
    _fetch_tms_permissions,
)

User = get_user_model()


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class UserModelTests(TestCase):
    def test_superuser_is_auto_promoted_to_admin(self):
        u = User.objects.create_user(
            username="su", email="su@x.com", password="x",
            is_superuser=True,
        )
        self.assertEqual(u.role, User.Role.ADMIN)

    def test_non_superuser_keeps_default_dispatcher_role(self):
        u = User.objects.create_user(username="d", email="d@x.com", password="x")
        self.assertEqual(u.role, User.Role.DISPATCHER)

    def test_visible_categories_by_role(self):
        admin = User(role="admin")
        dispatcher = User(role="dispatcher")
        self.assertIn("SAFETY", admin.visible_categories)
        self.assertNotIn("SAFETY", dispatcher.visible_categories)
        self.assertEqual(User(role="unknown").visible_categories, ["GENERAL"])

    def test_can_approve_roles(self):
        self.assertTrue(User(role="admin").can_approve)
        self.assertTrue(User(role="safety").can_approve)
        self.assertTrue(User(role="manager").can_approve)
        self.assertFalse(User(role="dispatcher").can_approve)
        self.assertFalse(User(role="accountant").can_approve)


class HasTmsPermissionTests(SimpleTestCase):
    def test_superuser_always_allowed(self):
        u = User(is_superuser=True)
        self.assertTrue(has_tms_permission(u, "email.view"))

    def test_tms_superuser_flag_allowed(self):
        u = User()
        u._tms_is_superuser = True
        self.assertTrue(has_tms_permission(u, "email.view"))

    def test_slug_present_in_permissions(self):
        u = User()
        u._tms_permissions = {"email.view", "load.view"}
        self.assertTrue(has_tms_permission(u, "email.view"))
        self.assertFalse(has_tms_permission(u, "email.send"))

    def test_empty_permissions_defers_to_caller(self):
        # No slug data -> return True so the caller's legacy gate decides.
        u = User()
        u._tms_permissions = set()
        self.assertTrue(has_tms_permission(u, "anything"))


class FetchTmsPermissionsTests(TestCase):
    def setUp(self):
        cache.clear()

    @mock.patch.object(tms_auth, "requests")
    def test_flattens_roles_to_slug_set(self, mock_requests):
        mock_requests.get.return_value = _FakeResponse(
            200,
            {"roles": [
                {"permissions": [{"slug": "email.view"}, {"slug": "email.send"}]},
                {"permissions": [{"slug": "load.view"}]},
            ]},
        )
        mock_requests.RequestException = Exception
        slugs = _fetch_tms_permissions("tok", "MC1")
        self.assertEqual(slugs, {"email.view", "email.send", "load.view"})

    @mock.patch.object(tms_auth, "requests")
    def test_non_200_returns_empty_set(self, mock_requests):
        mock_requests.get.return_value = _FakeResponse(403, {})
        mock_requests.RequestException = Exception
        self.assertEqual(_fetch_tms_permissions("tok", "MC1"), set())

    @mock.patch.object(tms_auth, "requests")
    def test_network_error_returns_empty_set(self, mock_requests):
        mock_requests.RequestException = Exception
        mock_requests.get.side_effect = Exception("boom")
        self.assertEqual(_fetch_tms_permissions("tok", "MC1"), set())


class TMSSessionTokenAuthenticationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.auth = TMSSessionTokenAuthentication()

    def _request(self, token=None, tenant=None):
        meta = {}
        if token:
            meta["HTTP_X_SESSION_TOKEN"] = token
        if tenant:
            meta["HTTP_X_TENANT"] = tenant
        return mock.Mock(META=meta)

    def test_no_token_returns_none(self):
        self.assertIsNone(self.auth.authenticate(self._request()))

    @mock.patch.object(tms_auth, "requests")
    def test_successful_auth_mirrors_user(self, mock_requests):
        mock_requests.RequestException = Exception
        mock_requests.get.return_value = _FakeResponse(
            200,
            {"user": {"email": "Dispatcher@Acme.com", "first_name": "Di",
                      "last_name": "Spatch", "is_superuser": False}},
        )
        user, token = self.auth.authenticate(self._request(token="tok123"))
        self.assertEqual(user.email, "Dispatcher@Acme.com")
        self.assertEqual(token, "tok123")
        # Mirrored locally with admin role + active/staff defaults.
        self.assertTrue(User.objects.filter(email="Dispatcher@Acme.com").exists())
        self.assertEqual(user.role, "admin")

    @mock.patch.object(tms_auth, "requests")
    def test_tms_401_raises_authentication_failed(self, mock_requests):
        mock_requests.RequestException = Exception
        mock_requests.get.return_value = _FakeResponse(401, text="nope")
        with self.assertRaises(exceptions.AuthenticationFailed):
            self.auth.authenticate(self._request(token="bad"))

    @mock.patch.object(tms_auth, "requests")
    def test_tms_unreachable_raises_authentication_failed(self, mock_requests):
        mock_requests.RequestException = Exception
        mock_requests.get.side_effect = mock_requests.RequestException("down")
        with self.assertRaises(exceptions.AuthenticationFailed):
            self.auth.authenticate(self._request(token="tok"))

    @mock.patch.object(tms_auth, "requests")
    def test_payload_without_email_is_rejected(self, mock_requests):
        mock_requests.RequestException = Exception
        mock_requests.get.return_value = _FakeResponse(200, {"user": {}})
        with self.assertRaises(exceptions.AuthenticationFailed):
            self.auth.authenticate(self._request(token="tok"))
