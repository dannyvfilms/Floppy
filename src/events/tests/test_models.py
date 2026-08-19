import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    TV,
    Anime,
    Item,
    Manga,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from events.models import Event


class EventModelTests(TestCase):
    """Test the Event model."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "testuser", "password": "testpassword"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        # Create test items
        self.season_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test TV Show",
            season_number=1,
        )

        self.movie_item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
        )

        self.anime_item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Anime",
        )

        self.manga_item = Item.objects.create(
            media_id="66296374554",
            source=Sources.MANGAUPDATES.value,
            media_type=MediaTypes.MANGA.value,
            title="Test Manga",
        )

        self.season = Season.objects.create(
            user=self.user,
            item=self.season_item,
            status=Status.IN_PROGRESS.value,
        )

        self.movie = Movie.objects.create(
            user=self.user,
            item=self.movie_item,
            status=Status.PLANNING.value,
        )

        self.anime = Anime.objects.create(
            user=self.user,
            item=self.anime_item,
            status=Status.IN_PROGRESS.value,
        )

        self.manga = Manga.objects.create(
            user=self.user,
            item=self.manga_item,
            status=Status.IN_PROGRESS.value,
        )

        # Create events
        self.now = timezone.now()
        self.tomorrow = self.now + datetime.timedelta(days=1)
        self.next_week = self.now + datetime.timedelta(days=7)

        self.season_event = Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=self.tomorrow,
        )

        self.movie_event = Event.objects.create(
            item=self.movie_item,
            datetime=self.next_week,
        )

        self.anime_event = Event.objects.create(
            item=self.anime_item,
            content_number=1,
            datetime=self.tomorrow,
        )

        self.manga_event = Event.objects.create(
            item=self.manga_item,
            content_number=1,
            datetime=self.tomorrow,
        )

    def test_event_string_representation(self):
        """Test the string representation of events."""
        # Season event
        self.assertEqual(
            str(self.season_event),
            "Test TV Show S1 E1",
        )

        # Movie event
        self.assertEqual(str(self.movie_event), "Test Movie")

        # Anime event
        self.assertEqual(str(self.anime_event), "Test Anime E1")

        # Manga event
        self.assertEqual(str(self.manga_event), "Test Manga #1")


class EventManagerTests(TestCase):
    """Test the EventManager custom manager."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "testuser", "password": "testpassword"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.credentials_other = {"username": "otheruser", "password": "testpassword"}
        self.other_user = get_user_model().objects.create_user(**self.credentials_other)

        # Create test items
        self.tv_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test TV Show",
        )

        self.season_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test TV Show",
            season_number=1,
        )

        self.movie_item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
        )

        self.paused_movie_item = Item.objects.create(
            media_id="278",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Paused Movie",
        )

        self.dropped_movie_item = Item.objects.create(
            media_id="424",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Dropped Movie",
        )

        self.manga_item = Item.objects.create(
            media_id="66296374554",
            source=Sources.MANGAUPDATES.value,
            media_type=MediaTypes.MANGA.value,
            title="Test Manga",
        )

        # Create media objects
        self.tv = TV.objects.create(
            user=self.user,
            item=self.tv_item,
            status=Status.IN_PROGRESS.value,
        )

        self.other_tv = TV.objects.create(
            user=self.other_user,
            item=self.tv_item,
            status=Status.IN_PROGRESS.value,
        )

        self.movie = Movie.objects.create(
            user=self.user,
            item=self.movie_item,
            status=Status.PLANNING.value,
        )

        self.paused_movie = Movie.objects.create(
            user=self.user,
            item=self.paused_movie_item,
            status=Status.PAUSED.value,
        )

        self.dropped_movie = Movie.objects.create(
            user=self.user,
            item=self.dropped_movie_item,
            status=Status.DROPPED.value,
        )

        self.manga = Manga.objects.create(
            user=self.user,
            item=self.manga_item,
            status=Status.IN_PROGRESS.value,
        )

        # Use fixed dates instead of timezone.now()
        # Base date: April 15, 2025 at noon UTC
        self.base_date = datetime.datetime(2025, 4, 15, 12, 0, 0, tzinfo=datetime.UTC)
        self.yesterday = self.base_date - datetime.timedelta(days=1)  # April 14
        self.tomorrow = self.base_date + datetime.timedelta(days=1)  # April 16
        self.next_week = self.base_date + datetime.timedelta(days=7)  # April 22

        # Create events with fixed dates
        self.past_event = Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=self.yesterday,  # April 14
        )

        self.movie_event = Event.objects.create(
            item=self.movie_item,
            datetime=self.next_week,  # April 22
        )

        self.paused_movie_event = Event.objects.create(
            item=self.paused_movie_item,
            datetime=self.next_week,  # April 22
        )

        self.dropped_movie_event = Event.objects.create(
            item=self.dropped_movie_item,
            datetime=self.next_week,  # April 22
        )

        self.season_event = Event.objects.create(
            item=self.season_item,
            content_number=2,
            datetime=self.tomorrow,  # April 16
        )

        # Manga with multiple events
        self.manga_event1 = Event.objects.create(
            item=self.manga_item,
            content_number=1,
            datetime=self.tomorrow,  # April 16
        )

        self.manga_event2 = Event.objects.create(
            item=self.manga_item,
            content_number=2,
            datetime=self.next_week,  # April 22
        )

    def test_get_user_events(self):
        """Test the get_user_events method."""
        # Use fixed dates for testing
        today = self.base_date.date()  # April 15
        next_week = today + datetime.timedelta(days=7)  # April 22

        # Get events for the user
        events = Event.objects.get_user_events(self.user, today, next_week)

        # Should include season, movie, and manga events
        self.assertEqual(events.count(), 4)
        self.assertIn(self.season_event, events)
        self.assertIn(self.manga_event1, events)
        self.assertIn(self.movie_event, events)
        self.assertIn(self.manga_event2, events)
        self.assertNotIn(self.past_event, events)

        # Get events for the other user
        other_events = Event.objects.get_user_events(self.other_user, today, next_week)

        # Other user has TV as active, so get season events
        self.assertEqual(other_events.count(), 1)

        # Test with a different date range
        tomorrow = today + datetime.timedelta(days=1)  # April 16
        limited_events = Event.objects.get_user_events(self.user, today, tomorrow)

        self.assertEqual(limited_events.count(), 2)
        self.assertIn(self.season_event, limited_events)  # Season event in range
        self.assertIn(self.manga_event1, limited_events)  # Manga event in range
        self.assertNotIn(self.movie_event, limited_events)  # Outside range
        self.assertNotIn(
            self.past_event,
            limited_events,
        )  # Past event, but filtered by active status


