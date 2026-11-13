from django.test import TestCase
from django.urls import reverse

from users.models import User


class StremioConfigurePageTests(TestCase):
    """The standalone configure page keeps a working fallback for its shared UI."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="stremio-configure",
            password="test-only-password",
        )

    def test_page_mounts_the_shared_configurator_over_the_server_fallback(self):
        response = self.client.get(
            reverse("stremio_addon_configure", args=[self.user.token])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-stremio-config-root")
        self.assertContains(response, 'id="stremio-config-props"')
        self.assertContains(response, "data-stremio-config-fallback")
        self.assertContains(response, "settings-islands.js")
        self.assertContains(response, "Install in Stremio")

    def test_configured_url_serializes_the_selected_catalog_order(self):
        response = self.client.get(
            reverse(
                "stremio_addon_configure_configured",
                args=[
                    self.user.token,
                    "floppy-history-series,floppy-watchlist-movies",
                ],
            )
        )

        self.assertContains(response, '"selectedIds": ["floppy-history-series", "floppy-watchlist-movies"]')
