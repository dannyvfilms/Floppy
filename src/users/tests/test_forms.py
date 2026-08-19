from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import RequestFactory, TestCase

from users.forms import (
    CustomSignupForm,
    CustomSocialSignupForm,
    NotificationSettingsForm,
)


def _build_request():
    """Build a request with a working session, as allauth's save() flow needs."""
    request = RequestFactory().post("/accounts/signup/")
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    return request


class NotificationSettingsFormTests(TestCase):
    """Tests for the NotificationSettingsForm."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.valid_discord_url = "discord://webhook_id/webhook_token"
        self.valid_telegram_url = "tgram://bot_token/chat_id"
        self.invalid_url = "invalid://not_a_real_url"

    def test_form_fields(self):
        """Test that the form has the correct fields."""
        form = NotificationSettingsForm()
        self.assertEqual(
            list(form.fields.keys()),
            [
                "notification_urls",
                "daily_digest_enabled",
                "release_notifications_enabled",
                "premiere_notifications_enabled",
            ],
        )

    def test_form_widget(self):
        """Test that the form uses the correct widget."""
        form = NotificationSettingsForm()
        self.assertEqual(form.fields["notification_urls"].widget.attrs["rows"], 5)
        self.assertEqual(form.fields["notification_urls"].widget.attrs["wrap"], "off")
        self.assertIn("placeholder", form.fields["notification_urls"].widget.attrs)

    @patch("apprise.Apprise.add")
    def test_valid_single_url(self, mock_add):
        """Test form with a single valid URL."""
        mock_add.return_value = True

        form_data = {
            "notification_urls": self.valid_discord_url,
            "daily_digest_enabled": True,
            "release_notifications_enabled": True,
        }
        form = NotificationSettingsForm(data=form_data, instance=self.user)

        self.assertTrue(form.is_valid())
        mock_add.assert_called_once_with(self.valid_discord_url)

    @patch("apprise.Apprise.add")
    def test_valid_multiple_urls(self, mock_add):
        """Test form with multiple valid URLs."""
        mock_add.return_value = True

        form_data = {
            "notification_urls": f"{self.valid_discord_url}\n{self.valid_telegram_url}",
            "daily_digest_enabled": True,
            "release_notifications_enabled": True,
        }
        form = NotificationSettingsForm(data=form_data, instance=self.user)

        self.assertTrue(form.is_valid())
        self.assertEqual(mock_add.call_count, 2)
        mock_add.assert_any_call(self.valid_discord_url)
        mock_add.assert_any_call(self.valid_telegram_url)

    @patch("apprise.Apprise.add")
    def test_empty_urls(self, mock_add):
        """Test form with empty URLs."""
        form_data = {
            "notification_urls": "",
            "daily_digest_enabled": True,
            "release_notifications_enabled": True,
        }
        form = NotificationSettingsForm(data=form_data, instance=self.user)

        self.assertTrue(form.is_valid())
        mock_add.assert_not_called()

    @patch("apprise.Apprise.add")
    def test_whitespace_only_urls(self, mock_add):
        """Test form with whitespace-only URLs."""
        form_data = {
            "notification_urls": "   \n  \t  ",
            "daily_digest_enabled": True,
            "release_notifications_enabled": True,
        }
        form = NotificationSettingsForm(data=form_data, instance=self.user)

        self.assertTrue(form.is_valid())
        mock_add.assert_not_called()

    @patch("apprise.Apprise.add")
    def test_invalid_url(self, mock_add):
        """Test form with an invalid URL."""
        mock_add.return_value = False

        form_data = {
            "notification_urls": self.invalid_url,
            "daily_digest_enabled": True,
            "release_notifications_enabled": True,
        }
        form = NotificationSettingsForm(data=form_data, instance=self.user)

        self.assertFalse(form.is_valid())
        self.assertIn("notification_urls", form.errors)
        self.assertIn(
            f"'{self.invalid_url}' is not a valid Apprise URL.",
            form.errors["notification_urls"],
        )
        mock_add.assert_called_once_with(self.invalid_url)

    @patch("apprise.Apprise.add")
    def test_mixed_valid_invalid_urls(self, mock_add):
        """Test form with a mix of valid and invalid URLs."""

        # Configure mock to return True for valid URL and False for invalid URL
        def side_effect(url):
            return url != self.invalid_url

        mock_add.side_effect = side_effect

        form_data = {
            "notification_urls": f"{self.valid_discord_url}\n{self.invalid_url}",
            "daily_digest_enabled": True,
            "release_notifications_enabled": True,
        }
        form = NotificationSettingsForm(data=form_data, instance=self.user)

        self.assertFalse(form.is_valid())
        self.assertIn("notification_urls", form.errors)
        self.assertIn(
            f"'{self.invalid_url}' is not a valid Apprise URL.",
            form.errors["notification_urls"],
        )
        self.assertEqual(mock_add.call_count, 2)

    @patch("apprise.Apprise.add")
    def test_urls_with_extra_whitespace(self, mock_add):
        """Test form with URLs that have extra whitespace."""
        mock_add.return_value = True

        form_data = {
            "notification_urls": (
                f"  {self.valid_discord_url}  \n\t{self.valid_telegram_url}\n"
            ),
            "daily_digest_enabled": True,
            "release_notifications_enabled": True,
        }
        form = NotificationSettingsForm(data=form_data, instance=self.user)

        self.assertTrue(form.is_valid())
        self.assertEqual(mock_add.call_count, 2)
        mock_add.assert_any_call(self.valid_discord_url)
        mock_add.assert_any_call(self.valid_telegram_url)

    @patch("apprise.Apprise.add")
    def test_form_saves_correctly(self, mock_add):
        """Test that the form saves the notification URLs correctly."""
        mock_add.return_value = True

        form_data = {
            "notification_urls": f"{self.valid_discord_url}\n{self.valid_telegram_url}",
            "daily_digest_enabled": True,
            "release_notifications_enabled": True,
        }
        form = NotificationSettingsForm(data=form_data, instance=self.user)

        self.assertTrue(form.is_valid())
        form.save()

        self.user.refresh_from_db()
        self.assertEqual(
            self.user.notification_urls,
            f"{self.valid_discord_url}\n{self.valid_telegram_url}",
        )
        self.assertTrue(self.user.daily_digest_enabled)
        self.assertTrue(self.user.release_notifications_enabled)

    @patch("apprise.Apprise.add")
    def test_empty_lines_are_ignored(self, mock_add):
        """Test that empty lines in the input are ignored."""
        mock_add.return_value = True

        form_data = {
            "notification_urls": (
                f"{self.valid_discord_url}\n\n{self.valid_telegram_url}\n\n"
            ),
            "daily_digest_enabled": True,
            "release_notifications_enabled": True,
        }
        form = NotificationSettingsForm(data=form_data, instance=self.user)

        self.assertTrue(form.is_valid())
        self.assertEqual(mock_add.call_count, 2)
        mock_add.assert_any_call(self.valid_discord_url)
        mock_add.assert_any_call(self.valid_telegram_url)

    def test_notification_preferences_save_correctly(self):
        """Test that notification preferences are saved correctly."""
        form_data = {
            "notification_urls": self.valid_discord_url,
            "daily_digest_enabled": False,
            "release_notifications_enabled": True,
        }

        with patch("apprise.Apprise.add", return_value=True):
            form = NotificationSettingsForm(data=form_data, instance=self.user)
            self.assertTrue(form.is_valid())
            form.save()

        self.user.refresh_from_db()
        self.assertFalse(self.user.daily_digest_enabled)
        self.assertTrue(self.user.release_notifications_enabled)


class CustomSignupFormTests(TestCase):
    """Tests for the local-registration CustomSignupForm."""

    def _valid_data(self, username="newuser"):
        return {
            "username": username,
            "password1": "SuperSecret123!",
            "password2": "SuperSecret123!",
        }

    def test_email_field_removed(self):
        """Test the email field is dropped since the User model has none."""
        form = CustomSignupForm(data=self._valid_data())

        self.assertNotIn("email", form.fields)

    def test_password2_label_customized(self):
        """Test the confirm-password field gets Floppy's copy."""
        form = CustomSignupForm(data=self._valid_data())

        self.assertEqual(form.fields["password2"].label, "Confirm Password")

    def test_valid_signup_creates_user(self):
        """Test a fresh username/password signup succeeds end to end."""
        form = CustomSignupForm(data=self._valid_data())

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save(_build_request())

        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertEqual(user.username, "newuser")

    def test_duplicate_username_is_a_validation_error_not_a_crash(self):
        """Test submitting an existing username returns a form error, not a 500."""
        get_user_model().objects.create_user(username="taken", password="12345")

        form = CustomSignupForm(data=self._valid_data(username="taken"))

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_save_race_condition_raises_validation_error_not_integrity_error(self):
        """Test a same-username race at save time surfaces as a validation error.

        `clean_username` only checks the DB at validation time; a concurrent
        signup for the same username can still slip through and hit the
        database's unique constraint inside save(). That must not propagate
        as an unhandled IntegrityError (-> HTTP 500).
        """
        form = CustomSignupForm(data=self._valid_data(username="racer"))
        self.assertTrue(form.is_valid(), form.errors)

        with patch(
            "allauth.account.forms.BaseSignupForm.save",
            side_effect=IntegrityError,
        ):
            with self.assertRaises(ValidationError) as ctx:
                form.save(_build_request())

        self.assertEqual(ctx.exception.code, "username_taken")


class CustomSocialSignupFormTests(TestCase):
    """Tests for the OIDC/social CustomSocialSignupForm."""

    def _build_sociallogin(self, username=""):
        user = get_user_model()(username=username)
        account = SocialAccount(provider="openid_connect", uid="test-uid")
        return SocialLogin(user=user, account=account)

    def test_email_field_removed(self):
        """Test the email field is dropped, mirroring local signup."""
        form = CustomSocialSignupForm(
            data={"username": "oidcuser"},
            sociallogin=self._build_sociallogin(),
        )

        self.assertNotIn("email", form.fields)

    def test_valid_signup_creates_user(self):
        """Test completing OIDC signup with a fresh username succeeds."""
        form = CustomSocialSignupForm(
            data={"username": "oidcuser"},
            sociallogin=self._build_sociallogin(),
        )

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save(_build_request())

        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertEqual(user.username, "oidcuser")

    def test_duplicate_username_is_a_validation_error_not_a_crash(self):
        """Test an existing username on OIDC completion is a form error, not a 500."""
        get_user_model().objects.create_user(username="taken", password="12345")

        form = CustomSocialSignupForm(
            data={"username": "taken"},
            sociallogin=self._build_sociallogin(),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)
