from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from app.providers import manual, tmdb

METADATA_PATH = "app.providers.services.get_media_metadata"

SEASON_METADATA = {
    "episodes": [{"episode_number": 1}, {"episode_number": 2}],
    "max_progress": 2,
    "image": "s.jpg",
    "season/1": {"episodes": [{"episode_number": 1}, {"episode_number": 2}]},
}


@patch(METADATA_PATH, return_value=SEASON_METADATA)
class EpisodePassHistory(TestCase):
    """Episode payloads report the current pass separately from all plays."""

    def setUp(self):
        """Watch a two-episode season to the end."""
        self.user = get_user_model().objects.create_user(username="t", password="x")
        tv_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        self.tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        self.episode_items = []
        for episode_number in (1, 2):
            item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=1,
                episode_number=episode_number,
            )
            self.episode_items.append(item)
            with patch(METADATA_PATH, return_value=SEASON_METADATA):
                Episode.objects.create(
                    item=item,
                    related_season=self.season,
                    end_date=datetime(2023, 6, episode_number, tzinfo=UTC),
                )

    def _metadata(self):
        return {
            "media_id": "123",
            "source": Sources.TMDB.value,
            "season_number": 1,
            "episodes": [
                {"episode_number": 1, "still_path": None, "media_id": "123", "image": ""},
                {"episode_number": 2, "still_path": None, "media_id": "123", "image": ""},
            ],
        }

    def test_episode_state_without_artwork_preserves_history_and_skips_image_fetches(self, _mock_metadata):
        metadata = self._metadata()
        plays = list(self.season.episodes.all())
        with patch.object(tmdb.helpers, "get_tmdb_backdrop_image") as backdrop, patch.object(
            tmdb, "get_tvdb_episode_image_map", return_value={}
        ) as tvdb_images:
            rows = tmdb.process_episodes(metadata, plays, season=self.season, include_artwork=False)
        backdrop.assert_not_called()
        tvdb_images.assert_not_called()
        self.assertEqual(len(rows[0]["history"]), 1)
        self.assertEqual(rows[0]["history"], rows[0]["all_history"])
        self.assertEqual(rows[0]["episode_number"], 1)
        self.assertIsNone(rows[0]["image"])

    def test_pass_history_matches_history_without_a_rewatch(self, _mock_metadata):
        """Outside a pass, both lists describe the same plays."""
        episodes = tmdb.process_episodes(
            self._metadata(),
            list(self.season.episodes.all()),
            season=self.season,
        )

        self.assertEqual(len(episodes[0]["history"]), 1)
        self.assertEqual(len(episodes[0]["all_history"]), 1)

    def test_pass_history_is_empty_when_a_rewatch_starts(self, _mock_metadata):
        """During a pass, earlier plays stay in history but not in the pass."""
        self.season.start_rewatch()

        episodes = tmdb.process_episodes(
            self._metadata(),
            list(self.season.episodes.all()),
            season=self.season,
        )

        self.assertEqual(episodes[0]["history"], [])
        self.assertEqual(len(episodes[0]["all_history"]), 1)

    def test_pass_history_picks_up_plays_logged_during_the_pass(self, _mock_metadata):
        """Replaying an episode ticks it again for the current pass."""
        self.season.start_rewatch()
        Episode.objects.create(
            item=self.episode_items[0],
            related_season=self.season,
            end_date=timezone.now(),
        )

        episodes = tmdb.process_episodes(
            self._metadata(),
            list(self.season.episodes.all()),
            season=self.season,
        )

        self.assertEqual(len(episodes[0]["all_history"]), 2)
        self.assertEqual(len(episodes[0]["history"]), 1)
        self.assertEqual(episodes[1]["history"], [])

    def test_manual_source_reports_the_pass_the_same_way(self, _mock_metadata):
        """Manual shows must not diverge from provider-backed ones."""
        self.season.start_rewatch()
        manual_metadata = {
            "season_number": 1,
            "episodes": [
                {
                    "episode_number": 1,
                    "media_id": "123",
                    "image": "",
                    "title": "One",
                },
            ],
        }

        episodes = manual.process_episodes(
            manual_metadata,
            list(self.season.episodes.all()),
            season=self.season,
        )

        self.assertEqual(episodes[0]["history"], [])
        self.assertEqual(len(episodes[0]["all_history"]), 1)

