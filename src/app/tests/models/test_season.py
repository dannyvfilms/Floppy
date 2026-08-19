from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
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
from users.models import QuickWatchDateChoices

mock_path = Path(__file__).resolve().parent.parent / "mock_data"


class SeasonModel(TestCase):
    """Test the @properties and custom save of the Season model."""

    def setUp(self):
        """Create a user and a season with episodes."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        item_season = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )

        self.season = Season.objects.create(
            item=item_season,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        item_ep1 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )
        Episode.objects.create(
            item=item_ep1,
            related_season=self.season,
            end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
        )

        item_ep2 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=2,
        )
        Episode.objects.create(
            item=item_ep2,
            related_season=self.season,
            end_date=datetime(2023, 6, 2, 0, 0, tzinfo=UTC),
        )

    def test_season_progress(self):
        """Test the progress property of the Season model."""
        self.assertEqual(self.season.progress, 2)

    def test_completed_episode_count(self):
        """Test completed episode count ignores duplicates and non-completed plays."""
        item_ep2 = Item.objects.get(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
        )
        Episode.objects.create(
            item=item_ep2,
            related_season=self.season,
            end_date=datetime(2023, 6, 3, 0, 0, tzinfo=UTC),
        )

        # Completed with no end_date still counts (issue #498).
        item_ep3 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=3,
        )
        Episode.objects.create(
            item=item_ep3,
            related_season=self.season,
            end_date=None,
        )

        # Not-yet-watched status doesn't count, even with an end_date set.
        item_ep4 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="The One After",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=4,
        )
        Episode.objects.create(
            item=item_ep4,
            related_season=self.season,
            end_date=datetime(2023, 6, 4, 0, 0, tzinfo=UTC),
            status=Status.PLANNING.value,
        )

        self.assertEqual(self.season.completed_episode_count, 3)
        self.assertEqual(self.season.progress, 3)

    def test_progress_first_watch_with_gap(self):
        """Regression for #327: watching a later episode before a skipped one
        should report the highest episode number touched, not the gap.
        """
        item_ep4 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=4,
        )
        Episode.objects.create(
            item=item_ep4,
            related_season=self.season,
            end_date=datetime(2023, 6, 4, 0, 0, tzinfo=UTC),
        )
        # setUp already watched ep1 and ep2; episode 3 is skipped entirely.
        self.assertEqual(self.season.progress, 4)

    def test_progress_rewatch_tolerates_skipped_episode(self):
        """Regression for #327: a second watchthrough that skips one episode
        should not get stuck at the skip point.
        """
        item_season = Item.objects.create(
            media_id="9999",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Rewatch Show",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        season = Season.objects.create(
            item=item_season,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        for ep_num in range(1, 7):
            item = Item.objects.create(
                media_id="9999",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Rewatch Show",
                image="http://example.com/image.jpg",
                season_number=1,
                episode_number=ep_num,
            )
            Episode.objects.create(
                item=item,
                related_season=season,
                end_date=datetime(2023, 6, ep_num, 0, 0, tzinfo=UTC),
            )
            if ep_num != 5:
                # Second watch for everything except episode 5 (implicit skip).
                Episode.objects.create(
                    item=item,
                    related_season=season,
                    end_date=datetime(2023, 7, ep_num, 0, 0, tzinfo=UTC),
                )

        # 5 of 6 episodes reached a second watch, a strict majority, so
        # progress should advance to 6 rather than freeze at 4.
        self.assertEqual(season.progress, 6)

    def _make_skip_ahead_season(self, media_id, runtime_minutes=None):
        """Create a season with only episode 9 of 10 watched, nothing before it."""
        item_season = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Skip Ahead Show",
            image="http://example.com/image.jpg",
            season_number=1,
            runtime_minutes=runtime_minutes,
        )
        season = Season.objects.create(
            item=item_season,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        item_ep9 = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Skip Ahead Show",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=9,
        )
        Episode.objects.create(
            item=item_ep9,
            related_season=season,
            end_date=datetime(2023, 6, 9, 0, 0, tzinfo=UTC),
        )
        return season

    def test_plays_sort_value_uses_completed_count_not_position(self):
        """Regression for #527: watching only a later episode is 1 play, not the ep number."""
        season = self._make_skip_ahead_season("8888")

        self.assertEqual(season.progress, 9)
        self.assertEqual(season._plays_sort_value(), 1)

    def test_progress_percentage_uses_completed_count(self):
        """Regression for #527: percentage should reflect episodes watched, not position."""
        season = self._make_skip_ahead_season("8889")
        season.max_progress = 10

        self.assertEqual(season.progress_percentage, 10)

    def test_progress_percentage_none_without_max_progress(self):
        """No max_progress attribute means percentage can't be computed."""
        item_season = Item.objects.create(
            media_id="8891",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="No Episodes Show",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        season = Season.objects.create(
            item=item_season,
            user=self.user,
            status=Status.PLANNING.value,
        )

        self.assertIsNone(season.progress_percentage)

    def test_progress_percentage_clamped_at_100(self):
        """Completed count exceeding max_progress should clamp to 100, not overshoot."""
        self.season.max_progress = 1
        self.assertEqual(self.season.progress_percentage, 100)

    def test_time_watched_minutes_single_out_of_order_watch(self):
        """Regression for #527: one watched episode reports one episode's runtime."""
        season = self._make_skip_ahead_season("8890", runtime_minutes=30)

        self.assertEqual(season.time_watched_minutes, 30)

    def test_season_start_date(self):
        """Test the start_date property of the Season model."""
        self.assertEqual(
            self.season.start_date,
            datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
        )

    def test_season_end_date(self):
        """Test the end_date property of the Season model."""
        self.assertEqual(
            self.season.end_date,
            datetime(2023, 6, 2, 0, 0, tzinfo=UTC),
        )

    @patch("app.models.providers.services.get_media_metadata")
    def test_season_save(self, mock_get_metadata):
        """Test the custom save method of the Season model."""
        mock_get_metadata.return_value = {
            "episodes": [
                {"episode_number": episode_number, "image": f"img{episode_number}.jpg"}
                for episode_number in range(1, 25)
            ],
            "image": "season_img.jpg",
            "related": {
                "seasons": [{"season_number": 1}],
            },
        }

        self.season.status = Status.COMPLETED.value
        self.season.save(update_fields=["status"])

        self.assertEqual(self.season.episodes.count(), 24)

    @patch("app.models.Season.get_episode_item")
    def test_watch_method(self, mock_get_episode_item):
        """Test the watch method of the Season model."""
        episode_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=3,
        )
        mock_get_episode_item.return_value = episode_item

        self.season.watch(3, datetime(2023, 6, 3, 0, 0, tzinfo=UTC))

        episode = Episode.objects.get(
            related_season=self.season,
            item=episode_item,
        )
        self.assertEqual(episode.end_date, datetime(2023, 6, 3, 0, 0, tzinfo=UTC))

        self.season.watch(3, datetime(2023, 6, 4, 0, 0, tzinfo=UTC))

        episodes = Episode.objects.filter(
            related_season=self.season,
            item=episode_item,
        )
        self.assertEqual(
            episodes.first().end_date,
            datetime(2023, 6, 4, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(episodes.count(), 2)

    @patch("app.models.Season.get_episode_item")
    def test_watch_with_none_date(self, mock_get_episode_item):
        """Test the watch method with None date."""
        episode_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=3,
        )
        mock_get_episode_item.return_value = episode_item

        self.season.watch(3, None)

        episode = Episode.objects.get(
            related_season=self.season,
            item=episode_item,
        )
        self.assertIsNone(episode.end_date)

    @patch("app.models.Season.get_episode_item")
    def test_unwatch_method(self, mock_get_episode_item):
        """Test the unwatch method of the Season model."""
        episode_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=3,
        )
        mock_get_episode_item.return_value = episode_item

        Episode.objects.create(
            related_season=self.season,
            item=episode_item,
            end_date=datetime(2023, 6, 3, 0, 0, tzinfo=UTC),
        )

        self.season.unwatch(3)

        with self.assertRaises(Episode.DoesNotExist):
            Episode.objects.get(
                related_season=self.season,
                item=episode_item,
            )

    @patch("app.models.Season.get_episode_item")
    def test_unwatch_with_repeats(self, mock_get_episode_item):
        """Test the unwatch method with an episode that has repeats."""
        episode_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=3,
        )
        mock_get_episode_item.return_value = episode_item

        Episode.objects.create(
            related_season=self.season,
            item=episode_item,
            end_date=datetime(2023, 6, 3, 0, 0, tzinfo=UTC),
        )
        Episode.objects.create(
            related_season=self.season,
            item=episode_item,
            end_date=datetime(2024, 6, 3, 0, 0, tzinfo=UTC),
        )

        self.season.unwatch(3)

        episodes = Episode.objects.filter(
            related_season=self.season,
            item=episode_item,
        )
        self.assertEqual(episodes.count(), 1)

    @patch("app.models.Season.get_episode_item")
    def test_unwatch_nonexistent_episode(self, mock_get_episode_item):
        """Test unwatching a non-existent episode."""
        episode_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=3,
        )
        mock_get_episode_item.return_value = episode_item

        self.season.unwatch(3)

        with self.assertRaises(Episode.DoesNotExist):
            Episode.objects.get(
                related_season=self.season,
                item=episode_item,
            )


