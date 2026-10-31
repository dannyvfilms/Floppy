"""Coverage for provider capability declarations and relocated settings."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from integrations.models import (
    ExternalReference,
    ExternalReferenceReviewStatus,
    ImportRun,
)
from users.provider_catalog import TAB_ORDER, catalog
from users.templatetags.user_tags import source_display


class ProviderSettingsTests(TestCase):
    """Verify the catalog reaches real controls without changing setup."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="provider-user")
        self.client.force_login(self.user)

    def test_metadata_game_filter_includes_primary_and_artwork_sources(self):
        response = self.client.get(
            reverse("providers"), {"capability": "metadata", "media": "game"}
        )
        slugs = {item["slug"] for item in response.context["providers"]}
        self.assertLessEqual(
            {
                "igdb",
                "steamgriddb",
                "screenscraper",
                "thegamesdb",
                "opencritic",
                "steam",
                "libretro",
            },
            slugs,
        )
        self.assertNotIn("goodreads", slugs)

    def test_directory_and_credentials_share_existing_provider_components(self):
        directory = self.client.get(reverse("providers"))
        self.assertTemplateUsed(directory, "users/components/provider_card.html")
        self.assertTemplateUsed(
            directory, "users/components/provider_filter_dropdown.html"
        )
        credentials = self.client.get(
            reverse("provider_detail", args=["hardcover"]), {"tab": "connection"}
        )
        self.assertTemplateUsed(credentials, "users/components/provider_instance_credentials.html")
        self.assertTemplateUsed(credentials, "users/components/provider_personal_credentials.html")

    def test_shared_source_identity_keeps_fallback_labels_safe(self):
        html = str(source_display("unknown", label="A <service>", heading_level=2))
        self.assertIn("A &lt;service&gt;", html)
        self.assertIn("<h2 ", html)
        self.assertNotIn("<service>", html)

    def test_search_combines_with_both_filters(self):
        response = self.client.get(
            reverse("providers"),
            {"q": "steam", "capability": "metadata", "media": "game"},
        )
        self.assertEqual(
            {item["slug"] for item in response.context["providers"]},
            {"steam", "steamgriddb"},
        )

    def test_live_search_returns_only_the_filtered_result_grid(self):
        response = self.client.get(
            reverse("providers"),
            {"q": "steam", "capability": "metadata", "media": "game"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="provider-results",
        )
        self.assertTemplateUsed(response, "users/components/provider_results.html")
        self.assertTemplateNotUsed(response, "users/providers.html")
        self.assertContains(response, 'id="provider-results"')
        self.assertContains(response, "SteamGridDB")
        self.assertNotContains(response, 'id="provider-filter-form"')
        self.assertNotContains(response, "Goodreads")

    def test_file_only_providers_do_not_expose_connection(self):
        for slug in (
            "goodreads",
            "clz",
            "playnite",
            "yamtrack_native",
            "storygraph",
            "tvtime",
        ):
            with self.subTest(slug=slug):
                response = self.client.get(reverse("provider_detail", args=[slug]))
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("connection", response.context["provider"]["tabs"])
                self.assertEqual(
                    self.client.get(
                        reverse("provider_detail", args=[slug]), {"tab": "connection"}
                    ).status_code,
                    404,
                )

    @patch("app.providers.credentials._probe", return_value=None)
    @patch("users.views.tasks.refresh_plex_sections.delay")
    def test_every_declared_tab_renders_and_keeps_canonical_order(
        self, _refresh, _probe
    ):
        before = get_user_model().objects.values().get(pk=self.user.pk)
        for item in catalog():
            self.assertEqual(
                item["tabs"], [tab for tab in TAB_ORDER if tab in item["tabs"]]
            )
            for tab in item["tabs"]:
                with self.subTest(provider=item["slug"], tab=tab):
                    response = self.client.get(
                        reverse("provider_detail", args=[item["slug"]]), {"tab": tab}
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'aria-current="page"')
        self.assertEqual(get_user_model().objects.values().get(pk=self.user.pk), before)

    def test_activity_filters_runs_before_limiting_and_stays_owned(self):
        other = get_user_model().objects.create_user(username="another-provider-user")
        own = ImportRun.objects.create(user=self.user, source="plex", status="finished")
        ImportRun.objects.create(user=other, source="plex", status="finished")
        for _ in range(12):
            ImportRun.objects.create(user=self.user, source="trakt", status="finished")
        with patch(
            "users.models.User.get_import_tasks",
            return_value={"results": [], "schedules": []},
        ):
            response = self.client.get(
                reverse("import_data_activity"), {"source": "plex"}
            )
        self.assertEqual(response.status_code, 286)
        self.assertEqual([run.pk for run in response.context["import_runs"]], [own.pk])

    def test_provider_match_queue_is_filtered_before_its_limit(self):
        reference = ExternalReference.objects.create(
            user=self.user,
            integration="trakt",
            external_namespace="movie",
            external_identity="older-trakt",
            media_type="movie",
            review_status=ExternalReferenceReviewStatus.NEEDS_REVIEW,
        )
        ExternalReference.objects.bulk_create(
            [
                ExternalReference(
                    user=self.user,
                    integration="plex",
                    external_namespace="movie",
                    external_identity=f"newer-plex-{index}",
                    media_type="movie",
                    review_status=ExternalReferenceReviewStatus.NEEDS_REVIEW,
                )
                for index in range(101)
            ]
        )
        response = self.client.get(
            reverse("provider_detail", args=["trakt"]), {"tab": "activity"}
        )
        self.assertEqual(
            [entry.pk for entry in response.context["match_review_references"]],
            [reference.pk],
        )

    def test_settings_destinations_require_sign_in(self):
        self.client.logout()
        for route in (
            "providers",
            "provider_activity",
            "data_management",
            "access_tokens",
        ):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response["Location"])

    def test_unknown_provider_and_tab_are_not_rendered(self):
        self.assertEqual(
            self.client.get(reverse("provider_detail", args=["missing"])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("provider_detail", args=["igdb"]), {"tab": "sync"}
            ).status_code,
            404,
        )

    def test_legacy_import_deep_link_preserves_options(self):
        response = self.client.get(
            reverse("import_data"), {"open": "myanimelist", "onboarding": "1"}
        )
        self.assertRedirects(
            response,
            reverse("provider_detail", args=["mal"])
            + "?open=myanimelist&onboarding=1&setup_flow=import&tab=import",
        )

    def test_central_destinations_render(self):
        for route in ("provider_activity", "data_management", "access_tokens"):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route)).status_code, 200)
