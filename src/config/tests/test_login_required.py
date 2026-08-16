"""Tests for authentication posture and anonymous route access.

Verifies that:
1. Dead LOGIN_REQUIRED_EXEMPT configuration is not present.
2. Global LoginRequiredMiddleware protects authenticated routes by default.
3. Intended public routes explicitly allow anonymous access via @login_not_required.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item
from app.models.choices import MediaTypes, Sources
from lists.models import CustomList, CustomListItem


class LoginRequiredConfigurationTests(TestCase):
    """Test suite for global authentication settings and route policies."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="auth-test-user",
            password="test-pass-123",
        )
        self.public_list = CustomList.objects.create(
            name="Public Test List",
            description="A list open to the public",
            owner=self.user,
            visibility="public",
            public_slug="public-test-slug",
        )
        self.private_list = CustomList.objects.create(
            name="Private Test List",
            description="A list restricted to owner",
            owner=self.user,
            visibility="private",
            public_slug="private-test-slug",
        )
        self.movie_item = Item.objects.create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Public Movie Item",
        )
        CustomListItem.objects.create(
            custom_list=self.public_list,
            item=self.movie_item,
        )

    def test_login_required_exempt_setting_is_removed(self):
        """LOGIN_REQUIRED_EXEMPT setting must not exist on settings."""
        self.assertFalse(
            hasattr(settings, "LOGIN_REQUIRED_EXEMPT"),
            "LOGIN_REQUIRED_EXEMPT is dead configuration and must remain removed.",
        )

    def test_anonymous_health_and_ping_probes_return_200(self):
        """Liveness health probes must remain accessible without authentication."""
        for path in ["/health/", "/ping/"]:
            response = self.client.get(path)
            self.assertEqual(
                response.status_code,
                200,
                f"Expected HTTP 200 for anonymous GET to {path}, got {response.status_code}",
            )

    def test_anonymous_full_health_check_bypasses_login_gate(self):
        """Full health check endpoint must execute without redirecting to login."""
        response = self.client.get("/health/full/")
        self.assertNotEqual(
            response.status_code,
            302,
            "Full health check must not redirect to login gate",
        )
        self.assertIn(response.status_code, (200, 500))

    def test_anonymous_service_worker_returns_200(self):
        """Service worker script must remain accessible without authentication."""
        response = self.client.get(reverse("service_worker"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")

    def test_anonymous_api_schema_and_docs_return_200(self):
        """OpenAPI schema and documentation endpoints must be accessible without login."""
        for endpoint in [reverse("schema"), reverse("openapi-contract"), reverse("swagger-ui")]:
            response = self.client.get(endpoint)
            self.assertEqual(
                response.status_code,
                200,
                f"Expected HTTP 200 for anonymous GET to {endpoint}, got {response.status_code}",
            )

    def test_anonymous_public_list_detail_returns_200(self):
        """Public list details must remain accessible by ID and slug without authentication."""
        for ref in [str(self.public_list.id), self.public_list.public_slug]:
            response = self.client.get(reverse("list_detail", args=[ref]))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Public Test List")

    def test_anonymous_public_list_rss_feed_returns_200(self):
        """Public list RSS feeds must remain accessible by ID and slug without authentication."""
        for ref in [str(self.public_list.id), self.public_list.public_slug]:
            response = self.client.get(reverse("list_rss", args=[ref]))
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"rss", response.content)

    def test_anonymous_public_list_json_export_returns_200(self):
        """Public list JSON exports must remain accessible by ID and slug without authentication."""
        for ref in [str(self.public_list.id), self.public_list.public_slug]:
            response = self.client.get(reverse("list_json", args=[ref]) + "?arr=radarr")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/json")

    def test_anonymous_public_list_csv_export_returns_200(self):
        """Public list CSV exports must remain accessible without authentication."""
        for ref in [str(self.public_list.id), self.public_list.public_slug]:
            response = self.client.get(reverse("list_export_csv", args=[ref]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "text/csv")

    def test_anonymous_private_list_endpoints_return_404(self):
        """Private lists must return 404 to anonymous requests."""
        for ref in [str(self.private_list.id), self.private_list.public_slug]:
            self.assertEqual(self.client.get(reverse("list_detail", args=[ref])).status_code, 404)
            self.assertEqual(self.client.get(reverse("list_rss", args=[ref])).status_code, 404)
            self.assertEqual(self.client.get(reverse("list_json", args=[ref]) + "?arr=radarr").status_code, 404)
            self.assertEqual(self.client.get(reverse("list_export_csv", args=[ref])).status_code, 404)

    def test_anonymous_protected_routes_redirect_to_login(self):
        """Protected application routes must redirect anonymous requests to the login page."""
        protected_routes = [
            reverse("lists"),
            reverse("list_create"),
            reverse("account"),
            reverse("ui_preferences"),
        ]
        for url in protected_routes:
            response = self.client.get(url)
            self.assertEqual(
                response.status_code,
                302,
                f"Expected HTTP 302 redirect for anonymous GET to {url}, got {response.status_code}",
            )
            self.assertIn("/accounts/login/", response["Location"])
