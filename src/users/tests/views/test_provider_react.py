"""Overview truth and the scoped data boundary of the AniList React page."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from django_celery_results.models import TaskResult

from app.providers import credentials
from integrations.models import ImportRun
from users.provider_catalog import PUBLIC_ACCESS, catalog
from users.provider_ui import ACTIVITY_PAGE_SIZE, anilist_overview


@override_settings(ANILIST_ID="", ANILIST_SECRET="")
class AniListReactTests(TestCase):
    """Keep resolved credentials, actual schedules and all operational writes scoped."""

    def setUp(self):
        """Authenticate one owner and prepare a second owner with a similar id."""
        cache.clear()
        self.user = get_user_model().objects.create_user(username="anilist-owner")
        self.other = get_user_model().objects.create_user(pk=self.user.pk * 10, username="anilist-other")
        self.client.force_login(self.user)
        self.url = reverse("provider_detail", args=["anilist"])
        self.cron = CrontabSchedule.objects.create(minute="0", hour="3", day_of_week="*")

    def schedule(self, name="owned", user=None, **options):
        """Store a real owned schedule, including the encrypted-token-shaped payload."""
        return PeriodicTask.objects.create(name=name, task="Import from AniList", crontab=self.cron,
            kwargs=json.dumps({"user_id": (user or self.user).pk, "username": name,
                               "token": "schedule-secret-never-serialize", "mode": "new"}, separators=(",", ":")), **options)

    def test_saved_frequency_is_not_an_enabled_automatic_import(self):
        """Preferences describe the next import, not whether a schedule exists."""
        self.user.import_frequency = "daily"
        self.user.save(update_fields=["import_frequency"])
        self.schedule("disabled", enabled=False)
        self.schedule("other-user", user=self.other)
        self.schedule("one-time", one_off=True)
        overview = anilist_overview(self.user)
        self.assertEqual(overview["scheduleCount"], 0)
        self.assertIsNone(overview["latestImport"])

    def test_enabled_schedule_uses_exact_ownership_and_real_next_run(self):
        self.schedule()
        self.schedule("someone-else", user=self.other)
        overview = anilist_overview(self.user)
        self.assertEqual(overview["scheduleCount"], 1)
        self.assertTrue(overview["nextImport"])

    def test_partial_credentials_are_not_claimed_as_active(self):
        credentials.set_user("anilist", self.user, {"client_id": "partial"})
        self.assertEqual(anilist_overview(self.user)["connection"], "none")

    @override_settings(ANILIST_ID="environment-client", ANILIST_SECRET="environment-secret")
    def test_personal_tier_takes_precedence_over_instance_and_reports_fallback(self):
        self.assertEqual(anilist_overview(self.user)["connection"], "instance")
        credentials.set_user("anilist", self.user, {"client_id": "personal-client"})
        overview = anilist_overview(self.user)
        self.assertEqual(overview["connection"], "personal")
        self.assertTrue(overview["instanceFallback"])
        credentials.set_user("anilist", self.user, {"client_id": "personal-client", "client_secret": "personal-secret"})
        self.assertFalse(anilist_overview(self.user)["instanceFallback"])

    def test_last_import_includes_runs_older_than_the_activity_window(self):
        run = ImportRun.objects.create(user=self.user, source="anilist", status="completed")
        ImportRun.objects.filter(pk=run.pk).update(started_at=timezone.now() - timedelta(days=60))
        ImportRun.objects.create(user=self.other, source="anilist", status="failed")
        ImportRun.objects.create(user=self.user, source="trakt", status="failed")
        latest = anilist_overview(self.user)["latestImport"]
        self.assertEqual(latest["status"], "Completed")
        self.assertTrue(latest["date"])

    def test_newly_queued_task_is_the_last_active_import(self):
        ImportRun.objects.create(user=self.user, source="anilist", status="completed")
        TaskResult.objects.create(task_id="new-pending", task_name="Import from AniList", status="PENDING",
                                  task_kwargs=json.dumps({"user_id": self.user.pk}, separators=(",", ":")))
        self.assertEqual(anilist_overview(self.user)["latestImport"]["status"], "Pending")

    def test_stale_pending_task_does_not_replace_the_last_real_import(self):
        run = ImportRun.objects.create(user=self.user, source="anilist", status="completed")
        ImportRun.objects.filter(pk=run.pk).update(started_at=timezone.now() - timedelta(days=2))
        task = TaskResult.objects.create(task_id="lost-pending", task_name="Import from AniList", status="PENDING",
                                         task_kwargs=json.dumps({"user_id": self.user.pk}))
        TaskResult.objects.filter(pk=task.pk).update(date_created=timezone.now() - timedelta(hours=1))
        self.assertEqual(anilist_overview(self.user)["latestImport"]["status"], "Completed")

    def test_all_anilist_tabs_use_one_full_page_island(self):
        for tab in ("overview", "connection", "import", "activity"):
            with self.subTest(tab=tab):
                response = self.client.get(self.url, {"tab": tab})
                self.assertContains(response, "data-provider-root")
                self.assertEqual(response.context["provider_page"]["tab"], tab)
                self.assertEqual(len(response.context["provider_page"]["tabs"]), 4)

    @override_settings(ANILIST_ID="private-environment-client", ANILIST_SECRET="private-environment-secret")
    def test_connection_model_contains_statuses_but_no_saved_keys_or_previews(self):
        credentials.set_user("anilist", self.user, {"client_id": "private-personal-client", "client_secret": "private-personal-secret"})
        page = self.client.get(self.url, {"tab": "connection"}).context["provider_page"]
        serialized = json.dumps(page)
        for secret in ("private-environment-client", "private-environment-secret", "private-personal-client", "private-personal-secret"):
            self.assertNotIn(secret, serialized)
        self.assertEqual([field["name"] for field in page["credentials"]["personalFields"]], ["client_id", "client_secret"])
        self.assertFalse(page["credentials"]["editable"])

    def test_activity_json_excludes_other_users_sources_and_stored_task_tokens(self):
        self.schedule()
        self.schedule("unowned", user=self.other)
        for task_id, user, source in (("owned-result", self.user, "AniList"), ("foreign-result", self.other, "AniList"), ("other-source", self.user, "Trakt")):
            TaskResult.objects.create(task_id=task_id, task_name=f"Import from {source}", status="SUCCESS",
                task_kwargs=json.dumps({"user_id": user.pk, "token": "result-secret-never-serialize"}, separators=(",", ":")),
                result='["Imported 1 anime.", null]')
        ImportRun.objects.create(user=self.user, source="anilist", status="completed", prepared_state={"secret": "prepared-secret-never-serialize"})
        response = self.client.get(self.url, {"tab": "activity", "format": "json"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()["results"]], ["owned-result"])
        self.assertEqual(len(response.json()["schedules"]), 1)
        for secret in ("schedule-secret-never-serialize", "result-secret-never-serialize", "prepared-secret-never-serialize"):
            self.assertNotIn(secret, response.content.decode())
        self.assertIn("no-store", response["Cache-Control"])

    def test_activity_history_is_paged_without_losing_older_results(self):
        for index in range(ACTIVITY_PAGE_SIZE + 3):
            TaskResult.objects.create(task_id=f"history-{index}", task_name="Import from AniList", status="SUCCESS",
                task_kwargs=json.dumps({"user_id": self.user.pk}), result='["No media was imported.", null]')
        first = self.client.get(self.url, {"tab": "activity", "format": "json"}).json()
        second = self.client.get(self.url, {"tab": "activity", "format": "json", "page": 2}).json()
        self.assertTrue(first["hasMore"])
        self.assertEqual(len(first["results"]), ACTIVITY_PAGE_SIZE)
        self.assertEqual(len(second["results"]), 3)
        self.assertFalse(second["hasMore"])
        self.assertEqual(len({row["id"] for row in first["results"] + second["results"]}), ACTIVITY_PAGE_SIZE + 3)

    def test_json_only_supports_activity_and_authenticated_owners(self):
        self.assertEqual(self.client.get(self.url, {"tab": "overview", "format": "json"}).status_code, 404)
        self.assertEqual(self.client.get(self.url, {"tab": "activity", "format": "json", "page": "bad"}).status_code, 404)
        self.client.logout()
        response = self.client.get(self.url, {"tab": "activity", "format": "json"})
        self.assertEqual(response.status_code, 302)

    @patch("integrations.views.tasks.import_anilist.delay")
    def test_public_import_returns_to_its_provider_tab(self, import_task):
        response = self.client.post(reverse("import_anilist_public"), {
            "user": "public-person", "frequency": "once", "time": "03:00", "mode": "new",
            "next": self.url + "?tab=import",
        })
        self.assertRedirects(response, self.url + "?tab=import")
        import_task.assert_called_once()

    def test_schedule_removal_keeps_ownership_and_safe_return_destination(self):
        owned = self.schedule()
        other = self.schedule("other", user=self.other)
        response = self.client.post(reverse("delete_import_schedule"), {"task_name": other.name, "next": self.url + "?tab=activity"})
        self.assertRedirects(response, self.url + "?tab=activity")
        self.assertTrue(PeriodicTask.objects.filter(pk=other.pk).exists())
        response = self.client.post(reverse("delete_import_schedule"), {"task_name": owned.name, "next": "https://untrusted.invalid/"})
        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertFalse(PeriodicTask.objects.filter(pk=owned.pk).exists())

    def test_embedded_owner_text_cannot_expose_or_delete_another_users_task(self):
        """SQL text matching is only a prefilter, not authorization."""
        payload = json.dumps({"user_id": self.other.pk, "username": f"literal 'user_id': {self.user.pk},"})
        task = self.schedule("foreign-poison")
        task.kwargs = payload
        task.save(update_fields=["kwargs"])
        TaskResult.objects.create(task_id="foreign-poison", task_name="Import from AniList", status="SUCCESS",
                                  task_kwargs=payload, result='"private result"')
        overview = anilist_overview(self.user)
        self.assertEqual(overview["scheduleCount"], 0)
        self.assertIsNone(overview["latestImport"])
        activity = self.client.get(self.url, {"tab": "activity", "format": "json"}).json()
        self.assertEqual(activity["results"], [])
        self.assertEqual(activity["schedules"], [])
        self.client.post(reverse("delete_import_schedule"), {"task_name": task.name})
        self.assertTrue(PeriodicTask.objects.filter(pk=task.pk).exists())


class SharedProviderPageTests(TestCase):
    """All providers share shell/card ownership without inventing unsupported tabs."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="shared-provider-owner")
        self.client.force_login(self.user)
        self.addCleanup(cache.clear)

    def test_every_provider_overview_uses_the_same_react_renderer_and_safe_cards(self):
        for provider in catalog():
            with self.subTest(slug=provider["slug"]):
                response = self.client.get(reverse("provider_detail", args=[provider["slug"]]))
                self.assertEqual(response.status_code, 200)
                page = response.context["provider_page"]
                self.assertEqual(page["contentOwner"], "react")
                self.assertContains(response, "data-provider-root")
                self.assertEqual(page["provider"]["label"], provider["label"])
                card_keys = [card["key"] for card in page["overviewCards"]]
                self.assertEqual(card_keys, [tab for tab in provider["tabs"] if tab in card_keys])
                for card in page["overviewCards"]:
                    self.assertIn(card["key"], provider["tabs"])
                    self.assertEqual(card["url"], reverse("provider_detail", args=[provider["slug"]]) + "?tab=" + card["key"])
                self.assertNotContains(response, "Available capabilities")

    @override_settings(BGG_API_TOKEN="bundled-boardgame-Z123", SHARED_DEFAULT_CREDENTIALS={"BGG_API_TOKEN": "bundled-boardgame-Z123"})
    def test_metadata_only_provider_uses_connection_and_metadata_cards(self):
        response = self.client.get(reverse("provider_detail", args=["bgg"]))
        page = response.context["provider_page"]
        self.assertEqual([card["key"] for card in page["overviewCards"]], ["connection", "metadata"])
        self.assertEqual(page["overviewCards"][0]["subtitle"], "Bundled credentials active")
        self.assertEqual(page["overviewCards"][0]["badge"], "Active")
        self.assertNotIn("bundled-boardgame-Z123", json.dumps(page))
        self.assertNotIn("Z123", json.dumps(page))

    def test_file_only_providers_explain_unavailable_automatic_imports(self):
        from users.provider_catalog import FILE_ONLY_IMPORTS

        for slug in FILE_ONLY_IMPORTS:
            with self.subTest(slug=slug):
                response = self.client.get(reverse("provider_detail", args=[slug]))
                card = next(card for card in response.context["provider_page"]["overviewCards"] if card["key"] == "import")
                self.assertEqual(card["badge"], "File only")
                self.assertEqual(card["subtitle"], "Automatic imports are unavailable for file uploads")
                preferences = self.client.get(reverse("provider_detail", args=[slug]), {"tab": "import"}).context["import_preferences"]
                self.assertTrue(preferences["fixedFrequency"])
                self.assertIn("uploaded", preferences["fixedFrequencyHelp"])

    def test_hardcover_account_sync_remains_schedulable(self):
        url = reverse("provider_detail", args=["hardcover"])
        card = next(card for card in self.client.get(url).context["provider_page"]["overviewCards"] if card["key"] == "import")
        self.assertEqual(card["badge"], "Inactive")
        preferences = self.client.get(url, {"tab": "import"}).context["import_preferences"]
        self.assertFalse(preferences["fixedFrequency"])

    def test_one_time_token_import_is_not_described_as_file_upload(self):
        url = reverse("provider_detail", args=["mangabaka"])
        card = next(card for card in self.client.get(url).context["provider_page"]["overviewCards"] if card["key"] == "import")
        self.assertEqual(card["badge"], "One-time")
        preferences = self.client.get(url, {"tab": "import"}).context["import_preferences"]
        self.assertTrue(preferences["fixedFrequency"])
        self.assertIn("personal token", preferences["fixedFrequencyHelp"])
        self.assertNotIn("uploaded", preferences["fixedFrequencyHelp"])

    def test_retained_tab_has_shared_react_header_and_separate_server_body(self):
        response = self.client.get(reverse("provider_detail", args=["hardcover"]), {"tab": "connection"})
        page = response.context["provider_page"]
        self.assertEqual(page["contentOwner"], "server")
        self.assertContains(response, "data-provider-root")
        self.assertTemplateUsed(response, "users/providers/content_legacy.html")
        self.assertContains(response, reverse("save_personal_credential", args=["hardcover"]))
        self.assertNotIn("credentials", page)

    def test_every_metadata_tab_uses_the_shared_inline_react_component(self):
        for provider in catalog():
            if not provider.get("metadata"):
                continue
            with self.subTest(slug=provider["slug"]):
                response = self.client.get(reverse("provider_detail", args=[provider["slug"]]), {"tab": "metadata"})
                self.assertEqual(response.status_code, 200)
                page = response.context["provider_page"]
                self.assertEqual(page["contentOwner"], "react")
                self.assertIn("metadata", page)
                self.assertNotContains(response, "activeModal")

    @override_settings(BGG_API_TOKEN="shared-bgg-token", SHARED_DEFAULT_CREDENTIALS={"BGG_API_TOKEN": "shared-bgg-token"})
    def test_fixed_primary_metadata_is_active_and_read_only(self):
        url = reverse("provider_detail", args=["bgg"])
        page = self.client.get(url).context["provider_page"]
        card = next(card for card in page["overviewCards"] if card["key"] == "metadata")
        self.assertEqual(card["badge"], "Active")
        self.assertEqual(card["subtitle"], "Primary metadata source active")
        metadata = self.client.get(url, {"tab": "metadata"}).context["provider_page"]["metadata"]
        self.assertTrue(metadata["status"]["active"])
        self.assertFalse(metadata["editable"])
        self.assertFalse(metadata["sources"][0]["editable"])

    @override_settings(HARDCOVER_API="")
    def test_personal_only_source_can_be_selected_and_seen_on_other_provider_pages(self):
        credentials.set_user("hardcover", self.user, {"api_key": "personal-metadata-secret"})
        url = reverse("provider_detail", args=["hardcover"])
        response = self.client.post(reverse("set_media_type_provider", args=["book"]),
                                    {"source": "hardcover", "next": url + "?tab=metadata"})
        self.assertRedirects(response, url + "?tab=metadata")
        self.user.refresh_from_db()
        self.assertEqual(self.user.book_metadata_source_default, "hardcover")
        page = self.client.get(reverse("provider_detail", args=["openlibrary"]), {"tab": "metadata"}).context["provider_page"]
        self.assertEqual(page["metadata"]["sources"][0]["current"], "hardcover")
        self.assertNotIn("personal-metadata-secret", json.dumps(page))

    def test_proxy_settings_expose_only_configuration_status(self):
        self.user.tmdb_proxy_url = "private-proxy-value"
        self.user.is_superuser = True
        self.user.save(update_fields=["tmdb_proxy_url", "is_superuser"])
        page = self.client.get(reverse("provider_detail", args=["tmdb"]), {"tab": "metadata"}).context["provider_page"]
        self.assertTrue(page["metadata"]["proxy"]["configured"])
        self.assertNotIn("private-proxy-value", json.dumps(page))

    @override_settings(IGDB_ID="client", IGDB_SECRET="secret", STEAMGRIDDB_API_KEY="", STEAM_API_KEY="")
    def test_game_contributions_distinguish_primary_metadata_and_public_artwork(self):
        def metadata(slug):
            return self.client.get(reverse("provider_detail", args=[slug]), {"tab": "metadata"}).context["provider_page"]["metadata"]

        igdb = {row["key"]: row for row in metadata("igdb")["contributions"]}
        self.assertEqual(igdb["search"]["status"], "Active")
        self.assertEqual(igdb["details"]["status"], "Active")
        self.assertEqual(igdb["logos"]["status"], "Not provided")
        self.assertEqual(igdb["backgrounds"]["status"], "Active")
        steam = metadata("steam")
        self.assertTrue(steam["status"]["active"])
        self.assertEqual(steam["status"]["summary"], "Supplemental metadata active")
        self.assertEqual({row["key"] for row in steam["contributions"] if row["status"] == "Not provided"},
                         {"search", "details", "covers"})
        self.assertEqual(metadata("libretro")["status"]["summary"], "Supplemental metadata active")
        self.assertEqual({row["key"] for row in steam["contributions"] if row["status"] == "Active"}, {"logos", "backgrounds"})
        grid = metadata("steamgriddb")
        self.assertFalse(grid["status"]["active"])
        self.assertEqual({row["status"] for row in grid["contributions"]}, {"Needs setup", "Not provided"})
        credentials.set_user("steamgriddb", self.user, {"api_key": "personal-grid-key"})
        grid = metadata("steamgriddb")
        self.assertEqual({row["key"] for row in grid["contributions"] if row["status"] == "Active"}, {"logos", "backgrounds", "gallery"})
        self.assertNotIn("personal-grid-key", json.dumps(grid))

    def test_supplemental_metadata_includes_its_media_domain(self):
        for slug in ("steam", "steamgriddb", "libretro"):
            with self.subTest(slug=slug):
                response = self.client.get(reverse("provider_detail", args=[slug]), {"tab": "metadata"})
                sources = response.context["provider_page"]["metadata"]["sources"]
                self.assertEqual([source["key"] for source in sources], ["game"])
                self.assertEqual(sources[0]["current"], "igdb")
                self.assertFalse(sources[0]["editable"])

    def test_imported_metadata_shows_real_library_defaults_and_scope(self):
        url = reverse("provider_detail", args=["audiobookshelf"])
        metadata = self.client.get(url, {"tab": "metadata"}).context["provider_page"]["metadata"]
        self.assertTrue(metadata["imported"])
        self.assertEqual(metadata["status"]["summary"], "Metadata for imported items")
        sources = {source["key"]: source for source in metadata["sources"]}
        self.assertEqual(set(sources), {"book", "podcast"})
        self.assertEqual(sources["podcast"]["current"], "pocketcasts")
        self.assertFalse(sources["podcast"]["editable"])
        self.assertTrue(sources["book"]["editable"])
        self.assertTrue(any(choice["value"] == "audiobookshelf" and choice["imported"] for choice in sources["podcast"]["choices"]))
        search = next(item for item in metadata["contributions"] if item["key"] == "search")
        self.assertIn(sources["podcast"]["currentLabel"], search["status"])
        self.assertIn(sources["book"]["currentLabel"], search["status"])
        self.assertNotEqual(search["status"], "Not selected")

    def test_unselected_provider_features_name_effective_source(self):
        credentials.set_user("hardcover", self.user, {"api_key": "personal-test-key"})
        self.user.book_metadata_source_default = "hardcover"
        self.user.save(update_fields=["book_metadata_source_default"])
        page = self.client.get(reverse("provider_detail", args=["openlibrary"]), {"tab": "metadata"}).context["provider_page"]
        metadata = page["metadata"]
        self.assertEqual(metadata["status"]["state"], "not_selected")
        search = next(item for item in metadata["contributions"] if item["key"] == "search")
        self.assertEqual(search["status"], "From Hardcover")

    @override_settings(STEAM_API_KEY="", SHARED_DEFAULT_CREDENTIALS={})
    def test_public_connection_is_distinct_from_instance_and_personal_keys(self):
        url = reverse("provider_detail", args=["steam"])
        def connection_card():
            page = self.client.get(url).context["provider_page"]
            return next(card for card in page["overviewCards"] if card["key"] == "connection")

        self.assertEqual(connection_card()["subtitle"], "Public API active")
        self.assertEqual(connection_card()["badge"], "Active")
        response = self.client.get(url, {"tab": "connection"})
        self.assertContains(response, "Public API")
        self.assertNotContains(response, "Game artwork uses a public API and does not require an API key.")
        credentials.set_instance("steam", {"api_key": "instance-private-key"})
        self.assertEqual(connection_card()["subtitle"], "Instance credentials active")
        credentials.set_user("steam", self.user, {"api_key": "personal-private-key"})
        self.assertEqual(connection_card()["subtitle"], "Personal credentials active")
        page = self.client.get(url, {"tab": "connection"}).context["provider_page"]
        self.assertNotIn("private-key", json.dumps(page))

    @override_settings(BGG_API_TOKEN="", SHARED_DEFAULT_CREDENTIALS={})
    def test_another_provider_can_declare_public_access_without_ui_changes(self):
        public = {"description": "Public board game data needs no key.", "capabilities": ("metadata",)}
        with patch.dict(PUBLIC_ACCESS, {"bgg": public}):
            url = reverse("provider_detail", args=["bgg"])
            page = self.client.get(url).context["provider_page"]
            cards = {card["key"]: card for card in page["overviewCards"]}
            self.assertEqual(cards["connection"]["subtitle"], "Public API active")
            self.assertEqual(cards["metadata"]["badge"], "Active")
            self.assertContains(self.client.get(url, {"tab": "connection"}), "Public API")

    @override_settings(SCREENSCRAPER_DEV_ID="", SCREENSCRAPER_DEV_PASSWORD="", SCREENSCRAPER_SSID="member", SCREENSCRAPER_SSPASSWORD="password")
    def test_screenscraper_member_credentials_do_not_replace_instance_access(self):
        url = reverse("provider_detail", args=["screenscraper"])
        metadata = self.client.get(url, {"tab": "metadata"}).context["provider_page"]["metadata"]
        self.assertFalse(metadata["status"]["active"])
        self.assertEqual(metadata["status"]["summary"], "Instance artwork access is not configured")
        with self.settings(SCREENSCRAPER_DEV_ID="developer-id", SCREENSCRAPER_DEV_PASSWORD="developer-password", SCREENSCRAPER_SSID="", SCREENSCRAPER_SSPASSWORD=""):
            metadata = self.client.get(url, {"tab": "metadata"}).context["provider_page"]["metadata"]
            self.assertTrue(metadata["status"]["active"])
            self.assertNotIn("developer-password", json.dumps(metadata))

    def test_generic_import_overview_ignores_foreign_and_one_time_schedules(self):
        other = get_user_model().objects.create_user(username="other-shared-provider")
        cron = CrontabSchedule.objects.create(minute="0", hour="4")
        for name, owner, one_off in (("owned", self.user, False), ("foreign", other, False), ("once", self.user, True)):
            PeriodicTask.objects.create(name=name, task="Import from Kitsu", crontab=cron,
                                        kwargs=json.dumps({"user_id": owner.pk, "username": name, "mode": "new"}), one_off=one_off)
        ImportRun.objects.create(user=other, source="kitsu", status="failed")
        ImportRun.objects.create(user=self.user, source="kitsu", status="completed")
        page = self.client.get(reverse("provider_detail", args=["kitsu"])).context["provider_page"]
        cards = {card["key"]: card for card in page["overviewCards"]}
        self.assertEqual(cards["import"]["subtitle"], "1 enabled schedule")
        self.assertEqual(cards["activity"]["subtitle"], "Completed")

    @patch("users.models.AsyncResult")
    def test_overview_reads_persisted_task_state_without_refreshing_or_writing(self, async_result):
        task = TaskResult.objects.create(task_id="shared-pending", task_name="Import from Kitsu", status="PENDING",
                                         task_kwargs=json.dumps({"user_id": self.user.pk}))
        page = self.client.get(reverse("provider_detail", args=["kitsu"])).context["provider_page"]
        cards = {card["key"]: card for card in page["overviewCards"]}
        self.assertEqual(cards["activity"]["subtitle"], "Pending")
        async_result.assert_not_called()
        task.refresh_from_db()
        self.assertEqual(task.status, "PENDING")
