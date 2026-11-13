from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.providers import credentials
from app.tasks import refresh_discover_rows, refresh_discover_tab_cache
from app.tasks_discover import (
    refresh_discover_profile_for_user,
    refresh_discover_profiles,
    warm_discover_api_cache,
)


class DiscoverTaskTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="discover-task-user",
            password="secret123",
        )

    @patch("app.discover.profile.get_or_compute_taste_profile")
    def test_profile_refresh_respects_freshness(self, compute):
        refresh_discover_profile_for_user(self.user.id, ["all"])
        compute.assert_called_once_with(self.user, "all", force=False)

    @patch("app.tasks_discover.cache_safety.acquire_lock")
    @patch("app.discover.profile.get_or_compute_taste_profile")
    def test_explicit_profile_refresh_can_force_recomputation(self, compute, acquire):
        refresh_discover_profile_for_user(self.user.id, ["all"], force=True)
        compute.assert_called_once_with(self.user, "all", force=True)
        acquire.assert_not_called()

    @patch("app.tasks_discover.cache_safety.release_lock")
    @patch("app.tasks_discover.cache_safety.acquire_lock", return_value=False)
    @patch("app.discover.profile.get_or_compute_taste_profile")
    def test_overlapping_scheduled_profile_refresh_is_skipped(
        self,
        compute,
        acquire,
        release,
    ):
        result = refresh_discover_profile_for_user(self.user.id, ["all"])
        self.assertEqual(result, {"profiles_refreshed": 0, "profiles_skipped": 1})
        acquire.assert_called_once()
        compute.assert_not_called()
        release.assert_not_called()

    @patch("app.tasks_discover.cache_safety.release_lock")
    @patch("app.tasks_discover.cache_safety.acquire_lock", return_value=True)
    @patch(
        "app.discover.profile.get_or_compute_taste_profile",
        side_effect=RuntimeError("boom"),
    )
    def test_failed_scheduled_profile_refresh_releases_lock(
        self,
        compute,
        acquire,
        release,
    ):
        with self.assertRaisesRegex(RuntimeError, "boom"):
            refresh_discover_profile_for_user(self.user.id, ["all"])
        compute.assert_called_once()
        acquire.assert_called_once()
        release.assert_called_once()

    @patch("app.tasks_discover.refresh_discover_profile_for_user.apply_async")
    def test_profile_fanout_preserves_force(self, dispatch):
        for force in (False, True):
            with self.subTest(force=force):
                refresh_discover_profiles([self.user.id], ["all"], force=force)
                self.assertEqual(dispatch.call_args.kwargs["kwargs"]["force"], force)

    @patch("app.discover.profile.get_or_compute_taste_profile")
    def test_deleted_profile_user_is_skipped(self, compute):
        user_id = self.user.id
        self.user.delete()
        self.assertEqual(
            refresh_discover_profile_for_user(user_id, ["all"]),
            {"profiles_refreshed": 0, "reason": "missing_user"},
        )
        compute.assert_not_called()

    def test_background_work_skips_users_with_discover_off(self):
        """Discover off means no profiles, rows, or tab caches are rebuilt."""
        self.user.show_discover = False
        self.user.save(update_fields=["show_discover"])

        with (
            patch("app.discover.profile.get_or_compute_taste_profile") as compute,
            patch("app.discover.service.refresh_rows_for_user") as refresh_rows,
            patch("app.discover.tab_cache.refresh_tab_cache") as refresh_tab,
            patch(
                "app.tasks_discover.refresh_discover_profile_for_user.apply_async",
            ) as fanout,
        ):
            self.assertEqual(
                refresh_discover_profile_for_user(self.user.id, ["all"])["reason"],
                "discover_disabled",
            )
            self.assertEqual(
                refresh_discover_rows(self.user.id, "all", ["top_picks"])["reason"],
                "discover_disabled",
            )
            self.assertEqual(
                refresh_discover_tab_cache(self.user.id, "all")["reason"],
                "discover_disabled",
            )
            refresh_discover_profiles([self.user.id], ["all"])

        compute.assert_not_called()
        refresh_rows.assert_not_called()
        refresh_tab.assert_not_called()
        fanout.assert_not_called()

    @patch("app.discover.tab_cache._should_enqueue_refresh_tasks", return_value=False)
    def test_skipped_tab_refresh_frees_its_reservation(self, _enqueue):
        """Turning Discover back on must be able to queue a real rebuild."""
        from app.discover import tab_cache

        self.assertTrue(tab_cache.schedule_tab_refresh(self.user.id, "all"))
        self.assertFalse(tab_cache.schedule_tab_refresh(self.user.id, "all"))

        self.user.show_discover = False
        self.user.save(update_fields=["show_discover"])
        refresh_discover_tab_cache(self.user.id, "all")

        self.assertTrue(tab_cache.schedule_tab_refresh(self.user.id, "all"))

    def test_api_cache_warm_skipped_when_nobody_uses_discover(self):
        """The shared provider warm-up has nothing to serve if Discover is off."""
        self.user.show_discover = False
        self.user.save(update_fields=["show_discover"])

        result = warm_discover_api_cache()

        self.assertEqual(result["reason"], "discover_disabled")
        self.assertEqual(result["warmed"], 0)

    @patch("app.discover.service.refresh_rows_for_user")
    @patch("app.discover.tab_cache.refresh_tab_cache")
    def test_refresh_discover_rows_skips_disabled_media_type(
        self,
        mock_refresh_tab_cache,
        mock_refresh_rows_for_user,
    ):
        self.user.comic_enabled = False
        self.user.save(update_fields=["comic_enabled"])

        result = refresh_discover_rows(self.user.id, "comic", ["coming_soon"])

        self.assertEqual(
            result,
            {
                "refreshed": 0,
                "reason": "disabled_media_type",
                "user_id": self.user.id,
            },
        )
        mock_refresh_rows_for_user.assert_not_called()
        mock_refresh_tab_cache.assert_not_called()

    @patch("app.discover.tab_cache.refresh_tab_cache")
    def test_refresh_discover_tab_cache_skips_disabled_media_type(
        self,
        mock_refresh_tab_cache,
    ):
        self.user.comic_enabled = False
        self.user.save(update_fields=["comic_enabled"])

        result = refresh_discover_tab_cache(self.user.id, "comic")

        self.assertEqual(
            result,
            {
                "refreshed": False,
                "reason": "disabled_media_type",
                "user_id": self.user.id,
            },
        )
        mock_refresh_tab_cache.assert_not_called()

    @patch("app.discover.tab_cache.refresh_tab_cache")
    @patch("app.discover.service.refresh_rows_for_user")
    def test_refresh_discover_rows_uses_personal_credentials(
        self,
        mock_refresh_rows_for_user,
        _mock_refresh_tab_cache,
    ):
        """A personal key must apply to background row rebuilds for that member."""
        observed = {}

        def rebuild(user, media_type, row_keys, *, show_more=False):
            observed["user"] = credentials.active_user()
            return 0

        mock_refresh_rows_for_user.side_effect = rebuild

        refresh_discover_rows(self.user.id, "movie", ["top_picks"])

        self.assertEqual(observed["user"], self.user)
        self.assertIsNone(credentials.active_user())

    @patch("app.discover.tab_cache.refresh_tab_cache")
    def test_refresh_discover_tab_cache_uses_personal_credentials(
        self,
        mock_refresh_tab_cache,
    ):
        observed = {}

        def rebuild(user, media_type, **kwargs):
            observed["user"] = credentials.active_user()
            return []

        mock_refresh_tab_cache.side_effect = rebuild

        refresh_discover_tab_cache(self.user.id, "movie")

        self.assertEqual(observed["user"], self.user)
        self.assertIsNone(credentials.active_user())
