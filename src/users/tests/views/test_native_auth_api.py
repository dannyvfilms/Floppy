"""Tests for the native auth and account-security JSON contract."""

import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

NATIVE = {"HTTP_X_FLOPPY_CLIENT": "native"}


class NativeAuthConfigTests(TestCase):
    """The public config endpoint exposes only redirect intents and flags."""

    def setUp(self):
        cache.clear()

    def test_auth_config_is_public_and_names_redirects(self):
        response = self.client.get(reverse("auth_config"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("registrationEnabled", payload)
        self.assertIn("providers", payload)
        self.assertTrue(payload["connectionsUrl"].endswith("/accounts/3rdparty/"))
        self.assertTrue(payload["deviceUrl"].endswith("/oauth/device"))


class NativeAccountTests(TestCase):
    """Account interactions use JSON only for the explicit native client."""

    def setUp(self):
        cache.clear()
        self.credentials = {"username": "nova", "password": "old-secret-123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_account_state_has_no_credentials(self):
        response = self.client.get(reverse("account"), **NATIVE)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["user"]["username"], "nova")
        self.assertTrue(payload["authenticator"]["setup"])
        self.assertTrue(payload["authenticator"]["secret"])
        self.assertTrue(payload["authenticator"]["qrDataUri"].startswith("data:image/png;base64,"))
        self.assertNotIn("old-secret-123", json.dumps(payload))

    def test_profile_update_returns_the_new_state(self):
        response = self.client.post(
            reverse("account"), {"username": "nova-2"}, **NATIVE
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["username"], "nova-2")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "nova-2")

    def test_password_errors_are_field_scoped(self):
        response = self.client.post(
            reverse("account"),
            {
                "old_password": "wrong",
                "new_password1": "new-secret-123",
                "new_password2": "new-secret-123",
            },
            **NATIVE,
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("old_password", payload["errors"])
        self.assertNotIn("new-secret-123", json.dumps(payload))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old-secret-123"))

    def test_authenticator_setup_and_enable_return_fresh_codes(self):
        import pyotp

        state = self.client.get(reverse("account"), **NATIVE).json()
        secret = state["authenticator"]["secret"]

        response = self.client.post(
            reverse("account"),
            {
                "action": "enable_authenticator",
                "current_password": "old-secret-123",
                "code": pyotp.TOTP(secret).now(),
            },
            **NATIVE,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["authenticator"]["configured"])
        self.assertEqual(len(payload["freshRecoveryCodes"]), 8)
        self.user.refresh_from_db()
        self.assertTrue(self.user.authenticator_enabled)

    def test_recovery_code_regeneration_needs_the_password(self):
        self.user.generate_recovery_codes(count=1)
        original = self.user.recovery_codes.get().pk

        response = self.client.post(
            reverse("account"),
            {"action": "regenerate_recovery_codes", "current_password": "wrong"},
            **NATIVE,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("current_password", response.json()["errors"])
        self.assertEqual(self.user.recovery_codes.get().pk, original)

    def test_delete_requires_confirmation_and_ends_the_session(self):
        refused = self.client.post(
            reverse("account"),
            {"action": "delete_account", "current_password": "old-secret-123"},
            **NATIVE,
        )
        self.assertEqual(refused.status_code, 400)

        response = self.client.post(
            reverse("account"),
            {
                "action": "delete_account",
                "current_password": "old-secret-123",
                "confirm_delete": "on",
            },
            **NATIVE,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(get_user_model().objects.filter(pk=self.user.pk).exists())


class NativeSignupTests(TestCase):
    """Native signup gets JSON field errors and keeps the web form unchanged."""

    def setUp(self):
        cache.clear()

    def test_duplicate_username_returns_json_error(self):
        get_user_model().objects.create_user(username="taken", password="old-secret-123")

        response = self.client.post(
            reverse("account_signup"),
            {
                "username": "taken",
                "password1": "new-secret-123",
                "password2": "new-secret-123",
            },
            **NATIVE,
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("username", payload["errors"])
        self.assertNotIn("new-secret-123", json.dumps(payload))

    def test_valid_signup_logs_in(self):
        response = self.client.post(
            reverse("account_signup"),
            {
                "username": "new-native",
                "password1": "new-secret-123",
                "password2": "new-secret-123",
            },
            **NATIVE,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(get_user_model().objects.filter(username="new-native").exists())


class NativePasswordRecoveryTests(TestCase):
    """Password recovery returns JSON errors and success for the native client."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="recover-native",
            password="old-secret-123",
        )
        self.recovery_code = self.user.generate_recovery_codes(count=1)[0]

    def test_failed_recovery_returns_field_errors(self):
        response = self.client.post(
            reverse("password_recover"),
            {
                "username": self.user.username,
                "authenticator_code": "000000",
                "new_password1": "new-secret-123",
                "new_password2": "new-secret-123",
            },
            **NATIVE,
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertNotIn("new-secret-123", json.dumps(response.json()))

    def test_recovery_code_resets_the_password(self):
        response = self.client.post(
            reverse("password_recover"),
            {
                "username": self.user.username,
                "recovery_code": self.recovery_code,
                "new_password1": "new-secret-123",
                "new_password2": "new-secret-123",
            },
            **NATIVE,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-secret-123"))
