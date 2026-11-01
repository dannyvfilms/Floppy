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
        self.assertTrue(all(field["personalStored"] for field in page["credentials"]["fields"]))
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
