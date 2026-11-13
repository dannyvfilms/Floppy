from django.contrib import auth
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse


class Profile(TestCase):
    """Test profile page."""

    def setUp(self):
        """Create user for the tests."""
        cache.clear()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_change_username(self):
        """Test changing username."""
        self.assertEqual(auth.get_user(self.client).username, "test")
        self.client.post(
            reverse("account"),
            {
                "username": "new_test",
            },
        )
        self.assertEqual(auth.get_user(self.client).username, "new_test")

    def test_change_password(self):
        """Test changing password."""
        self.assertEqual(auth.get_user(self.client).check_password("12345"), True)
        self.client.post(
            reverse("account"),
            {
                "old_password": "12345",
                "new_password1": "*FNoZN64",
                "new_password2": "*FNoZN64",
            },
        )
        self.assertEqual(auth.get_user(self.client).check_password("*FNoZN64"), True)

    def test_invalid_password_change(self):
        """Test password change with incorrect old password."""
        response = self.client.post(
            reverse("account"),
            {
                "old_password": "wrongpass",
                "new_password1": "newpass123",
                "new_password2": "newpass123",
            },
        )
        self.assertTrue(auth.get_user(self.client).check_password("12345"))
        self.assertContains(response, "Your old password was entered incorrectly")

    def test_account_page_shows_qr_setup_option(self):
        """Account page should include QR setup data for authenticator apps."""
        response = self.client.get(reverse("account"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scan this QR code")
        self.assertTrue(response.context["authenticator_uri"].startswith("otpauth://"))
        self.assertTrue(
            response.context["authenticator_qr_data_uri"].startswith(
                "data:image/png;base64,"
            ),
        )

    def test_account_page_shows_management_actions_when_authenticator_enabled(self):
        """Configured accounts should show authenticator management actions."""
        self.user.get_or_create_authenticator_secret()
        self.user.authenticator_enabled = True
        self.user.save(update_fields=["authenticator_enabled"])

        response = self.client.get(reverse("account"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add New Authenticator App")
        self.assertContains(response, "Deactivate Authenticator")
        self.assertFalse(response.context["show_authenticator_setup"])
        self.assertEqual(response.context["authenticator_qr_data_uri"], "")

    def test_authenticator_changes_require_current_password(self):
        """An active session alone cannot replace or disable account recovery."""
        import pyotp

        self.user.get_or_create_authenticator_secret()
        self.user.authenticator_enabled = True
        self.user.save(update_fields=["authenticator_enabled"])
        original_secret = self.user.authenticator_secret
        self.user.generate_recovery_codes(count=1)
        original_codes = list(self.user.recovery_codes.values_list("pk", flat=True))
        for action in [
            "start_authenticator_setup",
            "disable_authenticator",
            "enable_authenticator",
        ]:
            for password in ["", "wrong"]:
                with self.subTest(action=action, password=password):
                    self.client.post(
                        reverse("account"),
                        {
                            "action": action,
                            "current_password": password,
                            "code": pyotp.TOTP(original_secret).now(),
                        },
                    )
                    self.user.refresh_from_db()
                    self.assertTrue(self.user.authenticator_enabled)
                    self.assertEqual(self.user.authenticator_secret, original_secret)
                    self.assertEqual(
                        list(self.user.recovery_codes.values_list("pk", flat=True)),
                        original_codes,
                    )

    def test_disable_authenticator_with_password(self):
        self.user.get_or_create_authenticator_secret()
        self.user.authenticator_enabled = True
        self.user.save(update_fields=["authenticator_enabled"])
        response = self.client.post(
            reverse("account"),
            {
                "action": "disable_authenticator",
                "current_password": "12345",
            },
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.authenticator_enabled)
        self.assertContains(response, "Scan this QR code")

    def test_replace_and_enable_authenticator_with_password(self):
        import pyotp

        old_secret = self.user.get_or_create_authenticator_secret()
        self.user.authenticator_enabled = True
        self.user.save(update_fields=["authenticator_enabled"])
        self.client.post(
            reverse("account"),
            {
                "action": "start_authenticator_setup",
                "current_password": "12345",
            },
        )
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.authenticator_secret, old_secret)
        self.assertFalse(self.user.authenticator_enabled)
        response = self.client.post(
            reverse("account"),
            {
                "action": "enable_authenticator",
                "current_password": "12345",
                "code": pyotp.TOTP(self.user.authenticator_secret).now(),
            },
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.authenticator_enabled)
        self.assertEqual(len(response.context["fresh_recovery_codes"]), 8)

    @override_settings(ACCOUNT_RATE_LIMITS={"reauthenticate": "2/m/user"})
    def test_authenticator_password_checks_are_throttled(self):
        for _ in range(2):
            self.client.post(
                reverse("account"),
                {"action": "disable_authenticator", "current_password": "wrong"},  # pragma: allowlist secret
            )
        response = self.client.post(
            reverse("account"),
            {"action": "disable_authenticator", "current_password": "12345"},
        )
        self.assertEqual(response.status_code, 429)

    def test_regenerating_recovery_codes_preserves_password_confirmation(self):
        self.user.generate_recovery_codes(count=1)
        original = self.user.recovery_codes.get().pk
        for password in ["", "wrong"]:
            response = self.client.post(
                reverse("account"),
                {
                    "action": "regenerate_recovery_codes",
                    "current_password": password,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.user.recovery_codes.get().pk, original)
        response = self.client.post(
            reverse("account"),
            {
                "action": "regenerate_recovery_codes",
                "current_password": "12345",
            },
        )
        self.assertEqual(len(response.context["fresh_recovery_codes"]), 8)
        self.assertFalse(self.user.recovery_codes.filter(pk=original).exists())
