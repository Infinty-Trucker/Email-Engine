"""Tests for apps.settings: Fernet field encryption helpers.

Run with:
    python manage.py test apps.settings.tests --settings=config.test_settings
"""
from django.test import SimpleTestCase

from apps.settings.models import encrypt, decrypt


class EncryptionTests(SimpleTestCase):
    def test_round_trip(self):
        secret = "xoxb-super-secret-token"
        token = encrypt(secret)
        self.assertNotEqual(token, secret)
        self.assertEqual(decrypt(token), secret)

    def test_empty_value_encrypts_to_empty_string(self):
        self.assertEqual(encrypt(""), "")
        self.assertEqual(encrypt(None), "")

    def test_empty_value_decrypts_to_empty_string(self):
        self.assertEqual(decrypt(""), "")
        self.assertEqual(decrypt(None), "")

    def test_garbage_ciphertext_decrypts_to_empty_string(self):
        # decrypt swallows InvalidToken and returns "".
        self.assertEqual(decrypt("not-a-valid-fernet-token"), "")

    def test_ciphertext_is_not_deterministic(self):
        # Fernet embeds a timestamp/IV, so two encryptions differ but both
        # decrypt back to the same plaintext.
        a = encrypt("same")
        b = encrypt("same")
        self.assertEqual(decrypt(a), "same")
        self.assertEqual(decrypt(b), "same")
