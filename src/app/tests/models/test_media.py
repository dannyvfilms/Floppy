from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.utils import timezone

from app.models import (
    TV,
    Anime,
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)
from app.services.completion import select_preferred_activity_entry

mock_path = Path(__file__).resolve().parent.parent / "mock_data"


@tag("network")
class MediaModel(TestCase):
    """Test the custom save of the Media model."""

    def setUp(self):
        """Create a user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        item_anime = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Cowboy Bebop",
            image="http://example.com/image.jpg",
        )

        self.anime = Anime.objects.create(
            item=item_anime,
            user=self.user,
            status=Status.PLANNING.value,
        )

    def test_completed_progress(self):
        """When completed, the progress should be the total number of episodes."""
        self.anime.status = Status.COMPLETED.value
        self.anime.save()
        self.assertEqual(
            Anime.objects.get(item__media_id="1", user=self.user).progress,
            26,
        )

    def test_progress_is_max(self):
        """When progress is maximum number of episodes.

        Status should be completed and end_date the current date if not specified.
        """
        self.anime.status = Status.IN_PROGRESS.value
        self.anime.progress = 26
        self.anime.save()

        self.assertEqual(
            Anime.objects.get(item__media_id="1", user=self.user).status,
            Status.COMPLETED.value,
        )
        self.assertIsNotNone(
            Anime.objects.get(item__media_id="1", user=self.user).end_date,
        )

    def test_progress_bigger_than_max(self):
        """When progress is bigger than max, it should be set to max."""
        self.anime.status = Status.IN_PROGRESS.value
        self.anime.progress = 30
        self.anime.save()
        self.assertEqual(
            Anime.objects.get(item__media_id="1", user=self.user).progress,
            26,
        )


class CompletionNormalizationTests(TestCase):
    """Test planned activity cleanup when an item becomes completed."""

    def setUp(self):
        """Create a user and a reusable movie item."""
        self.user = get_user_model().objects.create_user(username="completion-user")
        self.item = Item.objects.create(
            media_id="movie-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Completion Movie",
        )
        self.fetch_releases = patch("app.models.Item.fetch_releases")
        self.fetch_releases.start()
        self.metadata = patch(
            "app.providers.services.get_media_metadata",
            return_value={"max_progress": 1},
        )
        self.metadata.start()
        self.addCleanup(self.fetch_releases.stop)
        self.addCleanup(self.metadata.stop)

    def test_new_completed_row_removes_planning_and_merges_metadata(self):
        """A separate completed play consumes the stale planning row."""
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
            score=8,
            notes="planned note",
        )

        completed = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=timezone.now(),
        )

        self.assertEqual(Movie.objects.filter(item=self.item).count(), 1)
        completed.refresh_from_db()
        self.assertEqual(completed.status, Status.COMPLETED.value)
        self.assertEqual(completed.score, 8)
        self.assertEqual(completed.notes, "planned note")
        self.assertIsNotNone(completed.end_date)

    def test_explicit_completed_fields_are_not_overwritten(self):
        """Explicit data on a completed play wins over planning metadata."""
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
            score=8,
            notes="planned note",
        )

        completed = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            score=9,
            notes="completed note",
        )

        self.assertEqual(completed.score, 9)
        self.assertEqual(completed.notes, "completed note")

    def test_repeated_completed_plays_remain_separate(self):
        """Cleaning planning does not deduplicate prior completed plays."""
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
        )

        self.assertEqual(
            Movie.objects.filter(item=self.item, status=Status.COMPLETED.value).count(),
            2,
        )
        self.assertFalse(
            Movie.objects.filter(item=self.item, status=Status.PLANNING.value).exists(),
        )

    def test_updating_planning_row_does_not_create_duplicate(self):
        """An exact row update upgrades the selected planning row in place."""
        planning = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        planning.status = Status.COMPLETED.value
        planning.end_date = timezone.now()
        planning.save()

        self.assertEqual(Movie.objects.filter(item=self.item).count(), 1)
        planning.refresh_from_db()
        self.assertEqual(planning.status, Status.COMPLETED.value)

    def test_pending_activity_is_selected_before_completed_activity(self):
        """Automatic activity updates prefer an unfinished row explicitly."""
        completed = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        planning = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        selected = select_preferred_activity_entry(
            Movie.objects.filter(item=self.item, user=self.user),
        )

        self.assertEqual(selected.pk, planning.pk)
        self.assertNotEqual(selected.pk, completed.pk)

    def test_tv_completion_rollup_is_not_normalized_as_item_activity(self):
        """TV roll-up saves keep their existing transition behavior."""
        tv_item = Item.objects.create(
            media_id="tv-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Roll-up Show",
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        with patch.object(TV, "_completed"):
            tv.status = Status.COMPLETED.value
            tv.save()

        self.assertEqual(TV.objects.filter(item=tv_item, user=self.user).count(), 1)

    def test_undated_planning_delete_invalidates_history_and_statistics(self):
        """Removing undated Planning clears user-level cached activity."""
        with (
            patch("app.signals.history_cache.invalidate_history_cache") as history,
            patch("app.signals.statistics_cache.invalidate_statistics_cache") as stats,
            patch(
                "app.signals.statistics_cache.invalidate_all_statistics_days",
            ) as stats_days,
            patch("app.signals.statistics_cache.schedule_all_ranges_refresh"),
        ):
            planning = Movie.objects.create(
                item=self.item,
                user=self.user,
                status=Status.PLANNING.value,
            )
            history.reset_mock()
            stats.reset_mock()
            stats_days.reset_mock()

            planning.delete()

        history.assert_called_once_with(self.user.id)
        stats.assert_called_once_with(self.user.id)
        stats_days.assert_called_once_with(self.user.id, reason="movie_change")
