from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app import history_cache
from app.models import TV, Episode, Item, MediaTypes, Season, Sources


class UpdateEpisodeScoreInvalidationTests(TestCase):
    """update_episode_score must invalidate the affected history day cache."""

    def setUp(self):
        # Episode.save() reaches out to providers for season metadata; stub it.
        metadata_patch = patch(
            "app.providers.services.get_media_metadata",
            return_value={"season/1": {"episodes": [{}, {}]}},
        )
        fetch_releases_patch = patch("app.models.Item.fetch_releases")
        metadata_patch.start()
        fetch_releases_patch.start()
        self.addCleanup(metadata_patch.stop)
        self.addCleanup(fetch_releases_patch.stop)

        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        tv_item = Item.objects.create(
            media_id="show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        tv = TV.objects.create(item=tv_item, user=self.user)
        season_item = Item.objects.create(
            media_id="show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show Season 1",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
        )
        episode_item = Item.objects.create(
            media_id="show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode Two",
            season_number=1,
            episode_number=2,
        )
        self.end_date = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
        self.episode = Episode.objects.create(
            item=episode_item,
            related_season=self.season,
            end_date=self.end_date,
        )

    def test_rating_episode_invalidates_history_day(self):
        with patch.object(history_cache, "invalidate_history_days") as mock_invalidate:
            response = self.client.post(
                reverse(
                    "update_episode_score",
                    kwargs={"season_id": self.season.id, "episode_number": 2},
                ),
                {"score": "8"},
            )

        self.assertEqual(response.status_code, 200)
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.score, 8)

        mock_invalidate.assert_called_once()
        _, kwargs = mock_invalidate.call_args
        expected_day = history_cache.history_day_key(self.end_date)
        self.assertEqual(kwargs["day_keys"], [expected_day])


class UnwatchedEpisodeRatingTests(UpdateEpisodeScoreInvalidationTests):
    """Rating an episode nobody watched stores a rating, not a play (#1448)."""

    def _rate(self, score, **extra):
        return self.client.post(
            reverse(
                "update_episode_score",
                kwargs={"season_id": self.season.id, "episode_number": 1},
            ),
            {"score": score, **extra},
        )

    def test_unwatched_episode_gets_rating_only_row(self):
        response = self._rate("8")

        self.assertEqual(response.status_code, 200)
        (row,) = Episode.ratings.filter(related_season=self.season, rating_only=True)
        self.assertEqual(row.score, 8)
        self.assertEqual(row.item.episode_number, 1)
        # The existing play is the only watch the season knows about.
        self.assertEqual(Episode.objects.filter(related_season=self.season).count(), 1)
        self.assertEqual(self.season.completed_episode_count, 1)

    def test_rating_again_with_toggle_clears_the_row(self):
        self._rate("8")
        self._rate("8", toggle="1")

        self.assertFalse(
            Episode.ratings.filter(related_season=self.season, rating_only=True).exists(),
        )

    def test_unwatched_rating_is_kept_when_the_episode_is_first_watched(self):
        self._rate("6")
        self.season.refresh_from_db()
        self.season.watch(1, datetime(2026, 7, 4, tzinfo=UTC))

        play = Episode.objects.get(related_season=self.season, item__episode_number=1)
        self.assertEqual(play.score, 6)
        self.assertFalse(
            Episode.ratings.filter(related_season=self.season, rating_only=True).exists(),
        )

    def test_season_page_rows_of_unwatched_episodes_can_be_rated(self):
        from app.activity_builders import attach_unwatched_ratings

        self._rate("9")
        metadata = {"media_id": "show-1", "source": Sources.TMDB.value, "season_number": 1}
        rows = attach_unwatched_ratings(
            [
                {"episode_number": 1, "all_history": []},
                {"episode_number": 2, "all_history": [self.episode]},
            ],
            self.user,
            metadata,
        )

        self.assertEqual(rows[0]["rating_season_id"], self.season.id)
        self.assertEqual(rows[0]["unwatched_score"], 9)
        self.assertNotIn("rating_season_id", rows[1])
