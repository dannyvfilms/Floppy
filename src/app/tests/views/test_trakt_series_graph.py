from datetime import timedelta

from django.test import RequestFactory, TestCase
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from app.views import TRAKT_SERIES_GRAPH_MAX_POLLS, trakt_series_graph_fragment


class TraktSeriesGraphFragmentTests(TestCase):
    """Coverage for Trakt series graph polling behavior."""

    def test_specials_do_not_keep_show_graph_polling(self):
        """Season 0 episodes should not hold the show-level poll open."""
        Item.objects.create(
            media_id="show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Special 1",
            season_number=0,
            episode_number=1,
        )
        Item.objects.create(
            media_id="show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode 1",
            season_number=1,
            episode_number=1,
            trakt_rating=8.0,
            trakt_rating_count=100,
        )

        request = RequestFactory().get("/app/api/trakt-series-graph/tmdb/show-1/")
        response = trakt_series_graph_fragment(request, Sources.TMDB.value, "show-1")

        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('hx-trigger="every 5s"', content)
        self.assertNotIn("Fetching remaining episodes", content)

    def _unrated_episode(self, media_id, release_datetime=None):
        Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Unrated",
            season_number=1,
            episode_number=1,
            release_datetime=release_datetime,
        )

    def _poll(self, media_id, query=""):
        request = RequestFactory().get(
            f"/app/api/trakt-series-graph/tmdb/{media_id}/{query}"
        )
        return trakt_series_graph_fragment(request, Sources.TMDB.value, media_id)

    def test_unaired_episodes_do_not_keep_graph_polling(self):
        """An episode that has not aired cannot have a rating yet."""
        self._unrated_episode(
            "show-2", release_datetime=timezone.now() + timedelta(days=30)
        )

        content = self._poll("show-2").content.decode()

        self.assertNotIn('hx-trigger="every 5s"', content)

    def test_polling_stops_after_the_attempt_cap(self):
        """An aired episode Trakt never rates must not poll for as long as the page is open."""
        self._unrated_episode("show-3")

        first = self._poll("show-3").content.decode()
        last = self._poll(
            "show-3", f"?attempt={TRAKT_SERIES_GRAPH_MAX_POLLS}"
        ).content.decode()

        self.assertIn('hx-trigger="every 5s"', first)
        self.assertIn("?attempt=1", first)
        self.assertNotIn('hx-trigger="every 5s"', last)
