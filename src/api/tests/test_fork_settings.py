# FORK: tests for the settings endpoints the native app uses.
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from integrations.models import IntegrationToken

from .base import FloppyApiTestCase


class SettingsTestCase(FloppyApiTestCase):
    """Shared helpers."""

    def make_superuser(self):
        self.user1.is_superuser = True
        self.user1.save(update_fields=["is_superuser"])

    def scoped_headers(self, *scopes):
        _token, raw = IntegrationToken.generate(
            user=self.user1, name="scoped", scopes=list(scopes)
        )
        return {"HTTP_X_API_KEY": raw}


class PreferencesExtensionTests(SettingsTestCase):
    """The preferences fields the web form saves and the native app dropped."""

    def test_get_reports_superuser_and_new_fields(self):
        data = self.call_api(
            "get", "api_user_preferences", headers=self.auth_headers
        ).json()
        self.assertFalse(data["is_superuser"])
        for field in ("theme", "logo_style", "ui_language", "show_recommendations"):
            self.assertIn(field, data["preferences"])
        self.assertIn("auto_pause_rules", data["preferences"])
        self.assertIn("theme", data["choices"])
        self.make_superuser()
        data = self.call_api(
            "get", "api_user_preferences", headers=self.auth_headers
        ).json()
        self.assertTrue(data["is_superuser"])

    @patch("app.providers.tmdb.metadata_languages", return_value=[("", "Default")])
    @patch("app.providers.tmdb.watch_provider_regions", return_value=[("US", "US")])
    def test_patch_saves_region(self, *_mocks):
        response = self.call_api(
            "patch",
            "api_user_preferences",
            payload={"watch_provider_region": "US"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        bad = self.call_api(
            "patch",
            "api_user_preferences",
            payload={"watch_provider_region": "ZZ"},
            headers=self.auth_headers,
        )
        self.assertEqual(bad.status_code, HTTP.BAD_REQUEST)

    def test_patch_saves_theme_logo_language_recommendations_rules(self):
        response = self.call_api(
            "patch",
            "api_user_preferences",
            payload={
                "theme": "dracula",
                "logo_style": "monochrome",
                "show_recommendations": False,
                "auto_pause_rules": [
                    {"library": "all", "weeks": 3},
                    {"library": "bogus", "weeks": 9},
                ],
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.theme, "dracula")
        self.assertFalse(self.user1.show_recommendations)
        self.assertEqual(self.user1.auto_pause_rules, [{"library": "all", "weeks": 3}])

    def test_patch_rejects_unknown_theme(self):
        response = self.call_api(
            "patch",
            "api_user_preferences",
            payload={"theme": "neon"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    @patch("app.providers.tmdb.metadata_languages", return_value=[("", "Default")])
    @patch("app.providers.tmdb.watch_provider_regions", return_value=[("US", "US")])
    def test_choices_endpoint(self, *_mocks):
        response = self.call_api(
            "get", "api_settings_user_preferences_choices", headers=self.auth_headers
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIn("watch_provider_region", response.json())
        self.assertIn("metadata_language", response.json())

    @patch("app.providers.tmdb.metadata_languages", return_value=[("", "Default")])
    @patch("app.providers.tmdb.watch_provider_regions", side_effect=RuntimeError("offline"))
    def test_unavailable_provider_still_allows_disabling_regions(self, *_mocks):
        choices = self.call_api(
            "get", "api_settings_user_preferences_choices", headers=self.auth_headers
        )
        self.assertEqual(choices.json()["watch_provider_region"], [["", "Disabled"]])
        response = self.call_api(
            "patch", "api_user_preferences", payload={"watch_provider_region": ""},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)


class NotificationsRegressionTests(SettingsTestCase):
    """A partial PATCH must not reset fields it omits."""

    def test_partial_patch_keeps_premiere_and_playback_webhook(self):
        self.user1.premiere_notifications_enabled = True
        self.user1.playback_webhook_url = "https://relay.example.com/p/1"
        self.user1.save(
            update_fields=["premiere_notifications_enabled", "playback_webhook_url"]
        )
        response = self.call_api(
            "patch",
            "api_user_notifications",
            payload={"daily_digest_enabled": True},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.user1.refresh_from_db()
        self.assertTrue(self.user1.premiere_notifications_enabled)
        self.assertEqual(
            self.user1.playback_webhook_url, "https://relay.example.com/p/1"
        )
        self.assertTrue(response.json()["premiere_notifications_enabled"])
        self.assertTrue(response.json()["playback_webhook_configured"])

    def test_premiere_toggle_is_writable(self):
        response = self.call_api(
            "patch",
            "api_user_notifications",
            payload={"premiere_notifications_enabled": False},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.user1.refresh_from_db()
        self.assertFalse(self.user1.premiere_notifications_enabled)


class AppearanceCardsHomeTests(SettingsTestCase):
    """Appearance, cards and home screen round trips."""

    def test_appearance_round_trip(self):
        data = self.call_api(
            "get", "api_settings_user_appearance", headers=self.auth_headers
        ).json()
        self.assertIn("dracula", data["presets"])
        self.assertIn("media", data["families"])
        response = self.call_api(
            "put",
            "api_settings_user_appearance",
            payload={
                "theme": "custom",
                "custom_theme": {"accent": "#112233", "radius": 10},
                "detail_layouts": {},
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.theme, "custom")
        self.assertEqual(self.user1.custom_theme["accent"], "#112233")
        self.assertEqual(response.json()["palette"]["accent"], "#112233")

    def test_appearance_rejects_bad_values_without_partial_save(self):
        before = self.user1.theme
        for payload in (
            {"theme": "nope"},
            {"theme": "custom", "custom_theme": {"accent": "red"}},
            {"theme": "dark", "detail_layouts": {"media": {"x": []}}},
        ):
            response = self.call_api(
                "put",
                "api_settings_user_appearance",
                payload=payload,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.theme, before)

    def test_demo_account_cannot_save_appearance(self):
        self.user1.is_demo = True
        self.user1.save(update_fields=["is_demo"])
        response = self.call_api(
            "put",
            "api_settings_user_appearance",
            payload={"theme": "dark"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_cards_round_trip(self):
        data = self.call_api(
            "get", "api_settings_user_cards", headers=self.auth_headers
        ).json()
        self.assertTrue(data["catalog"])
        self.assertIn("movie", data["profiles"])
        response = self.call_api(
            "put",
            "api_settings_user_cards",
            payload={
                "card_metadata": {
                    "types": {"movie": {"display": "always", "fields": ["year"]}}
                },
                "clickable_media_cards": True,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.user1.refresh_from_db()
        self.assertTrue(self.user1.clickable_media_cards)
        self.assertIn("movie", self.user1.card_metadata["types"])

    def test_scoped_token_needs_user_scopes(self):
        reader = self.scoped_headers("user:read")
        self.assertEqual(
            self.call_api("get", "api_settings_user_cards", headers=reader).status_code,
            HTTP.OK,
        )
        self.assertEqual(
            self.call_api(
                "put",
                "api_settings_user_cards",
                payload={"clickable_media_cards": True},
                headers=reader,
            ).status_code,
            HTTP.FORBIDDEN,
        )

    def test_home_screen_round_trip(self):
        data = self.call_api(
            "get", "api_settings_user_home_screen", headers=self.auth_headers
        ).json()
        self.assertIn("sections", data)
        self.assertTrue(data["sections"])
        self.assertIn("viewBox", data["sections"][0]["icon"])
        self.assertTrue(data["sections"][0]["icon"]["children"])
        response = self.call_api(
            "put",
            "api_settings_user_home_screen",
            payload={
                "sections": data["sections"],
                "show_media_type_headers": True,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.user1.refresh_from_db()
        self.assertTrue(self.user1.home_show_media_type_headers)

    def test_home_screen_rejects_invalid_sections(self):
        response = self.call_api(
            "put",
            "api_settings_user_home_screen",
            payload={"sections": [{"media_type": "nonsense"}]},
            headers=self.auth_headers,
        )
        self.assertIn(response.status_code, {HTTP.BAD_REQUEST, HTTP.OK})

    def test_invalid_home_sections_return_the_message(self):
        response = self.call_api(
            "put",
            "api_settings_user_home_screen",
            payload={"sections": "not a list"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(
            response.json(), {"detail": "Home Screen settings payload must be a list."}
        )

    def test_filter_fields_unknown_media_type(self):
        response = self.call_api(
            "get",
            "api_settings_user_home_screen_filter_fields",
            params={"media_type": "zzz"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)


class AccessTests(SettingsTestCase):
    """Account token, app tokens, grants and applications."""

    def test_account_token_is_never_scoped(self):
        self.client.force_login(self.user1)
        data = self.call_api(
            "get", "api_settings_user_token"
        ).json()
        self.assertEqual(data["token"], self.user1.token)
        response = self.call_api(
            "get",
            "api_settings_user_token",
            headers=self.scoped_headers("user:read"),
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_integration_token_lifecycle(self):
        self.client.force_login(self.user1)
        created = self.call_api(
            "post",
            "api_settings_user_integration_tokens",
            payload={"name": "Phone", "scopes": ["user:read"], "expires_in_days": 3},
            headers={},
        )
        self.assertEqual(created.status_code, HTTP.CREATED, created.content)
        body = created.json()
        self.assertTrue(body["secret"].startswith("flp_"))
        listed = self.call_api(
            "get", "api_settings_user_integration_tokens", headers={}
        ).json()
        self.assertEqual([row["name"] for row in listed["results"]], ["Phone"])
        self.assertNotIn("secret", listed["results"][0])
        self.assertTrue(listed["scope_choices"])
        deleted = self.call_api(
            "delete",
            "api_settings_user_integration_token_detail",
            args=(body["id"],),
            headers={},
        )
        self.assertEqual(deleted.status_code, HTTP.OK)
        self.assertEqual(
            self.call_api(
                "get", "api_settings_user_integration_tokens", headers={}
            ).json()["results"],
            [],
        )

    def test_integration_token_validation(self):
        self.client.force_login(self.user1)
        for payload in (
            {"name": "", "scopes": ["user:read"]},
            {"name": "x", "scopes": []},
            {"name": "x", "scopes": ["user:read"], "expires_in_days": "abc"},
            {"name": "x", "scopes": ["user:read"], "expires_in_days": 0},
        ):
            response = self.call_api(
                "post",
                "api_settings_user_integration_tokens",
                payload=payload,
                headers={},
            )
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST, payload)

    def test_cannot_revoke_another_users_token(self):
        _token, _raw = IntegrationToken.generate(
            user=self.user2, name="theirs", scopes=["user:read"]
        )
        response = self.call_api(
            "delete",
            "api_settings_user_integration_token_detail",
            args=(_token.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_scoped_token_cannot_mint_tokens(self):
        response = self.call_api(
            "post",
            "api_settings_user_integration_tokens",
            payload={"name": "x", "scopes": ["user:read"]},
            headers=self.scoped_headers("user:read", "user:write"),
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_catalog_grant_lifecycle(self):
        self.client.force_login(self.user1)
        created = self.call_api(
            "post",
            "api_settings_user_catalog_grants",
            payload={"name": "TV"},
            headers={},
        )
        self.assertEqual(created.status_code, HTTP.CREATED)
        grant = created.json()
        self.assertTrue(grant["secret"])
        listed = self.call_api(
            "get", "api_settings_user_catalog_grants", headers={}
        ).json()["results"]
        self.assertEqual(len(listed), 1)
        self.assertNotIn("secret", listed[0])
        self.call_api(
            "delete",
            "api_settings_user_catalog_grant_detail",
            args=(grant["id"],),
            headers={},
        )
        self.assertEqual(
            self.call_api(
                "get", "api_settings_user_catalog_grants", headers={}
            ).json()["results"],
            [],
        )

    def test_oauth_applications_empty(self):
        response = self.call_api(
            "get", "api_settings_user_o_auth_applications", headers=self.auth_headers
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["results"], [])

    def test_first_party_full_access_grant_is_listed_and_revocable(self):
        """The built-in Floppy app grant shows with the full-access marker."""
        from integrations.models import IntegrationToken
        from integrations.oauth_models import OAuthClient
        from integrations.oauth_scope_info import (
            FIRST_PARTY_CLIENT_ID,
            FIRST_PARTY_CLIENT_NAME,
            FULL_ACCOUNT_SCOPE,
        )

        client = OAuthClient.resolve(FIRST_PARTY_CLIENT_ID)
        token, _raw = IntegrationToken.generate(
            user=self.user1,
            name=FIRST_PARTY_CLIENT_NAME,
            scopes=["catalog:read", FULL_ACCOUNT_SCOPE],
            client_identifier=client.client_id,
        )
        listed = self.call_api(
            "get", "api_settings_user_o_auth_applications", headers=self.auth_headers
        ).json()["results"]
        self.assertEqual([row["name"] for row in listed], [FIRST_PARTY_CLIENT_NAME])
        self.assertIn(
            "Full account access", [scope["label"] for scope in listed[0]["scopes"]]
        )
        self.call_api(
            "delete",
            "api_settings_user_o_auth_application_detail",
            args=(FIRST_PARTY_CLIENT_ID,),
            headers=self.auth_headers,
        )
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)

    def test_card_preview_returns_real_card_for_draft_profile(self):
        """The preview is a card model (stand-in when no row), nothing saved."""
        response = self.call_api(
            "post",
            "api_settings_user_card_preview",
            payload={"type": "movie", "draft": {}},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        card = response.json()["card"]
        self.assertIn("title", card)
        self.assertEqual(card["shape"], "poster")


class UsersAdminTests(SettingsTestCase):
    """Superuser-only user management."""

    def test_non_superuser_is_forbidden(self):
        response = self.call_api(
            "get", "api_settings_managed_users", headers=self.auth_headers
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        response = self.call_api(
            "post",
            "api_settings_managed_users",
            payload={"username": "new-one"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_superuser_manages_accounts(self):
        self.make_superuser()
        self.client.force_login(self.user1)
        listed = self.call_api(
            "get", "api_settings_managed_users", headers={}
        )
        self.assertEqual(listed.status_code, HTTP.OK)
        self.assertEqual(listed.json()["currentUserId"], self.user1.pk)
        created = self.call_api(
            "post",
            "api_settings_managed_users",
            payload={"username": "made-by-admin", "password": ""},
            headers={},
        )
        self.assertEqual(created.status_code, HTTP.OK, created.content)
        member = created.json()["user"]
        duplicate = self.call_api(
            "post",
            "api_settings_managed_users",
            payload={"username": "made-by-admin"},
            headers={},
        )
        self.assertEqual(duplicate.status_code, HTTP.BAD_REQUEST)
        self.assertIn("detail", duplicate.json())
        deleted = self.call_api(
            "delete",
            "api_settings_managed_user_detail",
            args=(member["id"],),
            headers={},
        )
        self.assertEqual(deleted.status_code, HTTP.OK, deleted.content)


class AdvancedAboutTests(SettingsTestCase):
    """Advanced and About."""

    def test_advanced_hides_superuser_fields(self):
        data = self.call_api(
            "get", "api_settings_advanced_settings", headers=self.auth_headers
        ).json()
        self.assertEqual(data, {"isSuperuser": False})

    def test_advanced_for_superuser(self):
        self.make_superuser()
        data = self.call_api(
            "get", "api_settings_advanced_settings", headers=self.auth_headers
        ).json()
        self.assertTrue(data["isSuperuser"])
        self.assertIn("imageEnabled", data)
        self.assertIn("serverPort", data)
        self.assertNotIn("csrfToken", data["serverPort"])
        self.assertIn("logs", data["icons"])
        self.assertIn("server", data["icons"])
        self.assertEqual(data["labels"]["logs"]["title"], "Logs & Bug Reports")

    def test_image_cache_and_port_are_superuser_only(self):
        for method, name in (
            ("put", "api_settings_image_cache"),
            ("delete", "api_settings_image_cache"),
            ("put", "api_settings_server_port"),
            ("delete", "api_settings_server_port"),
        ):
            response = self.call_api(
                method, name, payload={"enabled": True}, headers=self.auth_headers
            )
            self.assertEqual(response.status_code, HTTP.FORBIDDEN, (method, name))
        response = self.call_api(
            "get", "api_settings_logs_export", headers=self.auth_headers
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_diagnostics_report_for_any_signed_in_user(self):
        response = self.call_api(
            "get", "api_settings_diagnostics_export", headers=self.auth_headers
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.assertIn("text/plain", response["Content-Type"])
        self.assertIn("floppy-diagnostics-", response["Content-Disposition"])

    def test_superuser_toggles_image_cache(self):
        from app.models import ApplicationSettings

        self.make_superuser()
        for enabled in (True, False):
            response = self.call_api(
                "put",
                "api_settings_image_cache",
                payload={"enabled": enabled},
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, HTTP.OK, response.content)
            self.assertEqual(response.json()["imageEnabled"], enabled)
            self.assertEqual(
                ApplicationSettings.objects.get(pk=1).image_caching_enabled, enabled
            )

    def test_cache_clear(self):
        response = self.call_api(
            "delete",
            "api_settings_cache_clear",
            args=("history",),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.assertIn("message", response.json())
        missing = self.call_api(
            "delete",
            "api_settings_cache_clear",
            args=("bogus",),
            headers=self.auth_headers,
        )
        self.assertEqual(missing.status_code, HTTP.NOT_FOUND)

    def test_about_payload(self):
        data = self.call_api(
            "get", "api_settings_about_settings", headers=self.auth_headers
        ).json()
        self.assertTrue(data["version"])
        self.assertTrue(data["resources"])
        self.assertTrue(data["specs"])
        self.assertEqual(data["presentation"]["overview"]["labels"]["title"], "Description")
        self.assertIn("info", data["presentation"]["overview"]["icons"])
        self.assertNotIn("csrfToken", data["presentation"])
        self.assertTrue(all(spec["url"].startswith("/") for spec in data["specs"]))


class DataTests(SettingsTestCase):
    """Export schedules, history, restore, RSS and library maintenance."""

    def test_schedule_lifecycle(self):
        created = self.call_api(
            "post",
            "api_settings_export_schedules",
            payload={"frequency": "weekly", "time": "04:30", "include_lists": True},
            headers=self.auth_headers,
        )
        self.assertEqual(created.status_code, HTTP.CREATED, created.content)
        duplicate = self.call_api(
            "post",
            "api_settings_export_schedules",
            payload={"frequency": "weekly", "time": "04:30", "include_lists": True},
            headers=self.auth_headers,
        )
        self.assertEqual(duplicate.status_code, HTTP.CONFLICT)
        listed = self.call_api(
            "get", "api_settings_export_schedules", headers=self.auth_headers
        ).json()
        self.assertEqual(len(listed["results"]), 1)
        self.assertEqual(listed["results"][0]["frequency"], "Weekly")
        removed = self.call_api(
            "delete",
            "api_settings_export_schedules",
            payload={"task_name": listed["results"][0]["task_name"]},
            headers=self.auth_headers,
        )
        self.assertEqual(removed.status_code, HTTP.OK, removed.content)
        self.assertEqual(
            self.call_api(
                "get", "api_settings_export_schedules", headers=self.auth_headers
            ).json()["results"],
            [],
        )

    def test_schedule_validation(self):
        for payload in (
            {"frequency": "daily"},
            {"frequency": "hourly", "include_lists": True},
            {"frequency": "daily", "time": "25:99", "include_lists": True},
        ):
            response = self.call_api(
                "post",
                "api_settings_export_schedules",
                payload=payload,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST, payload)

    def test_delete_unknown_schedule_reports_failure(self):
        response = self.call_api(
            "delete",
            "api_settings_export_schedules",
            payload={"task_name": "nope"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Backup schedule not found.")

    def test_history_empty(self):
        response = self.call_api(
            "get", "api_settings_export_history", headers=self.auth_headers
        )
        self.assertEqual(response.json(), {"results": []})

    def test_restore_requires_content(self):
        response = self.call_api(
            "post",
            "api_settings_restore_backup",
            payload={"content": ""},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_rss_payload(self):
        self.client.force_login(self.user1)
        data = self.call_api(
            "get", "api_settings_user_rss"
        ).json()
        self.assertIn("MEDIA_TYPE_PLACEHOLDER", data["feed_url_template"])
        self.assertIn(self.user1.token, data["feed_url_template"])
        self.assertTrue(data["media_types"])
        self.assertEqual(
            self.call_api(
                "get",
                "api_settings_user_rss",
                headers=self.scoped_headers("user:read"),
            ).status_code,
            HTTP.FORBIDDEN,
        )

    def test_library_maintenance_rejects_unknown_action_and_media_type(self):
        response = self.call_api(
            "post",
            "api_settings_library_maintenance",
            payload={"action": "explode"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        response = self.call_api(
            "post",
            "api_settings_library_maintenance",
            payload={"action": "delete_media_type", "media_type": "nonsense"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Unknown media type.")


class DataLabelsTests(SettingsTestCase):
    """Labels and previews the native Data page renders."""

    def test_schedule_media_types_carry_labels(self):
        data = self.call_api(
            "get", "api_settings_export_schedules", headers=self.auth_headers
        ).json()
        self.assertTrue(
            all({"value", "label"} <= set(row) for row in data["media_types"])
        )

    def test_backup_status_sections_and_scope(self):
        data = self.call_api(
            "get", "api_settings_export_backup_status", headers=self.auth_headers
        ).json()
        self.assertEqual(data["sections"][0]["id"], "csv")
        self.assertEqual(
            self.call_api(
                "get",
                "api_settings_export_backup_status",
                headers=self.scoped_headers("exports:read"),
            ).status_code,
            HTTP.FORBIDDEN,
        )

    def test_letterboxd_export_streams_csv(self):
        response = self.call_api(
            "get", "api_export_letterboxd", headers=self.auth_headers
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response["Content-Type"], "text/csv")

    def test_import_settings_round_trip_and_validation(self):
        url = "api_settings_import_settings"
        data = self.call_api("get", url, headers=self.auth_headers).json()
        self.assertTrue(data["frequencies"] and data["modes"])
        saved = self.call_api(
            "put",
            url,
            payload={"frequency": "daily", "time": "04:30", "mode": "overwrite"},
            headers=self.auth_headers,
        ).json()
        self.assertEqual(
            (saved["frequency"], saved["time"], saved["mode"]),
            ("daily", "04:30", "overwrite"),
        )
        for bad in ({"frequency": "hourly"}, {"time": "25:99"}, {"mode": "x"}):
            response = self.call_api(
                "put", url, payload=bad, headers=self.auth_headers
            )
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_library_maintenance_media_types_carry_labels(self):
        data = self.call_api(
            "get", "api_settings_library_maintenance", headers=self.auth_headers
        ).json()
        self.assertTrue(data["media_types"])
        self.assertTrue(all(row["label"] for row in data["media_types"]))

    @patch("app.tasks_anime_library_repair.duplicate_pair_count", return_value=2)
    def test_library_maintenance_reports_the_callers_duplicate_count(self, count):
        """The app offers the same conditional anime repair as the web Data page."""
        self.user1.anime_enabled = True
        self.user1.save(update_fields=["anime_enabled"])
        data = self.call_api(
            "get", "api_settings_library_maintenance", headers=self.auth_headers,
        ).json()
        self.assertEqual(data["duplicate_anime_count"], 2)
        count.assert_called_once_with(user_id=self.user1.id)
        count.reset_mock()
        self.user1.anime_enabled = False
        self.user1.save(update_fields=["anime_enabled"])
        data = self.call_api(
            "get", "api_settings_library_maintenance", headers=self.auth_headers,
        ).json()
        self.assertEqual(data["duplicate_anime_count"], 0)
        count.assert_not_called()

    def test_rss_preview_rejects_unknown_row(self):
        response = self.call_api(
            "get",
            "api_settings_user_rss_preview",
            params={"media_type": "movie", "row_key": "nope"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_maintenance_actions_queue_work(self):
        with patch(
            "app.tasks_tv_provider_migration.move_user_tv_library_task.delay"
        ) as delay:
            response = self.call_api(
                "post",
                "api_settings_library_maintenance",
                payload={"action": "convert_tv_library"},
                headers=self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.assertTrue(response.json()["ok"])
        delay.assert_called_once_with(self.user1.id)


class DemoAccountRevokeTests(SettingsTestCase):
    """The demo user cannot revoke the shared account's credentials."""

    def setUp(self):
        super().setUp()
        self.user1.is_demo = True
        self.user1.save(update_fields=["is_demo"])

    def test_token_revoke_is_refused(self):
        token, _raw = IntegrationToken.generate(user=self.user1, name="app", scopes=["catalog:read"])
        response = self.client.delete(f"/api/v1/user/tokens/{token.id}/", **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        token.refresh_from_db()
        self.assertIsNone(token.revoked_at)

    def test_grant_revoke_is_refused(self):
        from integrations.models import CatalogGrant

        grant, _raw = CatalogGrant.generate(self.user1, "addon")
        response = self.client.delete(f"/api/v1/user/catalog-grants/{grant.id}/", **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        grant.refresh_from_db()
        self.assertIsNone(grant.revoked_at)

    def test_oauth_application_revoke_is_refused(self):
        response = self.client.delete("/api/v1/user/oauth-applications/missing/", **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_notification_settings_are_refused(self):
        response = self.client.patch(
            "/api/v1/user/notifications/",
            {"playback_webhook_url": "https://evil.test/hook"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.user1.refresh_from_db()
        self.assertNotEqual(self.user1.playback_webhook_url, "https://evil.test/hook")


class DelegateMessageTests(SettingsTestCase):
    """_delegate judges a call only by the messages that call queued."""

    def _request(self):
        from types import SimpleNamespace

        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.db import SessionStore
        from django.test import RequestFactory

        django_request = RequestFactory().post("/api/v1/whatever/")
        django_request.user = self.user1
        django_request.session = SessionStore()
        django_request._messages = FallbackStorage(django_request)
        return SimpleNamespace(_request=django_request)

    def test_an_earlier_error_flash_does_not_fail_a_later_call(self):
        from django.contrib import messages
        from django.http import HttpResponseRedirect

        from api.fork_views_settings import _delegate

        request = self._request()
        messages.error(request._request, "Old unrelated error")

        def succeeding_view(django_request):
            messages.success(django_request, "Saved.")
            return HttpResponseRedirect("/settings/")

        response = _delegate(request, succeeding_view, post={})
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.data["messages"], ["Saved."])

    def test_the_view_error_still_fails_the_call(self):
        from django.contrib import messages
        from django.http import HttpResponseRedirect

        from api.fork_views_settings import _delegate

        request = self._request()

        def failing_view(django_request):
            messages.error(django_request, "Nope.")
            return HttpResponseRedirect("/settings/")

        response = _delegate(request, failing_view, post={})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Nope.")
