from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import Item, MediaTypes, Podcast, Sources, Status


@patch("app.history_cache.invalidate_history_days")
@patch("app.history_cache.invalidate_history_cache")
class PodcastHistoryInvalidationTests(TestCase):
    """History places podcasts by end date; undated saves must not wipe it (#1158)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="listener", password="pass"
        )
        item = Item.objects.create(
            media_id="ep-uuid",
            source=Sources.GPODDER.value,
            media_type=MediaTypes.PODCAST.value,
            title="Episode",
            image="https://example.com/ep.jpg",
        )
        self.podcast = Podcast.objects.create(
            user=self.user,
            item=item,
            status=Status.IN_PROGRESS.value,
            progress=2,
        )

    def test_undated_create_and_progress_update_skip_the_history_wipe(
        self, mock_invalidate_all, mock_invalidate_days
    ):
        self.podcast.progress = 5
        self.podcast.save(update_fields=["progress"])

        mock_invalidate_all.assert_not_called()
        mock_invalidate_days.assert_not_called()

    def test_full_save_of_an_unfinished_podcast_with_a_start_date_skips_the_wipe(
        self, mock_invalidate_all, mock_invalidate_days
    ):
        """The Pocket Casts poll saves in-progress podcasts without update_fields."""
        Podcast.objects.filter(pk=self.podcast.pk).update(start_date=timezone.now())
        self.podcast.refresh_from_db()
        self.podcast.progress = 9
        self.podcast.save()

        mock_invalidate_all.assert_not_called()
        mock_invalidate_days.assert_not_called()

    def test_completion_invalidates_only_its_day(
        self, mock_invalidate_all, mock_invalidate_days
    ):
        self.podcast.end_date = timezone.now()
        self.podcast.status = Status.COMPLETED.value
        self.podcast.save(update_fields=["end_date", "status"])

        mock_invalidate_all.assert_not_called()
        mock_invalidate_days.assert_called()

    def test_full_save_that_may_clear_the_end_date_still_wipes(
        self, mock_invalidate_all, _mock_invalidate_days
    ):
        Podcast.objects.filter(pk=self.podcast.pk).update(end_date=timezone.now())
        self.podcast.end_date = None
        self.podcast.save()

        mock_invalidate_all.assert_called_with(
            self.user.id, reason="undated_media_change"
        )
