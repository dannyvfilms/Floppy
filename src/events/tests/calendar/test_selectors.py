from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import TV, Anime, Item, MediaTypes, Music, Sources, Status, Video
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
        """Recently checked TV with existing season events is skipped when unchanged."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = set()
        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=timezone.now() - timezone.timedelta(days=30),
        )
        Item.objects.filter(id=self.tv_item.id).update(
            calendar_checked_at=timezone.now() - timezone.timedelta(days=1),
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
        """Recently checked, fully aired TVDB TV should not be refetched every run."""
        mock_tv_changes.return_value = set()
        mock_movie_changes.return_value = set()
        tvdb_tv_item, tvdb_season_item = self._create_tvdb_tv()
        Event.objects.create(
            item=tvdb_season_item,
            content_number=1,
            datetime=timezone.now() - timezone.timedelta(days=30),
        )
        Item.objects.filter(id=tvdb_tv_item.id).update(
            calendar_checked_at=timezone.now() - timezone.timedelta(days=1),
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


class CalendarMusicSelectionTests(CalendarFixturesMixin, TestCase):
    """Music tracks never gain calendar events, so they are never fetched."""

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_tracked_music_is_not_selected(self, _tv, _movie):
        """A music track has no events, so it used to be selected every reload."""
        item = Item.objects.create(
            media_id="11111111-1111-1111-1111-111111111111",
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            title="Some Song",
            image="http://example.com/song.jpg",
        )
        Music.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)

        self.assertNotIn(item, get_items_to_process(self.user))
        self.assertNotIn(item, get_items_to_process())
        self.assertIn(self.anime_item, get_items_to_process(self.user))


class CalendarVideoSelectionTests(CalendarFixturesMixin, TestCase):
    """Videos are checked for an upload date, with no provider call."""

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_tracked_video_is_selected(self, _tv, _movie):
        """A watched video gets a Calendar event on its upload date."""
        item = Item.objects.create(
            media_id="vid1",
            source=Sources.YOUTUBE.value,
            media_type=MediaTypes.VIDEO.value,
            title="A Video",
            image="http://example.com/video.jpg",
        )
        Video.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)

        self.assertIn(item, get_items_to_process(self.user))


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
    @override_settings(CALENDAR_ITEM_STALE_AFTER_HOURS=12)
    def test_show_without_season_events_follows_the_window(self, _tv, _movie):
        """A show without season events is not re-fetched on every reload (#1158)."""
        self.assertIn(self.tv_item, get_items_to_process(self.user))

        Item.objects.filter(id=self.tv_item.id).update(
            calendar_checked_at=timezone.now() - timezone.timedelta(hours=1),
        )
        self.assertNotIn(self.tv_item, get_items_to_process(self.user))

        Item.objects.filter(id=self.tv_item.id).update(
            calendar_checked_at=timezone.now() - timezone.timedelta(hours=13),
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


@override_settings(
    CALENDAR_ITEM_STALE_AFTER_HOURS=12, CALENDAR_AIRED_SHOW_RECHECK_DAYS=7
)
class CalendarAiredShowRecheckTests(CalendarFixturesMixin, TestCase):
    """A fully aired show is looked at again so a new season can be found (#1531)."""

    def _checked(self, item, days_ago):
        Item.objects.filter(id=item.id).update(
            calendar_checked_at=timezone.now() - timezone.timedelta(days=days_ago),
        )

    def _aired_event(self, season_item):
        Event.objects.create(
            item=season_item,
            content_number=1,
            datetime=timezone.now() - timezone.timedelta(days=30),
        )

    def _tvdb_show(self):
        tv_item = Item.objects.create(
            media_id="361753",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Sheriff Country",
            image="http://example.com/sheriff.jpg",
        )
        TV.objects.create(item=tv_item, user=self.user, status=Status.COMPLETED.value)
        season_item = Item.objects.create(
            media_id="361753",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Sheriff Country",
            image="http://example.com/sheriff.jpg",
            season_number=2,
        )
        self._aired_event(season_item)
        return tv_item

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_tmdb_aired_show_is_rechecked_once_a_week(self, _tv, _movie):
        """With no change-feed hit, a finished-looking show is still revisited."""
        self._aired_event(self.season_item)

        self._checked(self.tv_item, days_ago=1)
        self.assertNotIn(self.tv_item, get_items_to_process(self.user))

        self._checked(self.tv_item, days_ago=8)
        self.assertIn(self.tv_item, get_items_to_process(self.user))

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_tmdb_aired_show_never_checked_is_included(self, _tv, _movie):
        """A show that was never stamped as checked is due."""
        self._aired_event(self.season_item)
        Item.objects.filter(id=self.tv_item.id).update(calendar_checked_at=None)

        self.assertIn(self.tv_item, get_items_to_process(self.user))

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_tmdb_show_with_future_episode_is_not_rechecked(self, _tv, _movie):
        """A show still airing is left to the change feed, as before."""
        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=timezone.now() + timezone.timedelta(days=7),
        )
        self._checked(self.tv_item, days_ago=8)

        self.assertNotIn(self.tv_item, get_items_to_process(self.user))

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_tvdb_aired_show_is_rechecked_once_a_week(self, _tv, _movie):
        """TVDB has no change feed, so this is the only way it finds a new season."""
        tv_item = self._tvdb_show()

        self._checked(tv_item, days_ago=1)
        self.assertNotIn(tv_item, get_items_to_process(self.user))

        self._checked(tv_item, days_ago=8)
        self.assertIn(tv_item, get_items_to_process(self.user))

    def _tmdb_counterpart(self, tvdb_item, *, datetime_value):
        self.tv_item.provider_external_ids = {"tvdb_id": tvdb_item.media_id}
        self.tv_item.save(update_fields=["provider_external_ids"])
        season_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Breaking Bad",
            image="http://example.com/breakingbad.jpg",
            season_number=2,
        )
        Event.objects.create(
            item=season_item,
            content_number=1,
            datetime=datetime_value,
        )

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_tvdb_show_follows_its_tmdb_counterpart_before_the_week_is_up(
        self, _tv, _movie
    ):
        """A new season the TMDB identity already sees should refresh TVDB too."""
        tvdb_item = self._tvdb_show()
        self._checked(tvdb_item, days_ago=1)
        self._tmdb_counterpart(
            tvdb_item,
            datetime_value=timezone.now() + timezone.timedelta(days=7),
        )

        self.assertIn(tvdb_item, get_items_to_process(self.user))

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_tvdb_show_with_only_past_counterpart_events_stays_skipped(
        self, _tv, _movie
    ):
        """The counterpart trigger needs an upcoming episode, not just any event."""
        tvdb_item = self._tvdb_show()
        self._checked(tvdb_item, days_ago=1)
        self._tmdb_counterpart(
            tvdb_item,
            datetime_value=timezone.now() - timezone.timedelta(days=7),
        )

        self.assertNotIn(tvdb_item, get_items_to_process(self.user))

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    @override_settings(CALENDAR_AIRED_SHOW_RECHECK_DAYS=0)
    def test_zero_disables_the_recheck(self, _tv, _movie):
        """0 restores the previous behaviour for both providers."""
        self._aired_event(self.season_item)
        tvdb_item = self._tvdb_show()
        self._checked(self.tv_item, days_ago=30)
        self._checked(tvdb_item, days_ago=30)

        selected = get_items_to_process(self.user)
        self.assertNotIn(self.tv_item, selected)
        self.assertNotIn(tvdb_item, selected)

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_tmdb_show_with_undated_season_is_rechecked_before_the_week_is_up(
        self, _tv, _movie
    ):
        """A season TMDB listed without air dates is looked at again for the dates."""
        self._aired_event(self.season_item)
        undated_season = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Breaking Bad",
            image="http://example.com/breakingbad.jpg",
            season_number=2,
        )
        undated_event = Event.objects.create(
            item=undated_season,
            content_number=1,
            datetime=datetime.min.replace(tzinfo=UTC),
        )
        self._checked(self.tv_item, days_ago=2)

        self.assertIn(self.tv_item, get_items_to_process(self.user))

        # Once TMDB publishes the date nothing keeps the show in the list.
        Event.objects.filter(pk=undated_event.pk).update(
            datetime=timezone.now() - timezone.timedelta(days=3),
        )
        self.assertNotIn(self.tv_item, get_items_to_process(self.user))

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_undated_special_does_not_keep_a_show_in_the_reload(self, _tv, _movie):
        """Season 0 specials often never get a date; they are not a new season."""
        self._aired_event(self.season_item)
        specials = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Breaking Bad",
            image="http://example.com/breakingbad.jpg",
            season_number=0,
        )
        Event.objects.create(
            item=specials,
            content_number=1,
            datetime=datetime.min.replace(tzinfo=UTC),
        )
        self._checked(self.tv_item, days_ago=2)

        self.assertNotIn(self.tv_item, get_items_to_process(self.user))

    @patch("events.calendar.selectors.tmdb.movie_changes", return_value=set())
    @patch("events.calendar.selectors.tmdb.tv_changes", return_value=set())
    def test_selection_names_finished_shows_it_skipped(self, _tv, _movie):
        """The log says which finished shows were left out, so a bug report can tell."""
        self._aired_event(self.season_item)
        self._checked(self.tv_item, days_ago=2)

        with self.assertLogs("events.calendar.selectors", level="INFO") as logs:
            get_items_to_process(self.user)

        self.assertTrue(
            any(
                "skipped finished shows" in line and "Breaking Bad (1396, checked "
                in line
                for line in logs.output
            ),
            logs.output,
        )
