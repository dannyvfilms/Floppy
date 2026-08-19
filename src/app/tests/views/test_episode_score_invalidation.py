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
