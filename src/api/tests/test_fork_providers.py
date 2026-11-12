# FORK: tests for the provider, connection and match-review endpoints.
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.utils import timezone

from integrations.models import (
    ExternalReference,
    ExternalReferenceReviewStatus,
    IntegrationToken,
    JellyfinAccount,
    SyncBinding,
)

from .base import FloppyApiTestCase


class ProvidersTests(FloppyApiTestCase):
    """The directory and detail endpoints reuse the web view models."""

    def test_directory_lists_providers_with_status(self):
        data = self.call_api("get", "api_providers", headers=self.auth_headers).json()
        slugs = {row["slug"] for row in data["items"]}
        self.assertIn("jellyfin", slugs)
        for row in data["items"]:
            self.assertIn("label", row["status"])
            self.assertNotIn("url", row)
        self.assertNotIn("csrf", data)

    def test_directory_filters_by_query(self):
        data = self.call_api(
            "get", "api_providers", headers=self.auth_headers, params={"q": "jellyfin"}
        ).json()
        self.assertEqual({row["slug"] for row in data["items"]}, {"jellyfin"})

    def test_option_form_saves_toggles_and_text(self):
        url = "api_provider_form"
        saved = self.call_api(
            "post", url, headers=self.auth_headers, args=("jellyfin", "jellyfin_events"),
            payload={"tab": "tracking", "values": {"jellyfin_mark_played_enabled": True}},
        )
        self.assertEqual(saved.status_code, HTTP.OK, saved.content)
        self.user1.refresh_from_db()
        self.assertTrue(self.user1.jellyfin_mark_played_enabled)
        self.assertFalse(self.user1.jellyfin_mark_unplayed_enabled)
        self.call_api(
            "post", url, headers=self.auth_headers, args=("plex", "plex_usernames"),
            payload={"tab": "tracking", "values": {"plex_usernames": "ann, bob, ann"}},
        )
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.plex_usernames, "ann, bob")
        unknown = self.call_api(
            "post", url, headers=self.auth_headers, args=("jellyfin", "nope"), payload={"values": {}},
        )
        self.assertEqual(unknown.status_code, HTTP.NOT_FOUND)
        _token, raw = IntegrationToken.generate(user=self.user1, name="scoped", scopes=["user:write"])
        scoped = self.call_api(
            "post", url, headers={"HTTP_X_API_KEY": raw}, args=("jellyfin", "jellyfin_events"),
            payload={"values": {}},
        )
        self.assertEqual(scoped.status_code, HTTP.FORBIDDEN)

    def test_media_server_scrobbles_toggle_saves_and_clears(self):
        url = "api_provider_form"
        for enabled in (True, False):
            saved = self.call_api(
                "post", url, headers=self.auth_headers, args=("jellyfin", "group_scrobbled_anime"),
                payload={"tab": "tracking", "values": {"enabled": enabled}},
            )
            self.assertEqual(saved.status_code, HTTP.OK, saved.content)
            self.user1.refresh_from_db()
            self.assertEqual(self.user1.group_scrobbled_anime, enabled)
        detail = self.call_api("get", "api_provider_detail", headers=self.auth_headers, args=("plex",), params={"tab": "tracking"}).json()
        self.assertIn("group_scrobbled_anime", detail["forms"])

    def test_file_import_queues_text_upload(self):
        url = "api_provider_file_import"
        bad = self.call_api("post", url, headers=self.auth_headers, args=("goodreads",), payload={"content": " "})
        self.assertEqual(bad.status_code, HTTP.BAD_REQUEST)
        unknown = self.call_api("post", url, headers=self.auth_headers, args=("jellyfin",), payload={"content": "x"})
        self.assertEqual(unknown.status_code, HTTP.NOT_FOUND)
        with patch("integrations.upload_staging.enqueue_staged_task") as queued:
            queued.return_value.id = "task-1"
            ok = self.call_api(
                "post", url, headers=self.auth_headers, args=("goodreads",),
                payload={"name": "g.csv", "content": "Title\nA\n", "mode": "new"},
            )
        self.assertEqual(ok.status_code, HTTP.ACCEPTED, ok.content)
        self.assertEqual(ok.json()["task_id"], "task-1")

    @patch("api.helpers.BODY_SLACK_BYTES", 0)
    @patch("api.fork_views_providers.MAX_FILE_IMPORT_BYTES", 6)
    @patch("rest_framework.parsers.JSONParser.parse")
    def test_file_import_body_is_bounded_before_parsing(self, parse):
        response = self.call_api(
            "post", "api_provider_file_import", headers=self.auth_headers,
            args=("goodreads",), payload={"name": "g.csv", "content": "x" * 64},
        )
        self.assertEqual(response.status_code, HTTP.REQUEST_ENTITY_TOO_LARGE)
        parse.assert_not_called()

    def test_file_import_validates_type_size_and_binary_zip(self):
        import base64
        import io
        import zipfile

        url = "api_provider_file_import"
        call = lambda slug, payload: self.call_api(  # noqa: E731
            "post", url, headers=self.auth_headers, args=(slug,), payload=payload,
        )
        wrong = call("goodreads", {"name": "g.zip", "content": "a"})
        self.assertEqual(wrong.status_code, HTTP.UNSUPPORTED_MEDIA_TYPE)
        binary = call("goodreads", {"name": "g.csv", "contentBase64": base64.b64encode(b"a\x00b").decode()})
        self.assertEqual(binary.status_code, HTTP.UNSUPPORTED_MEDIA_TYPE)
        notzip = call("trakt", {"name": "t.zip", "contentBase64": base64.b64encode(b"hello").decode()})
        self.assertEqual(notzip.status_code, HTTP.UNSUPPORTED_MEDIA_TYPE)
        garbage = call("trakt", {"name": "t.zip", "contentBase64": "***"})
        self.assertEqual(garbage.status_code, HTTP.BAD_REQUEST)
        with patch("api.fork_views_providers.MAX_FILE_IMPORT_BYTES", 8):
            big = call("goodreads", {"name": "g.csv", "content": "0123456789"})
            huge = call("trakt", {"name": "t.zip", "contentBase64": "A" * 40})
        self.assertEqual(big.status_code, HTTP.REQUEST_ENTITY_TOO_LARGE)
        self.assertEqual(huge.status_code, HTTP.REQUEST_ENTITY_TOO_LARGE)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("watched.json", "[]")
        with patch("integrations.upload_staging.enqueue_staged_task") as queued:
            queued.return_value.id = "task-2"
            ok = call("trakt", {"name": "export.zip", "contentBase64": base64.b64encode(buffer.getvalue()).decode()})
            loose = call("trakt", {"name": "watched.json", "content": "[]"})
        self.assertEqual(ok.status_code, HTTP.ACCEPTED, ok.content)
        self.assertEqual(loose.status_code, HTTP.ACCEPTED, loose.content)
        self.assertTrue(queued.call_args.kwargs["file"].endswith(".zip"))

    def test_trakt_import_tab_describes_its_export_upload(self):
        data = self.call_api(
            "get", "api_provider_detail", headers=self.auth_headers, args=("trakt",), params={"tab": "import"},
        ).json()
        self.assertEqual(data["fileImport"]["accept"], ".zip,.json,.csv")
        self.assertTrue(data["fileImport"]["binary"])

    def test_playnite_upload_queues_the_existing_importer(self):
        with patch("integrations.upload_staging.enqueue_staged_task") as queued:
            queued.return_value.id = "playnite-task"
            response = self.call_api("post", "api_provider_file_import", headers=self.auth_headers,
                                     args=("playnite",), payload={"name": "games.csv", "content": "Name\nGame\n", "mode": "new"})
        self.assertEqual(response.status_code, HTTP.ACCEPTED, response.content)
        self.assertEqual(response.json()["task_id"], "playnite-task")

    def test_metadata_actions_save_source_move_and_proxy(self):
        url = "api_provider_metadata"
        call = lambda payload, slug="tmdb": self.call_api(  # noqa: E731
            "post", url, headers=self.auth_headers, args=(slug,), payload=payload,
        )
        self.assertEqual(call({"action": "nope"}).status_code, HTTP.BAD_REQUEST)
        self.assertEqual(call({"action": "move", "key": "movie"}).status_code, HTTP.BAD_REQUEST)
        self.assertEqual(call({"action": "source", "key": "tv", "source": "nope"}).status_code, HTTP.BAD_REQUEST)
        self.assertEqual(call({"action": "source", "key": "tv", "source": "tmdb"}).status_code, HTTP.OK)
        with patch("app.tasks_tv_provider_migration.move_user_tv_library_task.delay") as moved:
            self.assertEqual(call({"action": "move", "key": "tv"}).status_code, HTTP.OK)
        moved.assert_called_once_with(self.user1.id)
        self.assertEqual(call({"action": "proxy", "proxyUrl": "http://p:1"}).status_code, HTTP.FORBIDDEN)
        self.user1.is_superuser = True
        self.user1.save(update_fields=["is_superuser"])
        self.assertEqual(call({"action": "proxy", "proxyUrl": ""}).status_code, HTTP.OK)
        self.assertEqual(call({"action": "source", "key": "tv", "source": "tmdb"}, "nope").status_code, HTTP.NOT_FOUND)

    def test_form_connected_providers_do_not_ask_for_a_browser_handoff(self):
        """Seerr and KOReader connect through their option form, as on the web."""
        for slug in ("seerr", "koreader"):
            detail = self.call_api(
                "get", "api_provider_detail", headers=self.auth_headers,
                args=(slug,), params={"tab": "connection"},
            ).json()
            self.assertEqual(detail["connection"]["mode"], "form", slug)

    def test_unknown_provider_is_404(self):
        response = self.call_api("get", "api_provider_detail", headers=self.auth_headers, args=("nope",))
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_detail_never_returns_saved_secrets(self):
        JellyfinAccount.objects.create(
            user=self.user1,
            base_url="https://jelly.example.test",
            api_key="encrypted-secret-value",
            jellyfin_user_id="u1",
        )
        response = self.call_api(
            "get",
            "api_provider_detail",
            headers=self.auth_headers,
            args=("jellyfin",),
            params={"tab": "connection"},
        )
        self.assertEqual(response.status_code, HTTP.OK)
        body = response.content.decode()
        self.assertNotIn("encrypted-secret-value", body)
        data = response.json()
        self.assertEqual(data["connection"]["mode"], "form")
        self.assertTrue(data["connection"]["canTest"])
        self.assertEqual(data["guides"], [])
        self.assertEqual(data["guideCopy"], {})
        self.assertTrue(data["guidesSessionRequired"])

    def test_detail_rejects_a_tab_the_provider_lacks(self):
        response = self.call_api(
            "get",
            "api_provider_detail",
            headers=self.auth_headers,
            args=("jellyfin",),
            params={"tab": "nope"},
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_pin_round_trip(self):
        response = self.call_api(
            "post", "api_providers_pin", headers=self.auth_headers, payload={"provider": "jellyfin", "pinned": True}
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.user1.refresh_from_db()
        self.assertIn("jellyfin", self.user1.pinned_settings_providers)

    def test_browser_handoff_provider_refuses_a_form_connect(self):
        response = self.call_api("post", "api_provider_connect", headers=self.auth_headers, args=("trakt",), payload={})
        self.assertEqual(response.status_code, HTTP.CONFLICT)
        self.assertTrue(response.json()["handoff"])

    def test_connect_reports_the_web_view_error(self):
        response = self.call_api(
            "post", "api_provider_connect", headers=self.auth_headers, args=("jellyfin",), payload={"base_url": ""}
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertIn("required", response.json()["detail"])

    def test_disconnect_removes_the_account(self):
        JellyfinAccount.objects.create(
            user=self.user1, base_url="https://j.test", api_key="x", jellyfin_user_id="u1"
        )
        response = self.call_api("post", "api_provider_disconnect", headers=self.auth_headers, args=("jellyfin",), payload={})
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertFalse(JellyfinAccount.objects.filter(user=self.user1).exists())

    def test_test_requires_a_saved_account(self):
        response = self.call_api("post", "api_provider_test", headers=self.auth_headers, args=("jellyfin",), payload={})
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        response = self.call_api("post", "api_provider_test", headers=self.auth_headers, args=("trakt",), payload={})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_credentials_instance_write_needs_a_superuser(self):
        response = self.call_api(
            "put",
            "api_provider_credentials",
            headers=self.auth_headers,
            args=("tmdb",),
            payload={"scope": "instance", "values": {"api_key": "k"}},
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_sync_now_is_limited_to_saved_account_providers(self):
        response = self.call_api("post", "api_provider_sync", headers=self.auth_headers, args=("plex",), payload={})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_sync_now_reaches_each_web_sync_route_without_an_account(self):
        """Every sync-now provider resolves its web view; with no account it says so (400), never 500/404."""
        for slug in ("stremio", "storyteller", "koreader", "pocketcasts", "gpodder", "xbox", "psn", "lastfm", "koito"):
            with self.subTest(slug=slug):
                response = self.call_api(
                    "post", "api_provider_sync", headers=self.auth_headers, args=(slug,), payload={},
                )
                self.assertEqual(response.status_code, HTTP.BAD_REQUEST, response.content)
                self.assertIn("Connect", response.json()["detail"])

    def test_detail_marks_which_providers_link_in_the_app(self):
        for slug, expected in (("trakt", True), ("storyteller", True), ("jellyfin", False)):
            data = self.call_api("get", "api_provider_detail", headers=self.auth_headers, args=(slug,)).json()
            self.assertEqual(data["connection"]["canLink"], expected, slug)

    def test_schedule_delete_ignores_other_providers_tasks(self):
        response = self.call_api(
            "delete", "api_provider_schedules", headers=self.auth_headers, args=("mal",), payload={"task_name": "x"}
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_scoped_tokens_cannot_reach_provider_routes(self):
        _token, raw = IntegrationToken.generate(user=self.user1, name="scoped", scopes=["sync:read", "metadata:read"])
        headers = {"HTTP_X_API_KEY": raw}
        for name, args in (
            ("api_providers", ()),
            ("api_provider_detail", ("jellyfin",)),
            ("api_connections", ()),
            ("api_metadata_review", ()),
        ):
            response = self.call_api("get", name, args=args, headers=headers)
            self.assertEqual(response.status_code, HTTP.FORBIDDEN, name)


class ConnectionsTests(FloppyApiTestCase):
    """Sync connections, direction, pause and device approval."""

    def test_connections_empty_state(self):
        data = self.call_api("get", "api_connections", headers=self.auth_headers).json()
        self.assertEqual(data["sync"], [])
        self.assertEqual(data["conflicts"], [])

    def test_connection_dates_use_the_web_user_format_and_keep_all_capabilities(self):
        from users.templatetags.user_tags import user_datetime_format

        binding = SyncBinding.objects.create(
            user=self.user1,
            client_kind="plex",
            origin_key="connection-format",
            last_reconciled_at=timezone.now(),
        )
        data = self.call_api("get", "api_connections", headers=self.auth_headers).json()
        self.assertEqual(len(data["sync"]), 1)
        row = data["sync"][0]
        self.assertEqual(row["last_reconciled_label"], user_datetime_format(binding.last_reconciled_at, self.user1))
        self.assertTrue(row["capabilities"])
        self.assertTrue(any(not capability["approved"] for capability in row["capabilities"]))

    def test_direction_unknown_binding_is_an_error(self):
        response = self.call_api(
            "post", "api_connection_direction", headers=self.auth_headers, args=(999,), payload={"direction": "both"}
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_pause_unknown_binding_is_an_error(self):
        response = self.call_api(
            "post", "api_connection_pause", headers=self.auth_headers, args=(999,), payload={"paused": True}
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_device_lookup_rejects_an_unknown_code(self):
        response = self.call_api("get", "api_connection_device", headers=self.auth_headers, params={"user_code": "NOPE-0000"})
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.client.force_login(self.user1)
        response = self.call_api(
            "post", "api_connection_device", headers={}, payload={"user_code": "NOPE-0000", "action": "approve"}
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class MetadataReviewTests(FloppyApiTestCase):
    """The review queue and the candidate search."""

    def test_queue_is_scoped_to_the_user(self):
        item = self.items_by_type["movie"][0]
        ExternalReference.objects.create(
            user=self.user1,
            integration="plex",
            external_namespace="plex",
            external_identity="rk-1",
            media_type="movie",
            matched_item=item,
            review_status=ExternalReferenceReviewStatus.NEEDS_REVIEW.value,
        )
        ExternalReference.objects.create(
            user=self.user2,
            integration="plex",
            external_namespace="plex",
            external_identity="rk-2",
            media_type="movie",
            matched_item=item,
            review_status=ExternalReferenceReviewStatus.NEEDS_REVIEW.value,
        )
        data = self.call_api("get", "api_metadata_review", headers=self.auth_headers).json()
        self.assertEqual([row["identity"] for row in data["needs_review"]], ["rk-1"])
        self.assertEqual(data["saved"], [])

    def test_ignore_moves_a_reference_to_saved(self):
        reference = ExternalReference.objects.create(
            user=self.user1,
            integration="plex",
            external_namespace="plex",
            external_identity="rk-1",
            media_type="movie",
            matched_item=self.items_by_type["movie"][0],
            review_status=ExternalReferenceReviewStatus.NEEDS_REVIEW.value,
        )
        response = self.call_api(
            "post",
            "api_metadata_review_reference",
            headers=self.auth_headers,
            args=(reference.pk,),
            payload={"action": "ignored"},
        )
        self.assertEqual(response.status_code, HTTP.OK)
        reference.refresh_from_db()
        self.assertEqual(reference.review_status, ExternalReferenceReviewStatus.IGNORED.value)
        bad = self.call_api(
            "post",
            "api_metadata_review_reference",
            headers=self.auth_headers,
            args=(reference.pk,),
            payload={"action": "delete"},
        )
        self.assertEqual(bad.status_code, HTTP.BAD_REQUEST)

    def test_other_users_reference_is_not_changed(self):
        reference = ExternalReference.objects.create(
            user=self.user2,
            integration="plex",
            external_namespace="plex",
            external_identity="rk-9",
            media_type="movie",
            review_status=ExternalReferenceReviewStatus.NEEDS_REVIEW.value,
        )
        response = self.call_api(
            "post",
            "api_metadata_review_reference",
            headers=self.auth_headers,
            args=(reference.pk,),
            payload={"action": "ignored"},
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    @patch("app.providers.services.search")
    def test_candidates_search_and_empty_query(self, search):
        search.return_value = {"results": [{"media_id": 5, "title": "Found", "year": 2001}, {"title": "no id"}]}
        item = self.items_by_type["movie"][0]
        data = self.call_api(
            "get",
            "api_metadata_match_candidates",
            headers=self.auth_headers,
            args=(item.pk,),
            params={"q": "found"},
        ).json()
        self.assertEqual([row["title"] for row in data["candidates"]], ["Found"])
        empty = self.call_api(
            "get", "api_metadata_match_candidates", headers=self.auth_headers, args=(item.pk,)
        ).json()
        self.assertEqual(empty["candidates"], [])

    def test_match_search_failure_names_only_the_provider(self):
        """A provider failure answers with the provider's name, not the error."""
        from app.providers import services

        item = self.items_by_type["movie"][0]
        error = services.ProviderAPIError(item.source, RuntimeError("secret-key"), "upstream detail")
        for method, name, extra in (
            ("get", "api_metadata_match_candidates", {"params": {"q": "found"}}),
            ("post", "api_metadata_match_preview", {"payload": {"q": "found"}}),
        ):
            with self.subTest(route=name), patch("app.providers.services.search", side_effect=error):
                response = self.call_api(method, name, headers=self.auth_headers, args=(item.pk,), **extra)
                self.assertEqual(response.status_code, HTTP.BAD_GATEWAY)
                self.assertEqual(
                    response.json(), {"detail": f"Could not search {error.provider_label}."}
                )

    def test_candidates_for_an_untracked_item_is_404(self):
        item = self.items_by_type["movie"][0]
        response = self.call_api(
            "get", "api_metadata_match_candidates", headers=self.auth_headers2, args=(item.pk,)
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_apply_without_a_preview_token_is_rejected(self):
        item = self.items_by_type["movie"][0]
        response = self.call_api(
            "post",
            "api_metadata_match_apply",
            headers=self.auth_headers,
            args=(item.pk,),
            payload={"destination_item_id": item.pk},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class ProviderFormActionTests(FloppyApiTestCase):
    """A form action URL with a query string still resolves."""

    def test_action_with_query_string_resolves(self):
        from users import provider_views

        real = provider_views.provider_detail

        def with_query(request, slug):
            context = real(request, slug)
            form = context["provider_forms"]["plex_usernames"]
            form["action"] = f"{form['action']}?tab=tracking"
            return context

        with patch.object(provider_views, "provider_detail", with_query):
            response = self.call_api(
                "post", "api_provider_form", headers=self.auth_headers, args=("plex", "plex_usernames"),
                payload={"tab": "tracking", "values": {"plex_usernames": "ann"}},
            )
        self.assertEqual(response.status_code, HTTP.OK, response.content)


class DemoAccountGuardTests(FloppyApiTestCase):
    """API routes that delegate to guarded session views refuse the demo user."""

    def setUp(self):
        super().setUp()
        self.user1.is_demo = True
        self.user1.save(update_fields=["is_demo"])

    def test_connect_is_refused(self):
        response = self.call_api(
            "post", "api_provider_connect", headers=self.auth_headers, args=("jellyfin",),
            payload={"base_url": "https://j.test", "username": "a", "password": "b"},
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.assertFalse(JellyfinAccount.objects.filter(user=self.user1).exists())

    def test_personal_credentials_are_refused(self):
        response = self.client.put(
            "/api/v1/providers/tmdb/credentials/",
            {"scope": "personal", "values": {"api_key": "x"}},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_guarded_option_form_is_refused(self):
        response = self.call_api(
            "post", "api_provider_form", headers=self.auth_headers, args=("plex", "plex_usernames"),
            payload={"tab": "tracking", "values": {"plex_usernames": "mallory"}},
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.user1.refresh_from_db()
        self.assertNotEqual(self.user1.plex_usernames, "mallory")
