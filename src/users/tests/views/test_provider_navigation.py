"""Regression checks for provider navigation and preserved access credentials."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from integrations.models import CatalogGrant
from users.views import NEW_TOKEN_SESSION_KEY


class ProviderNavigationTests(TestCase):
    """Relocation must preserve working destinations and scoped setup state."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="member")
        self.other_user = get_user_model().objects.create_user(username="other")
        self.client.force_login(self.user)

    def test_invalid_capability_does_not_poison_directory_links(self):
        response = self.client.get(reverse("providers"), {"capability": "invalid"})

        self.assertContains(response, reverse("provider_detail", args=["steam"]))
        self.assertNotContains(response, "?tab=invalid")

    def test_legacy_provider_link_never_selects_an_unsupported_tab(self):
        response = self.client.get(
            reverse("integrations"),
            {"open": "steam"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["provider_slug"], "steam")
        self.assertIn(
            response.context["provider_tab"],
            response.context["provider"]["tabs"],
        )

    def test_stremio_keeps_own_install_grants_and_one_time_app_secret(self):
        own_grant, own_token = CatalogGrant.generate(self.user, "Living room")
        other_grant, other_token = CatalogGrant.generate(
            self.other_user, "Other install"
        )
        session = self.client.session
        session[NEW_TOKEN_SESSION_KEY] = {
            "name": "New app",
            "secret": "one-time-app-secret",
        }
        session.save()

        response = self.client.get(
            reverse("provider_detail", args=["stremio"]),
            {"tab": "connection"},
        )

        self.assertContains(response, own_grant.name)
        self.assertContains(response, own_token)
        self.assertNotContains(response, other_grant.name)
        self.assertNotContains(response, other_token)
        self.assertNotContains(response, "one-time-app-secret")
        self.assertIn(NEW_TOKEN_SESSION_KEY, self.client.session)

        access = self.client.get(reverse("access_tokens"))
        self.assertContains(access, "one-time-app-secret")
        self.assertNotIn(NEW_TOKEN_SESSION_KEY, self.client.session)

    def test_creating_stremio_install_returns_to_its_management_controls(self):
        response = self.client.post(
            reverse("create_catalog_grant"),
            {"name": "Living room"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["provider_slug"], "stremio")
        self.assertEqual(response.context["provider_tab"], "connection")
        grant = CatalogGrant.objects.get(user=self.user)
        self.assertContains(response, reverse("revoke_catalog_grant", args=[grant.pk]))

    @patch("integrations.tmdb_views.rating_sync_status")
    def test_central_activity_includes_tmdb_delivery_records(self, status):
        status.return_value = {
            "account": None,
            "enabled": False,
            "counts": {"pending": 17},
            "recent": [],
        }

        response = self.client.get(reverse("provider_activity"))

        self.assertEqual(response.status_code, 200)
        status.assert_called_once_with(self.user)
        self.assertContains(response, "Waiting 17")
