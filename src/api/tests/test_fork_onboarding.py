# FORK: tests for the first-run setup wizard JSON endpoint.
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from rest_framework.response import Response

from integrations.models import IntegrationToken

from .base import FloppyApiTestCase


class OnboardingApiTests(FloppyApiTestCase):
    """GET/POST user/onboarding."""

    def get(self, **params):
        return self.call_api("get", "api_user_onboarding", params=params or None, headers=self.auth_headers)

    def post(self, payload, headers=None):
        return self.call_api("post", "api_user_onboarding", payload=payload, headers=headers or self.auth_headers)

    def test_fresh_account_starts_on_media_types(self):
        body = self.get().json()
        self.assertEqual(body["step"], "media_types")
        self.assertTrue(body["offer"])
        values = [o["value"] for o in body["mediaTypes"]["options"]]
        self.assertIn("movie", values)
        self.assertNotIn("season", values)
        self.assertEqual(body["activeStep"], "media_types")
        self.assertTrue(body["heroUrl"].endswith("img/floppy-hero.png"))
        self.assertIn("viewBox", body["mediaTypes"]["options"][0]["icon"])

    def test_requires_authentication(self):
        response = self.call_api("get", "api_user_onboarding", headers=self.invalid_auth_headers)
        self.assertIn(response.status_code, {HTTP.UNAUTHORIZED, HTTP.FORBIDDEN})

    def test_media_types_requires_a_choice(self):
        response = self.post({"action": "media_types", "mediaTypes": []})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_walks_the_wizard_to_completion(self):
        body = self.post({"action": "media_types", "mediaTypes": ["movie"], "order": ["movie"]}).json()
        self.user1.refresh_from_db()
        self.assertTrue(self.user1.movie_enabled)
        self.assertFalse(self.user1.tv_enabled)
        self.assertEqual(self.user1.onboarding_status, "in_progress")
        # Nothing to add for movies without TMDB suggestions would skip; either
        # way the wizard must land on a step that exists.
        if body["step"] == "metadata":
            body = self.post({"action": "skip_metadata"}).json()
        self.assertEqual(body["step"], "services")
        self.assertEqual(body["services"]["mediaType"], "movie")
        self.assertEqual(body["services"]["total"], 1)
        candidates = [c["slug"] for c in body["services"]["candidates"]]
        pick = candidates[:1]
        body = self.post({"action": "services", "index": 0, "sources": pick + ["not-a-source"]}).json()
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.onboarding_selected_sources, pick)
        self.assertEqual(body["step"], "services_summary")
        body = self.post({"action": "later"}).json()
        self.assertEqual(body["status"], "completed")
        self.assertFalse(body["offer"])
        body = self.post({"action": "restart"}).json()
        self.assertEqual(body["step"], "media_types")

    def test_skip_marks_setup_complete(self):
        body = self.post({"action": "skip"}).json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["step"], "done")

    def test_malformed_next_index_is_400_and_applies_nothing(self):
        response = self.post({"action": "skip", "nextIndex": "two"})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.user1.refresh_from_db()
        self.assertNotEqual(self.user1.onboarding_status, "completed")

    def test_unknown_action_is_rejected(self):
        self.assertEqual(self.post({"action": "nope"}).status_code, HTTP.BAD_REQUEST)

    def test_demo_accounts_get_no_wizard(self):
        self.user1.is_demo = True
        self.user1.save(update_fields=["is_demo"])
        body = self.get().json()
        self.assertFalse(body["offer"])
        self.assertEqual(self.post({"action": "skip"}).status_code, HTTP.BAD_REQUEST)

    def test_scoped_token_cannot_save_provider_keys(self):
        _token, raw = IntegrationToken.generate(
            user=self.user1, name="app", client_identifier="app", scopes=["user:read", "user:write"],
        )
        headers = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
        self.user1.game_enabled = True
        self.user1.onboarding_step = "metadata"
        self.user1.save(update_fields=["game_enabled", "onboarding_step"])
        response = self.post({"action": "metadata", "values": {"steamgriddb-api_key": "abc"}}, headers=headers)
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        read_only = IntegrationToken.generate(
            user=self.user1, name="ro", client_identifier="ro", scopes=["user:read"],
        )[1]
        denied = self.post({"action": "skip"}, headers={"HTTP_AUTHORIZATION": f"Bearer {read_only}"})
        self.assertEqual(denied.status_code, HTTP.FORBIDDEN)

    def test_other_users_state_is_untouched(self):
        self.post({"action": "skip"})
        self.user2.refresh_from_db()
        self.assertEqual(self.user2.onboarding_status, "not_started")


