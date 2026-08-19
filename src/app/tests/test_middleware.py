from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from app.middleware import (
    AutoLoginMiddleware,
    NoStoreHtmlMiddleware,
    SessionInterruptedMiddleware,
)

UserModel = get_user_model()


class AutoLoginMiddlewareTest(TestCase):
    """Test cases for AutoLoginMiddleware."""

    def setUp(self):
        """Create test users."""
        self.factory = RequestFactory()
        self.existing_active_user = UserModel.objects.create_user(
            username="active_user",
            password="active_user_password",
            is_active=True,
        )
        self.existing_inactive_user = UserModel.objects.create_user(
            username="inactive_user",
            password="inactive_user_password",
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

    @override_settings(FLOPPY_AUTO_LOGIN_USERNAME=None)
    def test_env_var_unset(self):
        """Test that no auto-login occurs when FLOPPY_AUTO_LOGIN_USERNAME is unset."""
        request = self.get_request()

        self.run_middleware(request)

        self.assertFalse(request.user.is_authenticated)

    @override_settings(FLOPPY_AUTO_LOGIN_USERNAME="active_user")
    def test_existing_active_user(self):
        """Test that auto-login works with an existing active user."""
        request = self.get_request()

        self.run_middleware(request)

        self.assertTrue(request.user.is_authenticated)
        self.assertEqual(request.user, self.existing_active_user)

    @override_settings(FLOPPY_AUTO_LOGIN_USERNAME="missing_user")
    def test_missing_user(self):
        """Test that no auto-login occurs with a missing user."""
        request = self.get_request()

        self.run_middleware(request)

        self.assertFalse(request.user.is_authenticated)

    @override_settings(FLOPPY_AUTO_LOGIN_USERNAME="inactive_user")
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
            password="htmx_user_password",
        )
        self.client.force_login(user)

        response = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertNotEqual(response.status_code, 204)


class SessionInterruptedMiddlewareTest(TestCase):
    """A session row deleted mid-request must redirect, not 400 (#622)."""

    def setUp(self):
        """Use a request factory to drive the middleware directly."""
        self.factory = RequestFactory()

    def test_session_interrupted_redirects_instead_of_500(self):
        """A stale tab's session race is recovered instead of propagating."""

        def get_response(_request):
            raise SessionInterrupted("The request's session was deleted.")

        middleware = SessionInterruptedMiddleware(get_response)
        request = self.factory.post("/import/simkl-oauth")

        response = middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse(django_settings.LOGIN_REDIRECT_URL),
            response.headers["Location"],
        )

    def test_unaffected_requests_pass_through(self):
        """Requests that don't hit the race are untouched."""

        def get_response(_request):
            return HttpResponse("ok")

        middleware = SessionInterruptedMiddleware(get_response)
        request = self.factory.get("/")

        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


class SessionDurabilityTest(TestCase):
    """A cache loss must not log the user out (#386)."""

    def test_session_survives_cache_flush(self):
        """Redis restart/eviction falls back to the database session row."""
        from django.core.cache import cache

        user = UserModel.objects.create_user(
            username="session_user",
            password="session_user_password",
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get("/").status_code, 200)

        cache.clear()

        self.assertEqual(self.client.get("/").status_code, 200)


class NoStoreHtmlMiddlewareTest(TestCase):
    """HTML must not be heuristically cacheable by iOS Safari (#442)."""

    def setUp(self):
        """Create a logged-in client and a bare request factory."""
        self.factory = RequestFactory()
        self.user = UserModel.objects.create_user(
            username="no_store_user",
            password="no_store_password",
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _apply(self, response, path="/"):
        middleware = NoStoreHtmlMiddleware(lambda _request: response)
        return middleware(self.factory.get(path))

    def test_html_response_is_marked_no_store(self):
        """A rendered page tells the browser never to reuse the markup."""
        response = self._apply(HttpResponse("<html></html>"))

        self.assertEqual(response["Cache-Control"], "no-store, must-revalidate")

    def test_static_assets_keep_their_cache_headers(self):
        """Cache-busted static files stay cacheable."""
        response = self._apply(
            HttpResponse("<html></html>"),
            path="/static/css/main.css",
        )

        self.assertFalse(response.has_header("Cache-Control"))

    def test_non_html_responses_are_untouched(self):
        """JSON API responses are left alone."""
        response = self._apply(HttpResponse("{}", content_type="application/json"))

        self.assertFalse(response.has_header("Cache-Control"))

    def test_existing_cache_control_is_preserved(self):
        """A view that set its own policy wins."""
        existing = HttpResponse("<html></html>")
        existing.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

        self.assertEqual(
            self._apply(existing)["Cache-Control"],
            "no-cache, no-store, must-revalidate",
        )

    def test_rendered_page_is_no_store_end_to_end(self):
        """The header survives the real middleware stack."""
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store, must-revalidate")
