from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import TV, Anime, Item, MediaTypes, Sources, Status
from app.providers import services
from events.calendar.selectors import (
    get_changed_tmdb_movie_ids,
    get_changed_tmdb_tv_ids,
    get_items_to_process,
)
from events.models import Event
from events.tests.calendar.utils import CalendarFixturesMixin


class CalendarSelectorTests(CalendarFixturesMixin, TestCase):
    """Test calendar item selection rules."""

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process(self, mock_tv_changes, mock_movie_changes):
        """Test the get_items_to_process function."""
        mock_tv_changes.return_value = {self.tv_item.media_id}
        mock_movie_changes.return_value = set()

        credentials = {"username": "test2", "password": "12345"}
        user2 = get_user_model().objects.create_user(**credentials)

        future_date = timezone.now() + timezone.timedelta(days=7)
        Event.objects.create(
            item=self.anime_item,
            content_number=1,
            datetime=future_date,
        )
        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=future_date,
        )

        past_date = timezone.now() - timezone.timedelta(days=30)
        Event.objects.create(
            item=self.manga_item,
            content_number=1,
            datetime=past_date,
        )

        old_past_date = timezone.now() - timezone.timedelta(days=400)
        Event.objects.create(
            item=self.book_item,
            content_number=1,
            datetime=old_past_date,
        )

        comic_recent_date = timezone.now() - timezone.timedelta(days=180)
        Event.objects.create(
            item=self.comic_item,
            content_number=1,
            datetime=comic_recent_date,
        )

        user2_item = Item.objects.create(
            media_id="888",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="User2 Anime",
            image="http://example.com/user2.jpg",
        )
        Anime.objects.create(
            item=user2_item,
            user=user2,
            status=Status.PLANNING.value,
        )

        items = get_items_to_process(self.user)

        self.assertIn(self.anime_item, items)
        self.assertIn(self.tv_item, items)
        self.assertIn(self.comic_item, items)
        self.assertIn(self.movie_item, items)
        self.assertNotIn(user2_item, items)
        self.assertNotIn(self.manga_item, items)
        self.assertNotIn(self.book_item, items)

        all_items = get_items_to_process()
        self.assertIn(self.anime_item, all_items)
        self.assertIn(user2_item, all_items)

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process_includes_completed_changed_tv(
        self,
        mock_tv_changes,
        mock_movie_changes,
    ):
        """Changed completed TV shows should still be selected."""
        mock_tv_changes.return_value = {self.tv_item.media_id}
        mock_movie_changes.return_value = set()
        TV.objects.filter(item=self.tv_item, user=self.user).update(
            status=Status.COMPLETED.value,
        )

        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=timezone.now() - timezone.timedelta(days=30),
        )

        items = get_items_to_process(self.user)

        self.assertIn(self.tv_item, items)

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process_excludes_unchanged_tv_with_events(
        self,
        mock_tv_changes,
        mock_movie_changes,
    ):
        """Tracked TV with existing season events should be skipped when unchanged."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = set()
        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=timezone.now() - timezone.timedelta(days=30),
        )

        items = get_items_to_process(self.user)

        self.assertNotIn(self.tv_item, items)

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process_includes_tv_without_season_events(
        self,
        mock_tv_changes,
        mock_movie_changes,
    ):
        """Tracked TMDB TV should bootstrap even when no season events exist yet."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = set()

        items = get_items_to_process(self.user)

        self.assertIn(self.tv_item, items)

    def _create_tvdb_tv(self):
        tvdb_tv_item = Item.objects.create(
            media_id="418666",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Witch Hat Atelier",
            image="http://example.com/witchhat.jpg",
        )
        TV.objects.create(
            item=tvdb_tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        tvdb_season_item = Item.objects.create(
            media_id="418666",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Witch Hat Atelier",
            image="http://example.com/witchhat.jpg",
            season_number=1,
        )
        return tvdb_tv_item, tvdb_season_item

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process_includes_tvdb_tv_without_season_events(
        self,
        mock_tv_changes,
        mock_movie_changes,
    ):
        """Tracked TVDB TV should bootstrap even when no season events exist yet."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = set()
        tvdb_tv_item, _ = self._create_tvdb_tv()

        items = get_items_to_process(self.user)

        self.assertIn(tvdb_tv_item, items)

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process_includes_tvdb_tv_with_future_events(
        self,
        mock_tv_changes,
        mock_movie_changes,
    ):
        """TVDB TV with future season events should refresh to keep dates current."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = set()
        tvdb_tv_item, tvdb_season_item = self._create_tvdb_tv()
        Event.objects.create(
            item=tvdb_season_item,
            content_number=1,
            datetime=timezone.now() + timezone.timedelta(days=7),
        )

        items = get_items_to_process(self.user)

        self.assertIn(tvdb_tv_item, items)

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process_includes_tvdb_tv_with_unknown_date_events(
        self,
        mock_tv_changes,
        mock_movie_changes,
    ):
        """TVDB TV with datetime.min unknown-date events should keep refreshing."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = set()
        tvdb_tv_item, tvdb_season_item = self._create_tvdb_tv()
        Event.objects.create(
            item=tvdb_season_item,
            content_number=1,
            datetime=timezone.now().replace(year=1, month=1, day=1),
        )

        items = get_items_to_process(self.user)

        self.assertIn(tvdb_tv_item, items)

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process_excludes_tvdb_tv_with_only_past_events(
        self,
        mock_tv_changes,
        mock_movie_changes,
    ):
        """Fully aired TVDB TV should not be refetched every run."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = set()
        tvdb_tv_item, tvdb_season_item = self._create_tvdb_tv()
        Event.objects.create(
            item=tvdb_season_item,
            content_number=1,
            datetime=timezone.now() - timezone.timedelta(days=30),
        )

        items = get_items_to_process(self.user)

        self.assertNotIn(tvdb_tv_item, items)

    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_changed_tmdb_tv_ids_returns_empty_on_provider_error(
        self,
        mock_tv_changes,
    ):
        """Provider failures should not break the whole refresh selection."""
        error = MagicMock()
        error.response.status_code = 500
        error.response.text = "boom"
        mock_tv_changes.side_effect = services.ProviderAPIError(
            provider=Sources.TMDB.value,
            error=error,
            details="boom",
        )

        self.assertEqual(get_changed_tmdb_tv_ids(), set())

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process_excludes_unchanged_movie_with_events(
        self,
        mock_tv_changes,
        mock_movie_changes,
    ):
        """Tracked TMDB movies with events should be skipped when unchanged."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = set()
        Event.objects.create(
            item=self.movie_item,
            content_number=None,
            datetime=timezone.now() - timezone.timedelta(days=30),
        )

        items = get_items_to_process(self.user)

        self.assertNotIn(self.movie_item, items)

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process_includes_changed_movie_with_existing_event(
        self,
        mock_tv_changes,
        mock_movie_changes,
    ):
        """Changed TMDB movies should be selected even with past events."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = {self.movie_item.media_id}
        Event.objects.create(
            item=self.movie_item,
            content_number=None,
            datetime=timezone.now() - timezone.timedelta(days=30),
        )

        items = get_items_to_process(self.user)

        self.assertIn(self.movie_item, items)

    @patch("events.calendar.selectors.tmdb.movie_changes")
    @patch("events.calendar.selectors.tmdb.tv_changes")
    def test_get_items_to_process_includes_movie_without_events(
        self,
        mock_tv_changes,
        mock_movie_changes,
    ):
        """Tracked TMDB movies should bootstrap when they do not have events yet."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = set()

        items = get_items_to_process(self.user)

        self.assertIn(self.movie_item, items)

    @patch("events.calendar.selectors.tmdb.movie_changes")
    def test_get_changed_tmdb_movie_ids_returns_empty_on_provider_error(
        self,
        mock_movie_changes,
    ):
        """Movie provider failures should not break refresh selection."""
        error = MagicMock()
        error.response.status_code = 500
        error.response.text = "boom"
        mock_movie_changes.side_effect = services.ProviderAPIError(
            provider=Sources.TMDB.value,
            error=error,
            details="boom",
        )

        self.assertEqual(get_changed_tmdb_movie_ids(), set())


class CalendarStalenessGateTests(CalendarFixturesMixin, TestCase):
    """Test that recently checked items are skipped."""

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    @override_settings(CALENDAR_ITEM_STALE_AFTER_HOURS=12)
    def test_recently_checked_item_is_excluded(self, _tv, _movie):
        """An item checked inside the window costs a provider call for nothing."""
        self.assertIn(self.book_item, get_items_to_process(self.user))

        Item.objects.filter(id=self.book_item.id).update(
            calendar_checked_at=timezone.now() - timezone.timedelta(hours=1),
        )

        self.assertNotIn(self.book_item, get_items_to_process(self.user))

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    @override_settings(CALENDAR_ITEM_STALE_AFTER_HOURS=12)
    def test_item_checked_before_the_window_is_included(self, _tv, _movie):
        """Once the window lapses the item is due for another check."""
        Item.objects.filter(id=self.book_item.id).update(
            calendar_checked_at=timezone.now() - timezone.timedelta(hours=13),
        )

        self.assertIn(self.book_item, get_items_to_process(self.user))

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes")
    @override_settings(CALENDAR_ITEM_STALE_AFTER_HOURS=12)
    def test_change_feed_hit_bypasses_the_window(self, mock_tv_changes, _movie):
        """A show TMDB reports as changed must be refreshed even if just checked."""
        mock_tv_changes.return_value = {self.tv_item.media_id}
        Item.objects.filter(id=self.tv_item.id).update(
            calendar_checked_at=timezone.now() - timezone.timedelta(minutes=5),
        )

        self.assertIn(self.tv_item, get_items_to_process(self.user))

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    @override_settings(CALENDAR_ITEM_STALE_AFTER_HOURS=0)
    def test_zero_disables_the_gate(self, _tv, _movie):
        """0 restores the previous always-refresh behaviour."""
        Item.objects.filter(id=self.book_item.id).update(
            calendar_checked_at=timezone.now(),
        )

        self.assertIn(self.book_item, get_items_to_process(self.user))
