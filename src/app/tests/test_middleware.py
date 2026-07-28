from django.contrib.auth import get_user_model
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from app.middleware import AutoLoginMiddleware

UserModel = get_user_model()


class AutoLoginMiddlewareTest(TestCase):
    """Test cases for AutoLoginMiddleware."""

    def setUp(self):
        """Create test users."""
        self.factory = RequestFactory()
        self.existing_active_user = UserModel.objects.create_user(
            username="active_user",
            password="active_user_password",  # noqa: S106
            is_active=True,
        )
        self.existing_inactive_user = UserModel.objects.create_user(
            username="inactive_user",
            password="inactive_user_password",  # noqa: S106
            is_active=False,
        )

    def get_request(self):
        """Return a request with session and user middleware applied."""
        request = self.factory.get("/")
        SessionMiddleware(lambda _request: None).process_request(request)
        AuthenticationMiddleware(lambda _request: None).process_request(request)
        return request

    def run_middleware(self, request):
        """Run auto-login middleware against the request."""
        middleware = AutoLoginMiddleware(lambda _request: None)
        middleware(request)

    @override_settings(YAMTRACK_AUTO_LOGIN_USERNAME=None)
    def test_env_var_unset(self):
        """Test that no auto-login occurs when YAMTRACK_AUTO_LOGIN_USERNAME is unset."""
        request = self.get_request()

        self.run_middleware(request)

        self.assertFalse(request.user.is_authenticated)

    @override_settings(YAMTRACK_AUTO_LOGIN_USERNAME="active_user")
    def test_existing_active_user(self):
        """Test that auto-login works with an existing active user."""
        request = self.get_request()

        self.run_middleware(request)

        self.assertTrue(request.user.is_authenticated)
        self.assertEqual(request.user, self.existing_active_user)

    @override_settings(YAMTRACK_AUTO_LOGIN_USERNAME="missing_user")
    def test_missing_user(self):
        """Test that no auto-login occurs with a missing user."""
        request = self.get_request()

        self.run_middleware(request)

        self.assertFalse(request.user.is_authenticated)

    @override_settings(YAMTRACK_AUTO_LOGIN_USERNAME="inactive_user")
    def test_inactive_user(self):
        """Test that no auto-login occurs with an inactive user."""
        request = self.get_request()

        self.run_middleware(request)

        self.assertFalse(request.user.is_authenticated)


class HtmxAuthRedirectMiddlewareTest(TestCase):
    """Test cases for HtmxAuthRedirectMiddleware (#386)."""

    def setUp(self):
        """Use a logged-out client against a login-required fragment."""
        self.client = Client()
        self.url = reverse("active_playback_fragment")

    def test_htmx_request_gets_hx_redirect(self):
        """An htmx request must get 204 + HX-Redirect, not a followable 302.

        Following the 302 returns the whole login page with a 200, which htmx
        would happily swap into the fragment slot that made the request.
        """
        response = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 204)
        self.assertIn(
            reverse("account_login"),
            response.headers["HX-Redirect"],
        )
        self.assertEqual(response.content, b"")

    def test_plain_request_still_redirects(self):
        """A non-htmx request keeps the normal 302 to the login page."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("HX-Redirect", response.headers)
        self.assertIn(reverse("account_login"), response.headers["Location"])

    def test_non_login_redirect_is_untouched(self):
        """Redirects that aren't to the login page pass through unchanged."""
        user = UserModel.objects.create_user(
            username="htmx_user",
            password="htmx_user_password",  # noqa: S106
        )
        self.client.force_login(user)

        response = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertNotEqual(response.status_code, 204)


class SessionDurabilityTest(TestCase):
    """A cache loss must not log the user out (#386)."""

    def test_session_survives_cache_flush(self):
        """Redis restart/eviction falls back to the database session row."""
        from django.core.cache import cache  # noqa: PLC0415

        user = UserModel.objects.create_user(
            username="session_user",
            password="session_user_password",  # noqa: S106
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get("/").status_code, 200)

        cache.clear()

        self.assertEqual(self.client.get("/").status_code, 200)
