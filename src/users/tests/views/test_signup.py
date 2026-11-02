from django.contrib import auth
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from users import helpers


class SignupViewTests(TestCase):
    """Test the local registration flow at account_signup."""

    def setUp(self):
        """Clear the cached first-run flag so it doesn't leak between tests."""
        cache.delete(helpers.IS_FIRST_RUN_CACHE_KEY)

    def test_fresh_registration_succeeds(self):
        """Test a brand-new installation can register a local account."""
        response = self.client.post(
            reverse("account_signup"),
            {
                "username": "newuser",
                "password1": "SuperSecret123!",
                "password2": "SuperSecret123!",
            },
        )

        self.assertNotEqual(response.status_code, 500)
        self.assertTrue(
            get_user_model().objects.filter(username="newuser").exists(),
        )
        self.assertEqual(auth.get_user(self.client).username, "newuser")

    def test_duplicate_username_returns_form_error_not_500(self):
        """Test registering an already-taken username re-renders with an error."""
        get_user_model().objects.create_user(username="taken", password="12345")

        response = self.client.post(
            reverse("account_signup"),
            {
                "username": "taken",
                "password1": "SuperSecret123!",
                "password2": "SuperSecret123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            get_user_model().objects.filter(username="taken", is_active=True).count()
            > 1,
        )
        self.assertFormError(
            response.context["form"],
            "username",
            "A user with that username already exists.",
        )

    def test_first_run_shows_welcome_copy(self):
        """Test the signup page greets a fresh install differently."""
        response = self.client.get(reverse("account_signup"))

        self.assertContains(response, "Welcome to Floppy")

    def test_not_first_run_after_a_real_account_exists(self):
        """Test the welcome copy disappears once a real account exists."""
        get_user_model().objects.create_user(username="existing", password="12345")
        cache.delete(helpers.IS_FIRST_RUN_CACHE_KEY)

        response = self.client.get(reverse("account_signup"))

        self.assertNotContains(response, "Welcome to Floppy")

    @override_settings(
        ACCOUNT_ADAPTER="users.account_adapter.NoNewUsersAccountAdapter",
        REGISTRATION=False,
    )
    def test_closed_registration_rejects_direct_signup_post(self):
        response = self.client.post(
            reverse("account_signup"),
            {
                "username": "uninvited",
                "password1": "SuperSecret123!",
                "password2": "SuperSecret123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(auth.get_user(self.client).is_authenticated)

    def test_signup_requires_csrf_even_on_first_run(self):
        response = Client(enforce_csrf_checks=True).post(
            reverse("account_signup"),
            {
                "username": "uninvited",
                "password1": "SuperSecret123!",
                "password2": "SuperSecret123!",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.exists())
