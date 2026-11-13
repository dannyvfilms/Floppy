from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse


class PasswordRecoveryViewTests(TestCase):
    """Tests for self-service password recovery flow."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user(
            username="recover-me",
            password="old-pass-123",
        )
        self.recovery_code = self.user.generate_recovery_codes(count=1)[0]

    @override_settings(ACCOUNT_RATE_LIMITS={"reset_password": "2/m/key"})
    def test_recovery_throttles_account_across_ips_and_username_casing(self):
        """Moving IPs or changing case must not bypass an account's attempt limit."""
        for username, ip in (("recover-me", "192.0.2.1"), ("RECOVER-ME", "192.0.2.2")):
            response = self.client.post(
                reverse("password_recover"),
                {"username": username, "authenticator_code": "000000"},
                REMOTE_ADDR=ip,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("password_recover"),
            {
                "username": self.user.username,
                "recovery_code": self.recovery_code,
                "new_password1": "new-secure-pass-123",
                "new_password2": "new-secure-pass-123",
            },
            REMOTE_ADDR="192.0.2.3",
        )
        self.assertEqual(response.status_code, 429)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old-pass-123"))
        self.assertIsNone(self.user.recovery_codes.get().used_at)

    @override_settings(ACCOUNT_RATE_LIMITS={"reset_password": "1/m/ip"})
    def test_recovery_throttles_ip_across_usernames(self):
        """Trying another account must still consume the source IP's budget."""
        self.client.post(reverse("password_recover"), {"username": "unknown"})
        response = self.client.post(
            reverse("password_recover"), {"username": self.user.username}
        )
        self.assertEqual(response.status_code, 429)

    def test_recovery_page_accessible_without_login(self):
        """Password recovery page should be publicly accessible."""
        response = self.client.get(reverse("password_recover"))
        self.assertEqual(response.status_code, 200)

    def test_recover_password_with_recovery_code(self):
        """Recovery code should allow password reset for user without authenticator enabled."""
        response = self.client.post(
            reverse("password_recover"),
            {
                "username": self.user.username,
                "recovery_code": self.recovery_code,
                "new_password1": "new-secure-pass-123",
                "new_password2": "new-secure-pass-123",
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-secure-pass-123"))
        self.assertContains(response, "Password updated")

    def test_recover_password_with_authenticator_code_when_enabled(self):
        """Authenticator code alone should allow password reset when authenticator is enabled."""
        secret = self.user.get_or_create_authenticator_secret()
        self.user.authenticator_enabled = True
        self.user.save(update_fields=["authenticator_enabled"])

        import pyotp

        code = pyotp.TOTP(secret).now()
        response = self.client.post(
            reverse("password_recover"),
            {
                "username": self.user.username,
                "authenticator_code": code,
                "new_password1": "new-secure-pass-123",
                "new_password2": "new-secure-pass-123",
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-secure-pass-123"))
        self.assertContains(response, "Password updated")

    def test_recover_password_falls_back_to_recovery_code_when_no_authenticator_code(
        self,
    ):
        """Recovery code should still work as fallback when authenticator is enabled."""
        self.user.get_or_create_authenticator_secret()
        self.user.authenticator_enabled = True
        self.user.save(update_fields=["authenticator_enabled"])

        response = self.client.post(
            reverse("password_recover"),
            {
                "username": self.user.username,
                "recovery_code": self.recovery_code,
                "new_password1": "new-secure-pass-123",
                "new_password2": "new-secure-pass-123",
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-secure-pass-123"))
        self.assertContains(response, "Password updated")

    def test_recover_password_fails_when_enabled_and_no_authenticator_or_recovery_code(
        self,
    ):
        """Recovery should fail when neither authenticator code nor recovery code is provided."""
        self.user.get_or_create_authenticator_secret()
        self.user.authenticator_enabled = True
        self.user.save(update_fields=["authenticator_enabled"])

        response = self.client.post(
            reverse("password_recover"),
            {
                "username": self.user.username,
                "new_password1": "new-secure-pass-123",
                "new_password2": "new-secure-pass-123",
            },
        )

        self.assertContains(response, "Unable to verify recovery details")
