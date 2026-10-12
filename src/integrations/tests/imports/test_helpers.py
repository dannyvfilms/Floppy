import json
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, tag
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
from app.services.completion import normalize_completed_entries
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

    @patch("app.providers.services.get_media_metadata", return_value={"max_progress": None})
    def test_batch_normalization_preserves_owner_source_and_first_watch(self, _metadata):
        """Plans merge into the first watch only, with original deletion hooks."""
        other = get_user_model().objects.create_user(username="other-planner")
        item = Item.objects.create(
            media_id="batch-movie", source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value, title="Batch Movie",
        )
        alternate = Item.objects.create(
            media_id="batch-movie", source=Sources.TVDB.value,
            media_type=MediaTypes.MOVIE.value, title="Alternate Source",
        )
        plan = Movie.objects.create(
            item=item, user=self.user, status=Status.PLANNING.value,
            score=7, notes="original plan",
        )
        unrelated = Movie.objects.create(
            item=alternate, user=self.user, status=Status.PLANNING.value,
        )
        other_plan = Movie.objects.create(
            item=item, user=other, status=Status.PLANNING.value, score=3,
        )
        watches = [
            Movie(item=item, user=self.user, status=Status.COMPLETED.value),
            Movie(item=item, user=self.user, status=Status.COMPLETED.value),
            Movie(item=item, user=other, status=Status.COMPLETED.value, notes="keep"),
        ]
        Movie.objects.bulk_create(watches)
        normalize_completed_entries(watches)
        for watch in watches:
            watch.refresh_from_db()
        self.assertEqual((watches[0].score, watches[0].notes), (7, "original plan"))
        self.assertIsNone(watches[1].score)
        self.assertEqual(watches[1].notes, "")
        self.assertEqual((watches[2].score, watches[2].notes), (3, "keep"))
        self.assertFalse(Movie.objects.filter(pk__in=[plan.pk, other_plan.pk]).exists())
        self.assertTrue(Movie.objects.filter(pk=unrelated.pk).exists())

    @tag("slow", "benchmark")
    def test_batch_normalization_bounds_distinct_item_parameters(self):
        """Distinct identities use bounded queries, rather than one large IN list."""
        items = Item.objects.bulk_create([
            Item(media_id=f"bounded-plan-{index}", source=Sources.TMDB.value,
                 media_type=MediaTypes.MOVIE.value, title="Bounded Movie")
            for index in range(1001)
        ])
        watches = Movie.objects.bulk_create([
            Movie(item=item, user=self.user, status=Status.COMPLETED.value)
            for item in items
        ])
        with self.assertNumQueries(3):
            normalize_completed_entries(watches)

    @tag("slow", "benchmark")
    @patch("app.providers.services.get_media_metadata", return_value={"max_progress": None})
    def test_batch_episode_normalization_queries_do_not_grow_per_watch(self, _metadata):
        """A thousand completed watches preload owner and planning state once."""
        show_item = Item.objects.create(
            media_id="batch-show", source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value, title="Batch Show",
        )
        season_item = Item.objects.create(
            media_id="batch-show", source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value, season_number=1, title="Season",
        )
        episode_item = Item.objects.create(
            media_id="batch-show", source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value, season_number=1,
            episode_number=1, title="Episode",
        )
        tv = TV.objects.create(item=show_item, user=self.user, status=Status.PLANNING.value)
        season = Season.objects.create(
            item=season_item, user=self.user, related_tv=tv, status=Status.PLANNING.value,
        )
        watches = Episode.objects.bulk_create([
            Episode(item=episode_item, related_season=season, status=Status.COMPLETED.value)
            for _ in range(1000)
        ])
        with self.assertNumQueries(2):
            normalize_completed_entries(watches)
        self.assertEqual(Episode.objects.filter(related_season=season).count(), 1000)

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

    def _unsaved_tv_season_episode(self):
        tv_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
        )
        season_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            season_number=1,
        )
        episode_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Show",
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
        return {
            MediaTypes.EPISODE.value: [episode],
            MediaTypes.SEASON.value: [season],
            MediaTypes.TV.value: [tv],
        }

    @patch("integrations.episode_orders.resolve_incoming")
    def test_bulk_create_media_skips_order_lookup_without_active_orders(
        self,
        mock_resolve,
    ):
        """No tracked show has an alternate order, so no episode can map to one."""
        helpers.bulk_create_media(self._unsaved_tv_season_episode(), self.user)

        mock_resolve.assert_not_called()
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            1,
        )

    @patch("integrations.episode_orders.resolve_incoming", return_value=None)
    def test_bulk_create_media_still_resolves_orders_for_a_show_with_one(
        self,
        mock_resolve,
    ):
        from app.services.episode_ordering import persist_order

        bulk_media = self._unsaved_tv_season_episode()
        tv = TV.objects.create(
            item=bulk_media[MediaTypes.TV.value][0].item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        order = persist_order(
            tv.item,
            Sources.TMDB.value,
            "1396",
            "aired",
            "TMDB (Aired)",
            {
                "episodes": [
                    {
                        "provider_episode_id": "new-1",
                        "season_number": 1,
                        "episode_number": 1,
                        "title": "Pilot",
                        "image": "",
                    },
                ],
            },
        )
        TV.objects.filter(pk=tv.pk).update(active_episode_order=order)
        bulk_media.pop(MediaTypes.TV.value)
        bulk_media.pop(MediaTypes.SEASON.value)
        episode = bulk_media[MediaTypes.EPISODE.value][0]
        episode.related_season = Season.objects.create(
            item=Item.objects.get(
                media_type=MediaTypes.SEASON.value,
                media_id="1396",
            ),
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )

        helpers.bulk_create_media(bulk_media, self.user)

        mock_resolve.assert_called_once()

    def test_bulk_create_media_skips_episode_with_no_matching_season(self):
        """An unresolvable episode is dropped with a warning, not a DB crash.

        Regression for issue #1151: bulk_create_with_history previously
        received an Episode with a NULL related_season_id and raised
        IntegrityError, aborting the whole batch.
        """
        episode_item = Item.objects.create(
            media_id="orphan",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Orphan Show",
            season_number=1,
            episode_number=1,
        )
        episode = Episode(item=episode_item)

        warnings = helpers.bulk_create_media(
            {MediaTypes.EPISODE.value: [episode]},
            self.user,
        )

        self.assertEqual(Episode.objects.count(), 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("orphan", warnings[0])
        self.assertIn("S1", warnings[0])

    def test_bulk_create_media_keeps_episode_linked_directly_to_unsaved_season(self):
        """An episode built with a direct (unsaved) Season reference still saves.

        Regression: filtering on related_season_id alone (instead of the
        cached related_season object) incorrectly dropped an episode whose
        FK column read empty even though it was correctly linked in memory
        to a Season created earlier in the same batch - bulk_create() later
        self-heals that column from the cached object's pk.
        """
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
        tv = TV(item=tv_item, user=self.user, status=Status.IN_PROGRESS.value)
        season = Season(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )

        episodes = []
        for episode_number in (1, 2):
            episode_item = Item.objects.create(
                media_id="1",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Test Show",
                image="episode.jpg",
                season_number=1,
                episode_number=episode_number,
            )
            episodes.append(Episode(item=episode_item, related_season=season))

        bulk_media = {
            MediaTypes.EPISODE.value: episodes,
            MediaTypes.SEASON.value: [season],
            MediaTypes.TV.value: [tv],
        }

        warnings = helpers.bulk_create_media(bulk_media, self.user)

        self.assertEqual(warnings, [])
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            2,
        )

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

    @patch("django.contrib.messages.success")
    def test_create_import_schedule_replace_existing_refreshes_kwargs(
        self,
        _mock_success,
    ):
        """Reconnecting an account updates its schedule instead of keeping a dead token."""
        request = Mock()
        request.user = self.user
        args = ("testuser", request, "new", "daily", "14:30", "TestSource")

        helpers.create_import_schedule(*args, token="old-token")
        helpers.create_import_schedule(
            *args,
            token="new-token",
            extra_kwargs={"redirect_uri": "https://floppy.example.com/cb"},
            replace_existing=True,
        )

        self.assertEqual(PeriodicTask.objects.count(), 1)
        task_kwargs = json.loads(PeriodicTask.objects.get().kwargs)
        self.assertEqual(task_kwargs["token"], "new-token")
        self.assertEqual(task_kwargs["redirect_uri"], "https://floppy.example.com/cb")
        self.assertEqual(task_kwargs["username"], "testuser")

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


class GetOrCreateItemAcrossBucketsTests(TestCase):
    """An identity stored in several library buckets must not abort an import."""

    identity = {
        "media_id": "1396",
        "source": Sources.TMDB.value,
        "media_type": MediaTypes.TV.value,
    }

    def _create(self, bucket):
        return Item.objects.create(
            **self.identity,
            library_media_type=bucket,
            title="Breaking Bad",
            image="https://example.com/bb.jpg",
        )

    def test_reuses_existing_row_when_identity_is_in_two_buckets(self):
        """Prefers the requested bucket, where get_or_create raised."""
        tv = self._create(MediaTypes.TV.value)
        self._create(MediaTypes.SEASON.value)

        item, created = helpers.get_or_create_item_across_buckets(
            preferred_bucket=MediaTypes.TV.value,
            defaults={"title": "ignored", "image": "x"},
            **self.identity,
        )

        self.assertFalse(created)
        self.assertEqual(item, tv)
        self.assertEqual(Item.objects.filter(**self.identity).count(), 2)

    def test_creates_row_when_identity_is_missing(self):
        """Falls back to a plain get_or_create when nothing exists."""
        item, created = helpers.get_or_create_item_across_buckets(
            defaults={"title": "Breaking Bad", "image": "x"},
            **self.identity,
        )

        self.assertTrue(created)
        self.assertEqual(item.title, "Breaking Bad")

    def test_prefers_the_row_the_user_already_tracks(self):
        """Another user's row in the preferred bucket must not win."""
        user = get_user_model().objects.create_user(username="a", password="x")
        other = get_user_model().objects.create_user(username="b", password="x")
        self._create(MediaTypes.TV.value)
        mine = self._create(MediaTypes.SEASON.value)
        TV.objects.create(item=mine, user=user, status=Status.PLANNING.value)
        TV.objects.create(
            item=Item.objects.get(
                **self.identity,
                library_media_type=MediaTypes.TV.value,
            ),
            user=other,
            status=Status.PLANNING.value,
        )

        item, created = helpers.get_or_create_item_across_buckets(
            preferred_bucket=MediaTypes.TV.value,
            user=user,
            **self.identity,
        )

        self.assertFalse(created)
        self.assertEqual(item, mine)