class OnboardingServicesWalkTests(FloppyApiTestCase):
    """The services step walks one media type at a time."""

    def test_next_index_follows_the_enabled_media_types(self):
        for media_type in ("movie", "tv"):
            setattr(self.user1, f"{media_type}_enabled", True)
        self.user1.onboarding_status = "in_progress"
        self.user1.onboarding_step = "services"
        self.user1.save()
        first = self.call_api("get", "api_user_onboarding", headers=self.auth_headers).json()
        self.assertEqual(first["services"]["index"], 0)
        self.assertGreater(first["services"]["total"], 1)
        second = self.call_api(
            "post",
            "api_user_onboarding",
            payload={"action": "services", "index": 0, "sources": []},
            headers=self.auth_headers,
        ).json()
        self.assertEqual(second["step"], "services")
        self.assertEqual(second["services"]["index"], 1)
        self.assertFalse(second["services"]["isLast"] and second["services"]["total"] > 2)


class OnboardingInlineSetupTests(FloppyApiTestCase):
    """Inline setup keeps the web source contract and credential permissions."""

    def setUp(self):
        super().setUp()
        self.user1.onboarding_status = "in_progress"
        self.user1.onboarding_step = "service_setup"
        self.user1.onboarding_selected_sources = ["radarr", "goodreads"]
        self.user1.save()

    def connect(self, payload, headers=None):
        return self.call_api("post", "api_user_onboarding", headers=headers or self.auth_headers,
                             payload={"action": "connect_service", **payload})

    def test_service_model_exposes_fields_and_setup_copy_without_credentials(self):
        body = self.call_api("get", "api_user_onboarding", headers=self.auth_headers).json()
        source = body["serviceSetup"]["source"]
        self.assertEqual(source["slug"], "radarr")
        self.assertEqual(source["setupCopy"], "Requires your server URL and an API key.")
        self.assertEqual(source["connectFields"], [
            {"name": "base_url", "label": "Base URL", "type": "url"},
            {"name": "api_key", "label": "API Key", "type": "password"},
        ])
        self.assertNotIn("value", source["connectFields"][1])

    def test_inline_connect_delegates_only_declared_fields_and_advances(self):
        with patch("api.fork_views_providers._call", return_value=Response({"ok": True})) as delegated:
            response = self.connect({"slug": "radarr", "values": {
                "base_url": "https://radarr.example.test", "api_key": "test-only", "is_superuser": True,
            }})
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.assertEqual(response.json()["serviceSetup"]["source"]["slug"], "goodreads")
        post = delegated.call_args.kwargs["post"]
        self.assertEqual(post["base_url"], "https://radarr.example.test")
        self.assertNotIn("is_superuser", post)
        self.assertEqual(post["frequency"], "once")
        self.assertIn("radarr", self.user1.__class__.objects.get(pk=self.user1.pk).onboarding_connected_sources)

    def test_failed_connect_keeps_service_in_queue(self):
        with patch("api.fork_views_providers._call", return_value=Response({"detail": "Connection refused."}, status=400)):
            response = self.connect({"slug": "radarr", "values": {}})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.user1.refresh_from_db()
        self.assertNotIn("radarr", self.user1.onboarding_connected_sources)

    def test_upload_uses_existing_bounds_and_does_not_advance_on_failure(self):
        response = self.connect({"slug": "goodreads", "name": "bad.zip", "content": "bad"})
        self.assertEqual(response.status_code, HTTP.UNSUPPORTED_MEDIA_TYPE)
        self.user1.refresh_from_db()
        self.assertNotIn("goodreads", self.user1.onboarding_connected_sources)

    def test_successful_upload_advances_only_after_the_upload_api_accepts_it(self):
        with patch("api.fork_views_providers.ProviderFileImportView.post", return_value=Response({"task_id": "test-task"}, status=202)):
            response = self.connect({"slug": "goodreads", "name": "books.csv", "content": "Title\nBook\n"})
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.onboarding_connected_sources, ["goodreads"])

    def test_only_selected_sources_and_full_account_credentials_may_connect(self):
        self.assertEqual(self.connect({"slug": "sonarr", "values": {}}).status_code, HTTP.BAD_REQUEST)
        _token, raw = IntegrationToken.generate(user=self.user1, name="scoped", scopes=["user:write"])
        response = self.connect({"slug": "radarr", "values": {}}, headers={"HTTP_AUTHORIZATION": f"Bearer {raw}"})
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.onboarding_connected_sources, [])


class AccountRouteTests(FloppyApiTestCase):
    """The native account contract lives at the slashless route."""

    def test_account_route_has_no_trailing_slash(self):
        from django.urls import Resolver404, resolve

        self.assertEqual(resolve("/settings/account").url_name, "account")
        with self.assertRaises(Resolver404):
            resolve("/settings/account/")