class EventManagerCrossProviderDedupTests(TestCase):
    """The calendar must not show the same real episode twice (#639)."""

    def setUp(self):
        self.credentials = {"username": "dedup-cal-user", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def _tv_pair(self, tvdb_id="81189"):
        """Create a show tracked under both a TMDB and a verified TVDB identity."""
        tmdb_show = Item.objects.create(
            title="Breaking Bad",
            media_id="1396",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="",
            provider_external_ids={"tvdb_id": tvdb_id},
        )
        tvdb_show = Item.objects.create(
            title="Breaking Bad",
            media_id=tvdb_id,
            media_type=MediaTypes.TV.value,
            source=Sources.TVDB.value,
            image="",
        )
        TV.objects.create(
            item=tmdb_show,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        TV.objects.create(
            item=tvdb_show,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        tmdb_season = Item.objects.create(
            title="Breaking Bad",
            media_id="1396",
            media_type=MediaTypes.SEASON.value,
            source=Sources.TMDB.value,
            image="",
            season_number=1,
            provider_external_ids={"tvdb_id": tvdb_id},
        )
        tvdb_season = Item.objects.create(
            title="Breaking Bad",
            media_id=tvdb_id,
            media_type=MediaTypes.SEASON.value,
            source=Sources.TVDB.value,
            image="",
            season_number=1,
        )
        return tmdb_season, tvdb_season

    def test_get_user_events_hides_non_preferred_duplicate(self):
        tmdb_season, tvdb_season = self._tv_pair()
        when = timezone.now() + datetime.timedelta(days=1)
        tmdb_event = Event.objects.create(
            item=tmdb_season,
            content_number=1,
            datetime=when,
        )
        tvdb_event = Event.objects.create(
            item=tvdb_season,
            content_number=1,
            datetime=when,
        )
        self.user.tv_metadata_source_default = Sources.TMDB.value
        self.user.save(update_fields=["tv_metadata_source_default"])

        events = Event.objects.get_user_events(self.user, when.date(), when.date())

        self.assertEqual(list(events), [tmdb_event])
        self.assertNotIn(tvdb_event, events)

    def test_get_user_events_follows_preferred_source_switch(self):
        tmdb_season, tvdb_season = self._tv_pair()
        when = timezone.now() + datetime.timedelta(days=1)
        tmdb_event = Event.objects.create(
            item=tmdb_season,
            content_number=1,
            datetime=when,
        )
        tvdb_event = Event.objects.create(
            item=tvdb_season,
            content_number=1,
            datetime=when,
        )
        self.user.tv_metadata_source_default = Sources.TVDB.value
        self.user.save(update_fields=["tv_metadata_source_default"])

        events = Event.objects.get_user_events(self.user, when.date(), when.date())

        self.assertEqual(list(events), [tvdb_event])
        self.assertNotIn(tmdb_event, events)

    def test_get_user_events_keeps_unrelated_shows_sharing_a_title(self):
        """Two unrelated shows sharing a title but no verified tvdb link both survive."""
        remake_show = Item.objects.create(
            title="Breaking Bad",
            media_id="999999",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="",
        )
        remake_season = Item.objects.create(
            title="Breaking Bad",
            media_id="999999",
            media_type=MediaTypes.SEASON.value,
            source=Sources.TMDB.value,
            image="",
            season_number=1,
        )
        tvdb_show = Item.objects.create(
            title="Breaking Bad",
            media_id="81189",
            media_type=MediaTypes.TV.value,
            source=Sources.TVDB.value,
            image="",
        )
        tvdb_season = Item.objects.create(
            title="Breaking Bad",
            media_id="81189",
            media_type=MediaTypes.SEASON.value,
            source=Sources.TVDB.value,
            image="",
            season_number=1,
        )
        TV.objects.create(
            item=remake_show,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        TV.objects.create(
            item=tvdb_show,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        when = timezone.now() + datetime.timedelta(days=1)
        remake_event = Event.objects.create(
            item=remake_season,
            content_number=1,
            datetime=when,
        )
        tvdb_event = Event.objects.create(
            item=tvdb_season,
            content_number=1,
            datetime=when,
        )

        events = Event.objects.get_user_events(self.user, when.date(), when.date())

        self.assertCountEqual(list(events), [remake_event, tvdb_event])

    def test_get_user_events_stays_a_queryset_for_media_type_filtering(self):
        """download_calendar chains a media-type filter after get_user_events."""
        tmdb_season, _tvdb_season = self._tv_pair()
        when = timezone.now() + datetime.timedelta(days=1)
        Event.objects.create(item=tmdb_season, content_number=1, datetime=when)

        events = Event.objects.get_user_events(self.user, when.date(), when.date())
        filtered = events.filter(item__media_type__in=[MediaTypes.SEASON.value])

        self.assertEqual(filtered.count(), 1)