class SeasonStatusTests(TestCase):
    """Test Season model status change behaviors."""

    def setUp(self):
        """Create test data."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.tv_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
            image="http://example.com/image.jpg",
        )

        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        self.season_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            image="http://example.com/image.jpg",
            season_number=1,
        )

        self.season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )

    @patch("app.models.providers.services.get_media_metadata")
    def test_completed_status_creates_remaining_episodes(self, mock_get_metadata):
        """Test setting status to COMPLETED creates remaining episodes."""
        mock_metadata = {
            "episodes": [
                {"episode_number": 1, "image": "img1.jpg"},
                {"episode_number": 2, "image": "img2.jpg"},
                {"episode_number": 3, "image": "img3.jpg"},
            ],
            "image": "season_img.jpg",
        }
        mock_get_metadata.return_value = mock_metadata

        self.season.status = Status.COMPLETED.value
        self.season.save()

        self.assertEqual(self.season.episodes.count(), 3)
        episode_numbers = set(
            self.season.episodes.values_list("item__episode_number", flat=True),
        )
        self.assertEqual(episode_numbers, {1, 2, 3})

    @patch("app.models.providers.services.get_media_metadata")
    def test_completed_status_starts_next_season(self, mock_get_metadata):
        """Test completing a season starts the next season automatically."""
        next_season_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            image="http://example.com/image2.jpg",
            season_number=2,
        )
        next_season = Season.objects.create(
            item=next_season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )

        mock_get_metadata.return_value = {
            "episodes": [
                {"episode_number": 1, "image": "img1.jpg"},
            ],
            "image": "season_img.jpg",
        }

        self.season.status = Status.COMPLETED.value
        self.season.save()

        next_season.refresh_from_db()
        self.assertEqual(next_season.status, Status.IN_PROGRESS.value)

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)

    @patch("app.models.providers.services.get_media_metadata")
    def test_completed_last_season_completes_tv_show(self, mock_get_metadata):
        """Test completing the last season completes the TV show."""
        mock_get_metadata.side_effect = [
            {
                "episodes": [
                    {"episode_number": 1, "image": "img1.jpg"},
                ],
                "image": "season_img.jpg",
            },
            {
                "related": {
                    "seasons": [{"season_number": 1, "image": "season_img.jpg"}],
                },
            },
        ]

        self.season.status = Status.COMPLETED.value
        self.season.save()

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.COMPLETED.value)

    def test_dropped_status_updates_tv_status(self):
        """Test setting status to DROPPED updates TV status."""
        self.season.status = Status.DROPPED.value
        self.season.save()

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.DROPPED.value)

    def test_in_progress_status_updates_tv_status(self):
        """Test setting status to IN_PROGRESS updates TV status."""
        self.season.status = Status.IN_PROGRESS.value
        self.season.save()

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)

    def test_status_change_does_not_affect_tv_if_already_same_status(self):
        """Test status change doesn't update TV if already same status."""
        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()

        with patch.object(TV, "save") as mock_tv_save:
            self.season.status = Status.IN_PROGRESS.value
            self.season.save()

            # TV save shouldn't have been called
            mock_tv_save.assert_not_called()

    @patch("app.models.providers.services.get_media_metadata")
    def test_completed_status_noop_if_no_remaining_episodes(self, mock_get_metadata):
        """Test COMPLETED status does nothing if no remaining episodes."""
        mock_metadata = {
            "episodes": [
                {"episode_number": 1, "image": "img1.jpg"},
            ],
            "image": "season_img.jpg",
        }
        mock_get_metadata.return_value = mock_metadata

        ep_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Episode",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )
        Episode.objects.bulk_create(
            [
                Episode(
                    item=ep_item,
                    related_season=self.season,
                    end_date=timezone.now(),
                ),
            ],
        )

        with patch("app.models.tv.bulk_create_with_history") as mock_bulk_create:
            self.season.status = Status.COMPLETED.value
            self.season.save()

            # bulk_create shouldn't have been called
            mock_bulk_create.assert_not_called()

    def test_promote_to_completed_skips_manual_in_progress(self):
        """Regression: promote_to_completed_if_fully_watched must not override
        a manually set IN_PROGRESS status (rewatch scenario, issue #261).
        """
        ep_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Show",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )
        Episode.objects.create(
            item=ep_item,
            related_season=self.season,
            end_date=datetime(2024, 1, 1, tzinfo=UTC),
        )

        # Season is fully watched (1/1 episodes), user manually set IN_PROGRESS
        self.season.status = Status.IN_PROGRESS.value
        self.season.save()
        self.season.refresh_from_db()

        # promote_to_completed_if_fully_watched should be a no-op
        result = self.season.promote_to_completed_if_fully_watched(max_progress=1)
        self.assertFalse(result)

        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_get_tv_creates_tv_if_not_exists(self):
        """Test get_tv creates TV instance if it doesn't exist."""
        self.tv.delete()

        with patch(
            "app.models.providers.services.get_media_metadata",
        ) as mock_get_metadata:
            mock_metadata = {
                "title": "Test Show",
                "image": "tv_img.jpg",
                "details": {"seasons": 1},
            }
            mock_get_metadata.return_value = mock_metadata

            # Call get_tv
            tv = self.season.get_tv()

            self.assertIsNotNone(tv)
            self.assertEqual(tv.item.title, "Test Show")
            self.assertEqual(tv.status, Status.PLANNING.value)

    def test_get_tv_prefers_matching_library_media_type_bucket(self):
        """get_tv must not attach a season to a TV row from the other identity.

        Regression test for GitHub issue #623: when a show is tracked under
        both its TV identity and its anime identity (two separate TV rows,
        distinguished only by Item.library_media_type), get_tv used to pick
        whichever TV row matched media_id/source/user first, regardless of
        bucket, silently mis-attaching the season.
        """
        self.tv_item.library_media_type = MediaTypes.TV.value
        self.tv_item.save(update_fields=["library_media_type"])

        anime_tv_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
            image="http://example.com/image.jpg",
            library_media_type=MediaTypes.ANIME.value,
        )
        anime_tv = TV.objects.create(
            item=anime_tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        self.season.related_tv = None
        self.season.item.library_media_type = MediaTypes.ANIME.value
        self.season.item.save(update_fields=["library_media_type"])

        resolved = self.season.get_tv()

        self.assertEqual(resolved.id, anime_tv.id)


class SeasonGetRemainingEpsQuickWatchDateTests(TestCase):
    """Tests for Season.get_remaining_eps with different quick_watch_date settings."""

    def setUp(self):
        """Create a user and a season for testing."""
        self.QuickWatchDateChoices = QuickWatchDateChoices
        self.credentials = {"username": "test_quick", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        item_season = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )

        self.season = Season.objects.create(
            item=item_season,
            user=self.user,
            status=Status.PLANNING.value,
        )

        self.mock_metadata = {
            "episodes": [
                {
                    "episode_number": 1,
                    "image": "img1.jpg",
                    "air_date": datetime(1994, 9, 22, tzinfo=UTC),
                },
                {
                    "episode_number": 2,
                    "image": "img2.jpg",
                    "air_date": datetime(1994, 9, 29, tzinfo=UTC),
                },
                {
                    "episode_number": 3,
                    "image": "img3.jpg",
                    "air_date": None,
                },
            ],
            "image": "season_img.jpg",
        }

    @patch("app.models.Season.get_episode_item")
    def test_get_remaining_eps_current_date(self, mock_get_episode_item):
        """Test get_remaining_eps uses current date for CURRENT_DATE preference."""
        self.user.quick_watch_date = self.QuickWatchDateChoices.CURRENT_DATE
        self.user.save()

        for i in range(1, 4):
            mock_get_episode_item.return_value = Item.objects.create(
                media_id="1668",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Episode {i}",
                image=f"img{i}.jpg",
                season_number=1,
                episode_number=i,
            )

        episodes = self.season.get_remaining_eps(self.mock_metadata)

        for ep in episodes:
            self.assertIsNotNone(ep.end_date)

    @patch("app.models.Season.get_episode_item")
    def test_get_remaining_eps_no_date(self, mock_get_episode_item):
        """Test get_remaining_eps sets None for NO_DATE preference."""
        self.user.quick_watch_date = self.QuickWatchDateChoices.NO_DATE
        self.user.save()

        for i in range(1, 4):
            mock_get_episode_item.return_value = Item.objects.create(
                media_id="1668",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Episode {i}",
                image=f"img{i}.jpg",
                season_number=1,
                episode_number=i,
            )

        episodes = self.season.get_remaining_eps(self.mock_metadata)

        for ep in episodes:
            self.assertIsNone(ep.end_date)

    @patch("app.models.Season.get_episode_item")
    def test_get_remaining_eps_release_date(self, mock_get_episode_item):
        """Test get_remaining_eps uses air_date for RELEASE_DATE preference."""
        self.user.quick_watch_date = self.QuickWatchDateChoices.RELEASE_DATE
        self.user.save()

        episode_items = []
        for i in range(1, 4):
            item = Item.objects.create(
                media_id="1668",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Episode {i}",
                image=f"img{i}.jpg",
                season_number=1,
                episode_number=i,
            )
            episode_items.append(item)

        mock_get_episode_item.side_effect = episode_items

        episodes = self.season.get_remaining_eps(self.mock_metadata)

        # Episodes returned in reverse order (3, 2, 1)
        self.assertIsNone(episodes[0].end_date)  # Episode 3 has no air_date
        self.assertEqual(episodes[1].end_date, datetime(1994, 9, 29, tzinfo=UTC))
        self.assertEqual(episodes[2].end_date, datetime(1994, 9, 22, tzinfo=UTC))

    @patch("app.models.providers.services.get_media_metadata")
    def test_season_completion_with_no_date(self, mock_get_metadata):
        """Integration test: completing a season with NO_DATE preference."""
        self.user.quick_watch_date = self.QuickWatchDateChoices.NO_DATE
        self.user.save()

        mock_get_metadata.return_value = {
            "episodes": [
                {"episode_number": 1, "image": "img1.jpg", "air_date": None},
                {"episode_number": 2, "image": "img2.jpg", "air_date": None},
            ],
            "image": "season_img.jpg",
        }

        self.season.status = Status.COMPLETED.value
        self.season.save()

        episodes = Episode.objects.filter(related_season=self.season)
        self.assertEqual(episodes.count(), 2)
        for ep in episodes:
            self.assertIsNone(ep.end_date)

    @patch("app.models.providers.services.get_media_metadata")
    def test_season_completion_with_release_date(self, mock_get_metadata):
        """Integration test: completing a season with RELEASE_DATE preference."""
        self.user.quick_watch_date = self.QuickWatchDateChoices.RELEASE_DATE
        self.user.save()

        mock_get_metadata.return_value = {
            "episodes": [
                {
                    "episode_number": 1,
                    "image": "img1.jpg",
                    "air_date": datetime(1994, 9, 22, tzinfo=UTC),
                },
                {
                    "episode_number": 2,
                    "image": "img2.jpg",
                    "air_date": datetime(1994, 9, 29, tzinfo=UTC),
                },
            ],
            "image": "season_img.jpg",
        }

        self.season.status = Status.COMPLETED.value
        self.season.save()

        episodes = Episode.objects.filter(related_season=self.season).order_by(
            "item__episode_number",
        )
        self.assertEqual(episodes.count(), 2)
        self.assertEqual(episodes[0].end_date, datetime(1994, 9, 22, tzinfo=UTC))
        self.assertEqual(episodes[1].end_date, datetime(1994, 9, 29, tzinfo=UTC))

    @patch("app.models.Season.get_episode_item")
    def test_get_remaining_eps_explicit_end_date_overrides_preference(
        self,
        mock_get_episode_item,
    ):
        """An explicit end_date argument wins over the user's quick_watch_date."""
        self.user.quick_watch_date = self.QuickWatchDateChoices.CURRENT_DATE
        self.user.save()

        for i in range(1, 4):
            mock_get_episode_item.return_value = Item.objects.create(
                media_id="1668",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Episode {i}",
                image=f"img{i}.jpg",
                season_number=1,
                episode_number=i,
            )

        episodes = self.season.get_remaining_eps(self.mock_metadata, end_date=None)

        for ep in episodes:
            self.assertIsNone(ep.end_date)

    @patch("app.models.providers.services.get_media_metadata")
    def test_season_completion_with_pending_end_date_blank(self, mock_get_metadata):
        """Completing via the form with a blank end_date persists no date,
        even when the user's quick_watch_date preference defaults to today.
        """
        self.user.quick_watch_date = self.QuickWatchDateChoices.CURRENT_DATE
        self.user.save()

        mock_get_metadata.return_value = {
            "episodes": [
                {"episode_number": 1, "image": "img1.jpg", "air_date": None},
                {"episode_number": 2, "image": "img2.jpg", "air_date": None},
            ],
            "image": "season_img.jpg",
        }

        self.season.status = Status.COMPLETED.value
        self.season._pending_end_date = None
        self.season.save()

        episodes = Episode.objects.filter(related_season=self.season)
        self.assertEqual(episodes.count(), 2)
        for ep in episodes:
            self.assertIsNone(ep.end_date)

    @patch("app.models.providers.services.get_media_metadata")
    def test_season_completion_with_pending_end_date_explicit(self, mock_get_metadata):
        """Completing via the form with an explicit end_date applies it to all episodes."""
        self.user.quick_watch_date = self.QuickWatchDateChoices.CURRENT_DATE
        self.user.save()

        mock_get_metadata.return_value = {
            "episodes": [
                {"episode_number": 1, "image": "img1.jpg", "air_date": None},
                {"episode_number": 2, "image": "img2.jpg", "air_date": None},
            ],
            "image": "season_img.jpg",
        }

        chosen_date = datetime(2000, 1, 1, tzinfo=UTC)
        self.season.status = Status.COMPLETED.value
        self.season._pending_end_date = chosen_date
        self.season.save()

        episodes = Episode.objects.filter(related_season=self.season)
        self.assertEqual(episodes.count(), 2)
        for ep in episodes:
            self.assertEqual(ep.end_date, chosen_date)


class SeasonEpisodeItemModelTests(TestCase):
    """Focused tests for season episode item creation/updating."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="episode-item-user",
            password="12345",
        )
        season_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/season.jpg",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

    @override_settings(TIME_ZONE="Europe/Berlin")
    def test_get_episode_item_anchors_date_only_air_date_to_utc(self):
        """A date-only air_date must not shift with the server's TIME_ZONE.

        Regression test: get_episode_item() used to interpret a "YYYY-MM-DD"
        air_date as midnight in the server's configured TIME_ZONE rather
        than UTC. Under a positive-offset zone like Europe/Berlin (+2h in
        summer), that shifted the stored release_datetime into the previous
        UTC day - e.g. an episode that airs 2026-07-15 got stored as
        2026-07-14 22:00 UTC, so any page or comparison that reads the date
        component in UTC showed the wrong calendar day.
        """
        item = self.season.get_episode_item(
            5,
            {
                "episodes": [
                    {
                        "episode_number": 5,
                        "name": "No Shortcuts",
                        "air_date": "2026-07-15",
                    },
                ],
            },
        )

        self.assertEqual(
            item.release_datetime,
            datetime(2026, 7, 15, 0, 0, tzinfo=UTC),
            "a date-only air_date must be stored as UTC midnight, "
            "regardless of the server's configured TIME_ZONE",
        )

    def test_get_episode_item_updates_existing_item_with_episode_title(self):
        """Episode items should store the episode title instead of the show title."""
        existing_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            localized_title="Friends",
            image=settings.IMG_NONE,
            season_number=1,
            episode_number=3,
        )

        item = self.season.get_episode_item(
            3,
            {
                "episodes": [
                    {
                        "episode_number": 3,
                        "name": "The One with the Thumb",
                        "image": "https://example.com/s1e3.jpg",
                        "air_date": "1994-10-06",
                    },
                ],
            },
        )

        existing_item.refresh_from_db()
        self.assertEqual(item.id, existing_item.id)
        self.assertEqual(existing_item.title, "The One with the Thumb")
        self.assertEqual(existing_item.localized_title, "The One with the Thumb")

    @patch("app.providers.tmdb.get_tvdb_episode_image_map")
    def test_get_episode_item_uses_tvdb_episode_art_when_tmdb_still_missing(
        self,
        mock_get_tvdb_episode_image_map,
    ):
        """TMDB episode items should persist TVDB episode art before IMG_NONE."""
        mock_get_tvdb_episode_image_map.return_value = {
            "4": "https://example.com/tvdb-s1e4.jpg",
        }

        item = self.season.get_episode_item(
            4,
            {
                "tvdb_id": "998877",
                "season_number": 1,
                "episodes": [
                    {
                        "episode_number": 4,
                        "name": "The One with George Stephanopoulos",
                        "still_path": None,
                        "air_date": "1994-10-13",
                    },
                ],
            },
        )

        self.assertEqual(item.title, "The One with George Stephanopoulos")
        self.assertEqual(item.image, "https://example.com/tvdb-s1e4.jpg")
