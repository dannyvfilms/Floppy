from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from app.models import (
    TV,
    DeletedMedia,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from integrations.imports import (
    helpers,
)

mock_path = Path(__file__).resolve().parent.parent / "mock_data"
app_mock_path = (
    Path(__file__).resolve().parent.parent.parent.parent / "app" / "tests" / "mock_data"
)


class HelpersTest(TestCase):
    """Test helper functions for imports."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def test_bulk_completed_media_removes_stale_planning_row(self):
        """Bulk persistence applies the same planning normalization as save()."""
        item = Item.objects.create(
            media_id="bulk-movie",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Bulk Movie",
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
            score=7,
            notes="import plan",
        )
        completed = Movie(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
        )

        helpers.bulk_create_media(
            {MediaTypes.MOVIE.value: [completed]},
            self.user,
        )

        rows = Movie.objects.filter(item=item, user=self.user)
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.status, Status.COMPLETED.value)
        self.assertEqual(row.score, 7)
        self.assertEqual(row.notes, "import plan")

    def test_update_season_references(self):
        """Test updating season references with actual TV instances."""
        item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
        )
        tv = TV.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        new_season = Season(
            item=item,
            user=self.user,
            related_tv=TV(item=item, user=self.user),
        )

        helpers.update_season_references([new_season], self.user)

        self.assertEqual(new_season.related_tv.id, tv.id)

    def test_update_episode_references(self):
        """Test updating episode references with actual Season instances."""
        tv_item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        season_item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            season_number=1,
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.PLANNING.value,
        )

        episode_item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Show",
            season_number=1,
            episode_number=1,
        )

        new_episode = Episode(
            item=episode_item,
            related_season=Season(item=season_item, related_tv=tv, user=self.user),
        )

        helpers.update_episode_references([new_episode], self.user)

        self.assertEqual(new_episode.related_season.id, season.id)

    def test_bulk_create_media_orders_tv_season_and_episode_dependencies(self):
        """Out-of-order batches should still save TV, seasons, then episodes safely."""
        tv_item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
            image="tv.jpg",
        )
        season_item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            image="season.jpg",
            season_number=1,
        )
        episode_item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Show",
            image="episode.jpg",
            season_number=1,
            episode_number=1,
        )

        tv = TV(item=tv_item, user=self.user, status=Status.IN_PROGRESS.value)
        season = Season(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        episode = Episode(item=episode_item, related_season=season)

        bulk_media = {
            MediaTypes.EPISODE.value: [episode],
            MediaTypes.SEASON.value: [season],
            MediaTypes.TV.value: [tv],
        }

        helpers.bulk_create_media(bulk_media, self.user)

        self.assertEqual(TV.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Season.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            1,
        )
        self.assertEqual(Episode.objects.get().related_season_id, season.id)

    def _make_completed_season(self, media_id="42"):
        """Create a bulk-created Completed season with zero episodes."""
        tv_item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
            image="tv.jpg",
        )
        season_item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            image="season.jpg",
            season_number=1,
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        return Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.COMPLETED.value,
        )

    def test_backfill_retries_transient_network_error(self):
        """A single dropped connection should not strand a season at zero episodes."""
        season = self._make_completed_season()
        season_metadata = {
            "episodes": [{"episode_number": 1, "still_path": None}],
            "max_progress": 1,
        }

        with (
            patch(
                "app.providers.services.get_media_metadata",
                side_effect=[requests.ConnectionError("boom"), season_metadata],
            ),
            patch("integrations.imports.helpers.time.sleep"),
        ):
            warnings = helpers._backfill_completed_season_episodes([season])

        self.assertEqual(warnings, [])
        self.assertEqual(Episode.objects.filter(related_season=season).count(), 1)

    def test_backfill_surfaces_warning_after_exhausted_retries(self):
        """A persistently failing fetch should be reported, not silently dropped."""
        season = self._make_completed_season()

        with (
            patch(
                "app.providers.services.get_media_metadata",
                side_effect=requests.ConnectionError("still down"),
            ),
            patch("integrations.imports.helpers.time.sleep"),
        ):
            warnings = helpers._backfill_completed_season_episodes([season])

        self.assertEqual(len(warnings), 1)
        self.assertIn("Test Show", warnings[0])
        self.assertEqual(Episode.objects.filter(related_season=season).count(), 0)

    @patch("django.contrib.messages.error")
    def test_create_import_schedule(self, mock_messages):
        """Test creating import schedule."""
        request = Mock()
        request.user = self.user

        helpers.create_import_schedule(
            "testuser",
            request,
            "new",
            "daily",
            "14:30",
            "TestSource",
        )

        schedule = PeriodicTask.objects.first()
        self.assertIsNotNone(schedule)
        self.assertEqual(
            schedule.name,
            "Import from TestSource for testuser at 14:30:00 daily",
        )

        helpers.create_import_schedule(
            "testuser",
            request,
            "new",
            "daily",
            "14:30",
            "TestSource",
        )
        mock_messages.assert_called_with(
            request,
            "The same import task is already scheduled.",
        )

    @patch("django.contrib.messages.error")
    def test_create_import_schedule_invalid_time(self, mock_messages):
        """Test creating import schedule with invalid time."""
        request = Mock()
        request.user = self.user

        helpers.create_import_schedule(
            "testuser",
            request,
            "new",
            "daily",
            "25:00",  # Invalid time
            "TestSource",
        )

        mock_messages.assert_called_with(request, "Invalid import time.")
        self.assertEqual(PeriodicTask.objects.count(), 0)

    def test_get_deleted_media(self):
        """Test collecting deletion tombstones for a user."""
        other_credentials = {"username": "other", "password": "12345"}
        other_user = get_user_model().objects.create_user(**other_credentials)
        DeletedMedia.objects.create(
            user=self.user,
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            media_id="12345",
        )
        DeletedMedia.objects.create(
            user=other_user,
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            media_id="99999",
        )

        deleted = helpers.get_deleted_media(self.user)

        self.assertIn("12345", deleted[MediaTypes.TV.value][Sources.TMDB.value])
        self.assertNotIn("99999", deleted[MediaTypes.TV.value][Sources.TMDB.value])

    def test_should_process_media_skips_deleted_media(self):
        """Deleted media should be skipped regardless of new/overwrite mode."""
        existing_media = {}
        deleted_media = {MediaTypes.MOVIE.value: {Sources.TMDB.value: {"67890"}}}

        for mode in ("new", "overwrite"):
            to_delete = {}
            result = helpers.should_process_media(
                existing_media,
                to_delete,
                MediaTypes.MOVIE.value,
                Sources.TMDB.value,
                "67890",
                mode,
                deleted_media=deleted_media,
            )
            self.assertFalse(result)
            self.assertEqual(to_delete, {})

    def test_should_process_media_skip_existing_false_bypasses_new_mode_skip(self):
        """skip_existing=False lets an existing item through in 'new' mode.

        This is what Plex TV episode import relies on (issue #541): an
        already-tracked show must not block newly watched episodes of it.
        """
        existing_media = {
            MediaTypes.TV.value: {Sources.TMDB.value: {"12345": Mock()}},
        }
        to_delete = {}

        result = helpers.should_process_media(
            existing_media,
            to_delete,
            MediaTypes.TV.value,
            Sources.TMDB.value,
            "12345",
            "new",
            skip_existing=False,
        )

        self.assertTrue(result)
        self.assertEqual(to_delete, {})

    def test_should_process_media_skip_existing_default_still_skips(self):
        """Default behavior (skip_existing=True) is unchanged for other callers."""
        existing_media = {
            MediaTypes.TV.value: {Sources.TMDB.value: {"12345": Mock()}},
        }
        to_delete = {}

        result = helpers.should_process_media(
            existing_media,
            to_delete,
            MediaTypes.TV.value,
            Sources.TMDB.value,
            "12345",
            "new",
        )

        self.assertFalse(result)

    def test_create_import_schedule_every_2_days(self):
        """Test creating import schedule for every 2 days."""
        request = Mock()
        request.user = self.user

        helpers.create_import_schedule(
            "testuser",
            request,
            "new",
            "every_2_days",
            "14:30",
            "TestSource",
        )

        schedule = CrontabSchedule.objects.first()
        self.assertEqual(schedule.day_of_week, "*/2")
