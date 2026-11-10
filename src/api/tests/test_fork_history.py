# FORK: History endpoints the native app uses beyond GET /api/v1/history/.
from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.utils import timezone

from app.models import Movie, Status
from users.models import SavedView

from .base import FloppyApiTestCase


class HistoryGenresTests(FloppyApiTestCase):
    """GET /history/genres/."""

    def test_returns_genre_lists(self):
        """Both lists are present and sorted."""
        response = self.call_api("get", "api_history_genres", headers=self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertIsInstance(payload["genres"], list)
        self.assertIsInstance(payload["implied_genres"], list)

    def test_requires_authentication(self):
        """Anonymous callers are rejected."""
        response = self.call_api("get", "api_history_genres", headers=self.invalid_auth_headers)
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)


class HistoryEntryTests(FloppyApiTestCase):
    """PATCH/DELETE /history/entries/<type>/<instance_id>/."""

    def setUp(self):
        """Give the first movie a dated play."""
        super().setUp()
        self.movie = self.movie_medias[0]
        self.movie.status = Status.COMPLETED.value
        self.movie.end_date = timezone.now() - timedelta(days=2)
        self.movie.save()

    def test_patch_updates_date_score_and_status(self):
        """The edit dialog's fields round trip."""
        response = self.call_api(
            "patch",
            "api_history_entry",
            args=("movie", self.movie.id),
            payload={"date": "2024-03-04T21:30", "score": 8, "status": Status.PAUSED.value},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.status, Status.PAUSED.value)
        self.assertEqual(self.movie.score, 8)
        self.assertEqual(timezone.localtime(self.movie.end_date).date().isoformat(), "2024-03-04")

    def test_patch_rejects_invalid_score(self):
        """Out of range scores return 400."""
        response = self.call_api(
            "patch",
            "api_history_entry",
            args=("movie", self.movie.id),
            payload={"score": 99},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_patch_other_users_entry_is_404(self):
        """Another account cannot edit the entry."""
        response = self.call_api(
            "patch",
            "api_history_entry",
            args=("movie", self.movie.id),
            payload={"score": 5},
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_delete_removes_the_play(self):
        """Deleting a movie entry removes the tracked play."""
        response = self.call_api(
            "delete",
            "api_history_entry",
            args=("movie", self.movie.id),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertFalse(Movie.objects.filter(id=self.movie.id).exists())

    def test_delete_without_history_record_runs_the_same_cleanup(self):
        """The fallback syncs the season and clears History/Statistics caches."""
        from app.models import Season

        episode = self.episode_medias[0]
        self.assertFalse(episode.history.exists())
        with (
            patch.object(Season, "_sync_status_after_episode_change") as synced,
            patch("app.fork_services_history.history_cache.invalidate_history_days") as history,
            patch("app.fork_services_history.statistics_cache.invalidate_statistics_days") as stats,
        ):
            response = self.call_api(
                "delete",
                "api_history_entry",
                args=("episode", episode.id),
                headers=self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT, response.content)
        synced.assert_called_once()
        history.assert_called_once()
        stats.assert_called_once()

    def test_delete_other_users_entry_is_404(self):
        """Another account cannot delete the entry."""
        response = self.call_api(
            "delete",
            "api_history_entry",
            args=("movie", self.movie.id),
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertTrue(Movie.objects.filter(id=self.movie.id).exists())

    def test_delete_refused_for_types_that_keep_their_row(self):
        """Reading and anime entries are not deleted through the feed."""
        response = self.call_api(
            "delete",
            "api_history_entry",
            args=("anime", self.anime_medias[0].id),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class HistoryFeedExtrasTests(FloppyApiTestCase):
    """Sessions, day overflow, release days and saved views."""

    def test_sessions_returns_sessions_and_stats(self):
        """The activity dialog payload has both lists."""
        response = self.call_api(
            "get",
            "api_history_sessions",
            params={"media_type": "movie", "media_id": "701", "source": "tmdb"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertIn("sessions", payload)
        self.assertIn("stats", payload)

    def test_day_rejects_bad_key(self):
        """A malformed day key returns 400."""
        response = self.call_api("get", "api_history_day", args=("not-a-day",), headers=self.auth_headers)
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_day_rejects_negative_offset(self):
        """A negative offset returns 400."""
        response = self.call_api(
            "get",
            "api_history_day",
            args=("20240304",),
            params={"entry_offset": "-1"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_day_returns_entries_for_a_played_day(self):
        """A day with a play returns its bounded page."""
        movie = self.movie_medias[0]
        movie.status = Status.COMPLETED.value
        movie.end_date = timezone.now()
        movie.save()
        key = timezone.localdate().strftime("%Y%m%d")
        response = self.call_api("get", "api_history_day", args=(key,), headers=self.auth_headers)
        self.assertIn(response.status_code, (HTTP.OK, HTTP.NOT_FOUND))
        if response.status_code == HTTP.OK:
            self.assertIn("entries", response.json()["day"])

    def test_release_days_are_json(self):
        """Release-date days serialise (items are plain dicts)."""
        response = self.call_api("get", "api_history_release", headers=self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        for day in response.json()["results"]:
            for entry in day["entries"]:
                self.assertIsInstance(entry["item"], dict)

    def test_release_days_are_paged_by_day(self):
        """Release mode returns one bounded page of days, like the web page."""
        days = [{"date": f"2026-01-0{n}", "entries": []} for n in range(1, 4)]
        with patch(
            "app.history_views._build_release_history_days",
            return_value=days,
        ):
            response = self.call_api(
                "get",
                "api_history_release",
                headers=self.auth_headers,
                params={"limit": 2, "offset": 1},
            )
        self.assertEqual(response.status_code, HTTP.OK)
        data = response.json()
        self.assertEqual([d["date"] for d in data["results"]], ["2026-01-02", "2026-01-03"])
        self.assertEqual(data["pagination"]["total"], 3)
        self.assertIsNone(data["pagination"]["next"])

    def test_saved_view_created_for_history(self):
        """A saved view keeps only the supported History filters."""
        response = self.call_api(
            "post",
            "api_history_saved_views",
            payload={"name": "Movies", "query": "media_type=movie&bogus=1"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED, response.content)
        saved = SavedView.objects.get(user=self.user1, name="Movies")
        self.assertEqual(saved.media_type, "history")
        self.assertEqual(saved.query, "media_type=movie")

    def test_saved_view_needs_a_name(self):
        """An empty name returns 400."""
        response = self.call_api(
            "post",
            "api_history_saved_views",
            payload={"name": "  ", "query": ""},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
