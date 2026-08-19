from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from app.error_views import csrf_failure


@override_settings(
    DEBUG=False,
    ROOT_URLCONF="app.tests.urls_error_pages",
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
)
class ErrorPageTests(TestCase):
    """Verify custom error pages render copyable traceback panels."""

    def setUp(self):
        """Set up non-raising clients for error-page assertions."""
        self.client = Client()
        self.client.raise_request_exception = False
        self.csrf_client = Client(enforce_csrf_checks=True)
        self.csrf_client.raise_request_exception = False

    def assert_traceback_panel(self, response, panel_id):
        """Assert the shared traceback panel rendered on the response."""
        expected_status = response.status_code
        self.assertContains(
            response,
            f'data-copy-target="#{panel_id}"',
            status_code=expected_status,
            html=False,
        )
        self.assertContains(
            response,
            f'id="{panel_id}"',
            status_code=expected_status,
            html=False,
        )
        self.assertContains(
            response,
            "Copy this block when opening a ticket",
            status_code=expected_status,
            html=False,
        )

    def test_bad_request_page_includes_copyable_traceback(self):
        """The 400 page should expose a copyable traceback report."""
        response = self.client.get("/boom-400/")

        self.assertEqual(response.status_code, 400)
        self.assert_traceback_panel(response, "error-report-400")
        self.assertContains(
            response,
            "SuspiciousOperation: Broken payload",
            status_code=400,
            html=False,
        )

    def test_permission_denied_page_includes_copyable_traceback(self):
        """The 403 page should expose a copyable traceback report."""
        response = self.client.get("/boom-403/")

        self.assertEqual(response.status_code, 403)
        self.assert_traceback_panel(response, "error-report-403")
        self.assertContains(
            response,
            "PermissionDenied: Forbidden area",
            status_code=403,
            html=False,
        )

    def test_not_found_page_includes_copyable_traceback(self):
        """The 404 page should expose a copyable traceback report."""
        response = self.client.get("/boom-404/")

        self.assertEqual(response.status_code, 404)
        self.assert_traceback_panel(response, "error-report-404")
        self.assertContains(
            response,
            "Http404: Missing object",
            status_code=404,
            html=False,
        )

    def test_server_error_page_includes_copyable_traceback(self):
        """The 500 page should expose a copyable traceback report."""
        response = self.client.get("/boom-500/")

        self.assertEqual(response.status_code, 500)
        self.assert_traceback_panel(response, "error-report-500")
        self.assertContains(
            response,
            "RuntimeError: Kaboom",
            status_code=500,
            html=False,
        )

    def test_hardcover_401_page_shows_api_token_expiry_help(self):
        """Hardcover 401s should show token-expiry guidance and a docs link."""
        response = self.client.get("/boom-hardcover-401/")

        self.assertEqual(response.status_code, 500)
        self.assert_traceback_panel(response, "error-report-500")
        self.assertContains(
            response,
            "Hardcover token expired",
            status_code=500,
            html=False,
        )
        self.assertContains(
            response,
            "src/config/settings.py",
            status_code=500,
            html=False,
        )
        self.assertContains(
            response,
            "https://docs.hardcover.app/api/getting-started/",
            status_code=500,
            html=False,
        )

    def test_csrf_failure_redirects_anonymous_user_to_login(self):
        """Anonymous CSRF failures should bounce to login, not a dead end."""
        response = self.csrf_client.post("/csrf-protected/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.headers["Location"])

    def test_csrf_failure_returns_authenticated_user_to_their_page(self):
        """A logged-in user keeps their session and retries with a fresh token."""
        get_user_model().objects.create_user(username="csrf-user", password="12345")
        self.csrf_client.login(username="csrf-user", password="12345")

        response = self.csrf_client.post("/csrf-protected/", HTTP_REFERER="/")

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("/accounts/login/", response.headers["Location"])

    def test_csrf_failure_on_login_page_does_not_loop(self):
        """A CSRF-rejected login POST must explain itself, not bounce to login.

        Redirecting here sends the user back to the form they just submitted,
        so they retry, fail CSRF again, and loop forever with no diagnostics
        (#386).
        """
        with override_settings(ROOT_URLCONF="config.urls"):
            login_url = reverse("account_login")
            response = self.csrf_client.post(
                login_url,
                {"login": "someone", "password": "12345"},
                HTTP_REFERER="http://testserver" + login_url,
            )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "USE_X_FORWARDED", status_code=403)

    def test_csrf_failure_page_includes_copyable_report(self):
        """The rendered CSRF page should expose a copyable diagnostic report.

        Only reachable when the request has no user attached, since an
        authenticated or anonymous user is redirected instead.
        """
        request = RequestFactory().post("/csrf-protected/")
        response = csrf_failure(request, reason="CSRF token missing")

        self.assertEqual(response.status_code, 403)
        self.assert_traceback_panel(response, "error-report-403-csrf")
        self.assertContains(
            response,
            "CSRF verification failed",
            status_code=403,
            html=False,
        )
        self.assertContains(
            response,
            "Traceback unavailable",
            status_code=403,
            html=False,
        )
